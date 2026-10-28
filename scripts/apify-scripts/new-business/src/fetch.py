"""Direct HTTP first. Proxy only after a block. CAPTCHA only if that still fails.

robots.txt is evaluated with the longest-match helper before a host is
fetched. A disallow is not retried through a proxy. Spend is reserved only
when a proxy request is sent or a solver returns a token.
"""

from __future__ import annotations

import logging
import os
import random
import time
import uuid
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import quote, urlparse

try:
    from .runtime import USER_AGENT, prepare_imports
    from .spend import CAPTCHA_EVENT, PROXY_EVENT, Ledger
except ImportError:
    from runtime import USER_AGENT, prepare_imports
    from spend import CAPTCHA_EVENT, PROXY_EVENT, Ledger


MAX_BYTES = 8 * 1024 * 1024
log = logging.getLogger("apify")

# Strong challenge markers only. A page that merely says "captcha" in prose
# is not treated as a wall.
CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "cf-challenge",
    "challenge-platform",
    "/cdn-cgi/challenge",
    "just a moment",
    "attention required",
    "turnstile",
    "hcaptcha",
    "g-recaptcha",
    "recaptcha",
    "data-sitekey",
)


class _Response:
    """Object shape expected by new_business_website / website_quality."""

    def __init__(self, result, url):
        self.status_code = int((result or {}).get("status") or 0)
        self.text = (result or {}).get("text") or ""
        self.url = url
        self.headers = {}


def looks_json(result):
    ctype = ((result or {}).get("content_type") or "").lower()
    if "json" in ctype:
        return True
    text = ((result or {}).get("text") or "").lstrip()
    return text.startswith("{") or text.startswith("[")


def is_captcha(result):
    if looks_json(result):
        return False
    haystack = f"{(result or {}).get('text') or ''} {(result or {}).get('url') or ''}".lower()
    return any(marker in haystack for marker in CHALLENGE_MARKERS)


def is_block(result):
    result = result or {}
    if result.get("error") in ("robots_disallowed", "request_cap", "proxy_unavailable"):
        return False
    status = int(result.get("status") or 0)
    if status in (401, 403, 429):
        return True
    return is_captcha(result)


def default_solver(url, html):
    """No paid solver ships with this Actor. None means the run stops unpaid."""
    return None


def _cap():
    return {"status": 0, "text": "", "error": "request_cap", "content_type": "", "url": ""}


def _blocked(result, stop):
    body = dict(result or {})
    body["error"] = "blocked"
    body["stop"] = stop
    body.setdefault("status", 403)
    body.setdefault("text", "")
    body.setdefault("content_type", "text/html")
    return body


class _Pacer:
    def __init__(self, delay_seconds, max_requests, sleep):
        self.delay = float(delay_seconds)
        self.max_requests = int(max_requests)
        self.sleep = sleep or time.sleep
        self.made = 0

    def acquire(self):
        if self.made >= self.max_requests:
            return False
        if self.made:
            high = self.delay if self.delay >= 7 else max(self.delay, min(7.0, self.delay + 4.0))
            self.sleep(random.uniform(self.delay, high))
        self.made += 1
        return True


def _robots_allowed(robots_txt, url):
    prepare_imports()
    from crm_enrich_robots import robots_allowed

    return robots_allowed(robots_txt, url, "*")


