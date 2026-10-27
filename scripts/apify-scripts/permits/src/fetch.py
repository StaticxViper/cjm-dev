"""Direct HTTP first. Proxy only after a block. CAPTCHA only if that still fails.

robots.txt is evaluated with the longest-match helper before a host is
fetched. A disallow is not retried through a proxy. Spend is reserved only
when a proxy request is sent or a solver returns a token.
"""

from __future__ import annotations

import logging
import random
import time
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

try:
    from .runtime import (
        USER_AGENT,
        AccessPolicy,
        escalate,
        is_block,
        prepare_imports,
        proxy_url_from_env,
    )
    from .spend import PRICES_USD
except ImportError:
    from runtime import (
        USER_AGENT,
        AccessPolicy,
        escalate,
        is_block,
        prepare_imports,
        proxy_url_from_env,
    )
    from spend import PRICES_USD


MAX_BYTES = 8 * 1024 * 1024
log = logging.getLogger("apify")


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
            high = self.delay if self.delay >= 5 else max(self.delay, min(5.0, self.delay + 2.0))
            self.sleep(random.uniform(self.delay, high))
        self.made += 1
        return True


def _robots_allowed(robots_txt, url):
    prepare_imports()
    from crm_enrich_robots import robots_allowed

    return robots_allowed(robots_txt, url, "*")


def _cap():
    return {"status": 0, "text": "", "error": "request_cap", "content_type": "", "url": ""}


def _normalize(result, url):
    body = dict(result or {})
    body.setdefault("status", 0)
    body.setdefault("text", "")
    body.setdefault("content_type", "")
    body.setdefault("error", None)
    body["url"] = body.get("url") or url
    return body


def build_fetch(config, direct, *, proxy=None, solver=None, sleep=None):
    """Return fetch(url) with robots, the block ladder, and a spend ledger."""
    settings = {
        "max_spend_usd": config["max_spend_usd"],
        "max_proxy_usd": config["max_proxy_usd"],
        "allow_captcha": bool(config.get("allow_captcha")),
        "proxy_groups": list(config.get("proxy_groups") or []),
        "proxy_configuration": config.get("proxy_configuration") or {},
        "prices_usd": dict(PRICES_USD),
    }
    policy = AccessPolicy(settings, solver=solver if settings["allow_captcha"] else None)
    pacer = _Pacer(config["delay_seconds"], config["max_requests"], sleep)
    robots_cache = {}
    body_cache = {}

    def later_proxy(target, token=None):
        if token and not pacer.acquire():
            return {
                "status": 0,
                "text": "",
                "error": "request_cap",
                "content_type": "",
                "url": target,
            }
        return proxy(target, token=token) or {}

    def ladder(url):
        result = _normalize(direct(url), url)
        result["via"] = "direct"
        if not is_block(result):
            return result
        decision = policy.on_direct(result)
        if decision.action != "proxy":
            result["error"] = "blocked"
            result["stop"] = decision.stop or "challenge"
            return result
        if proxy is None:
            final, _stop = escalate(policy, url, result, None)
            return final
        if not pacer.acquire():
            return _cap()
        final, _stop = escalate(policy, url, result, later_proxy)
        return final

    def fetch(url):
        if url in body_cache:
            return body_cache[url]
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in robots_cache:
            if not pacer.acquire():
                return _cap()
            loaded = ladder(origin + "/robots.txt")
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

    fetch.ledger = policy.ledger
    fetch.settings = settings
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


def default_solver(url, html):
    """No paid solver ships with this Actor. None means the run stops unpaid."""
    del url, html
    return None


def make_live_fetch(config, proxy_url_fn=None):
    def direct(url):
        return http_get(url)

    def proxy(url, token=None):
        # token is accepted for the ladder. The default solver never produces
        # one, so a live run does not submit CAPTCHA tokens.
        del token
        if proxy_url_fn is None:
            proxy_url = proxy_url_from_env(config.get("proxy_groups"))
        else:
            proxy_url = proxy_url_fn() or ""
        if not proxy_url:
            return {"status": 0, "text": "", "error": "proxy_unavailable", "content_type": ""}
        return http_get(url, proxy_url=proxy_url)

    solver = default_solver if config.get("allow_captcha") else None
    return build_fetch(config, direct, proxy=proxy, solver=solver)