def build_fetch(config, direct, *, proxy=None, solver=None, sleep=None):
    """Return fetch(url) with robots, the block ladder, and a spend ledger."""
    ledger = Ledger(config["max_spend_usd"], config["max_proxy_usd"])
    pacer = _Pacer(config["delay_seconds"], config["max_requests"], sleep)
    allow_captcha = bool(config.get("allow_captcha"))
    robots_cache = {}
    body_cache = {}

    def ladder(url):
        result = direct(url) or {}
        result.setdefault("status", 0)
        result.setdefault("text", "")
        result.setdefault("content_type", "")
        result["url"] = url
        result["via"] = "direct"
        if not is_block(result):
            return result
        host = urlparse(url).netloc
        if not ledger.can(PROXY_EVENT):
            log.critical("Blocked on %s with no proxy budget left.", host)
            return _blocked(result, "budget")
        if proxy is None:
            log.critical("Blocked on %s and no proxy hook is configured.", host)
            return _blocked(result, "proxy_unavailable")
        if not pacer.acquire():
            return _cap()
        proxied = proxy(url, token=None) or {}
        if proxied.get("error") == "proxy_unavailable":
            log.critical("Blocked on %s and Apify Proxy credentials are not set.", host)
            return _blocked(result, "proxy_unavailable")
        ledger.commit(PROXY_EVENT)
        log.critical("Proxy retry after a block for %s.", host)
        proxied.setdefault("status", 0)
        proxied.setdefault("text", "")
        proxied.setdefault("content_type", "")
        proxied["url"] = url
        proxied["via"] = "proxy"
        if not is_block(proxied):
            return proxied
        if not is_captcha(proxied):
            return _blocked(proxied, "challenge")
        if not allow_captcha:
            log.critical("CAPTCHA on %s. Solving is off for this run.", host)
            return _blocked(proxied, "captcha_disabled")
        if not ledger.can(CAPTCHA_EVENT):
            log.critical("CAPTCHA on %s. Spend cap would not cover a solve.", host)
            return _blocked(proxied, "budget")
        if solver is None:
            return _blocked(proxied, "captcha_unavailable")
        token = solver(url, proxied.get("text") or "")
        if not token:
            log.critical("CAPTCHA on %s. No solver is configured, so nothing was billed.", host)
            return _blocked(proxied, "captcha_unavailable")
        ledger.commit(CAPTCHA_EVENT)
        log.critical("CAPTCHA solve used for %s.", host)
        if not pacer.acquire():
            return _cap()
        retried = proxy(url, token=token) or {}
        retried.setdefault("status", 0)
        retried.setdefault("text", "")
        retried.setdefault("content_type", "")
        retried["url"] = url
        retried["via"] = "proxy"
        if is_block(retried):
            return _blocked(retried, "challenge")
        return retried

    def fetch(url):
        if url in body_cache:
            return body_cache[url]
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in robots_cache:
            if not pacer.acquire():
                return _cap()
            robots_url = origin + "/robots.txt"
            loaded = ladder(robots_url)
            if loaded.get("error") in ("blocked", "request_cap") or loaded.get("stop"):
                robots_cache[origin] = {"kind": "blocked", "result": loaded}
            elif int(loaded.get("status") or 0) >= 400 and int(loaded.get("status") or 0) != 404:
                robots_cache[origin] = {
                    "kind": "error",
                    "error": loaded.get("error") or f"HTTP {loaded.get('status')} for robots.txt",
                }
            else:
                text = "" if int(loaded.get("status") or 0) == 404 else (loaded.get("text") or "")
                robots_cache[origin] = {"kind": "rules", "text": text}
        decision = robots_cache[origin]
        if decision["kind"] == "blocked":
            return decision["result"]
        if decision["kind"] == "error":
            return {
                "status": 0,
                "text": "",
                "error": decision.get("error") or "robots_fetch_failed",
                "content_type": "",
                "url": url,
            }
        if not _robots_allowed(decision.get("text") or "", url):
            denied = {
                "status": 0,
                "text": "",
                "error": "robots_disallowed",
                "content_type": "",
                "url": url,
            }
            body_cache[url] = denied
            return denied
        if not pacer.acquire():
            return _cap()
        result = ladder(url)
        body_cache[url] = result
        return result

    def website_fetch(url):
        result = fetch(url)
        return _Response(result, url)

    fetch.ledger = ledger
    fetch.website = website_fetch
    return fetch


def _pause(attempt):
    time.sleep(random.uniform(0.4, 1.2) * (attempt + 1))


def http_get(url, proxy_url=None, timeout=45, attempts=3):
    """GET one URL. Retries 429 and 5xx. Does not launch a browser."""
    last_error = None
    handlers = []
    if proxy_url:
        handlers.append(urlrequest.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = urlrequest.build_opener(*handlers)
    for attempt in range(attempts):
        try:
            req = urlrequest.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            })
            with opener.open(req, timeout=timeout) as response:
                status = getattr(response, "status", 200) or 200
                content_type = response.headers.get("Content-Type", "")
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    return {
                        "status": status,
                        "text": "",
                        "error": "response_too_large",
                        "content_type": content_type,
                    }
                text = data.decode("utf-8-sig", "replace")
                if status == 429 or status >= 500:
                    last_error = f"HTTP {status}"
                    if attempt + 1 < attempts:
                        _pause(attempt)
                        continue
                return {"status": status, "text": text, "error": None, "content_type": content_type}
        except urlerror.HTTPError as exc:
            content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
            body = ""
            if exc.fp is not None:
                body = exc.read(8000).decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                last_error = f"HTTP {exc.code}"
                _pause(attempt)
                continue
            return {"status": exc.code, "text": body, "error": None, "content_type": content_type}
        except Exception as exc:
            last_error = str(exc)
            if attempt + 1 < attempts:
                _pause(attempt)
                continue
            return {"status": 0, "text": "", "error": last_error, "content_type": ""}
    return {"status": 0, "text": "", "error": last_error or "fetch_failed", "content_type": ""}


def proxy_url_from_env():
    """Cheapest Apify Proxy group. Empty when the platform password is absent."""
    password = os.environ.get("APIFY_PROXY_PASSWORD") or ""
    if not password:
        return ""
    host = os.environ.get("APIFY_PROXY_HOSTNAME") or "proxy.apify.com"
    port = os.environ.get("APIFY_PROXY_PORT") or "8000"
    session = uuid.uuid4().hex[:12]
    user = quote(f"groups-DATACENTER,session-{session}", safe="")
    secret = quote(password, safe="")
    return f"http://{user}:{secret}@{host}:{port}"


def make_live_fetch(config):
    def direct(url):
        return http_get(url)

    def proxy(url, token=None):
        # token is accepted for the ladder. The default solver never produces
        # one, so a live run does not submit CAPTCHA tokens.
        del token
        proxy_url = proxy_url_from_env()
        if not proxy_url:
            return {"status": 0, "text": "", "error": "proxy_unavailable", "content_type": ""}
        return http_get(url, proxy_url=proxy_url)

    solver = default_solver if config.get("allow_captcha") else None
    return build_fetch(config, direct, proxy=proxy, solver=solver)
