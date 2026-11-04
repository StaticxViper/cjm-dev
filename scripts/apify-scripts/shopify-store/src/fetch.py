"""Direct HTTP only. No proxy, no CAPTCHA solver, no browser.

robots.txt is read once per host and evaluated with the longest-match helper.
Per RFC 9309 a 4xx robots answer means no rules, including 403 and 429. A 5xx
or network failure skips that host. A 401, 403, or 429 on the catalog URL
itself is not retried. 5xx is retried once.
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse

try:
    from .runtime import USER_AGENT, is_block, prepare_imports
except ImportError:
    from runtime import USER_AGENT, is_block, prepare_imports


MAX_BYTES = 8 * 1024 * 1024
RETRY_STATUS = (500, 502, 503, 504)
log = logging.getLogger("apify")


class _Pacer:
    def __init__(self, delay_seconds, sleep):
        self.delay = float(delay_seconds)
        self.sleep = sleep or time.sleep
        self.made = 0

    def wait(self):
        if self.made:
            self.sleep(random.uniform(self.delay, self.delay + 1.0))
        self.made += 1


def _robots_allowed(robots_txt, url):
    prepare_imports()
    from crm_enrich_robots import robots_allowed

    return robots_allowed(robots_txt, url, "*")


def _normalize(result, url):
    body = dict(result or {})
    body.setdefault("status", 0)
    body.setdefault("text", "")
    body.setdefault("content_type", "")
    body.setdefault("error", None)
    body["url"] = body.get("url") or url
    return body


def build_fetch(config, direct, *, sleep=None):
    """Return fetch(url) with robots and pacing around ``direct(url)``."""
    pacer = _Pacer(config["delay_seconds"], sleep)
    robots_cache = {}

    def fetch(url):
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in robots_cache:
            pacer.wait()
            loaded = _normalize(direct(origin + "/robots.txt"), origin + "/robots.txt")
            status = int(loaded.get("status") or 0)
            if is_block(loaded) and status not in (401, 403, 429):
                robots_cache[origin] = {"kind": "blocked", "result": loaded}
            elif 200 <= status < 300:
                robots_cache[origin] = {"kind": "rules", "text": loaded.get("text") or ""}
            elif 400 <= status < 500:
                robots_cache[origin] = {"kind": "rules", "text": ""}
            else:
                robots_cache[origin] = {
                    "kind": "error",
                    "error": loaded.get("error") or f"robots.txt answered HTTP {status}",
                }
        decision = robots_cache[origin]
        if decision["kind"] == "blocked":
            body = dict(decision["result"])
            body["url"] = url
            return _normalize(body, url)
        if decision["kind"] == "error":
            return _normalize({"error": "robots_unavailable", "detail": decision["error"]}, url)
        if not _robots_allowed(decision.get("text") or "", url):
            return _normalize({"error": "robots_disallowed"}, url)
        pacer.wait()
        return _normalize(direct(url), url)

    fetch.pacer = pacer
    return fetch


def _pause(attempt, retry_after=None):
    if retry_after:
        try:
            time.sleep(min(30.0, float(retry_after)))
            return
        except (TypeError, ValueError):
            pass
    time.sleep(random.uniform(0.4, 1.2) * (attempt + 1))


def http_get(url, timeout=30, attempts=2, client=None, sleep=None):
    """GET one URL. Retries 5xx once. Does not retry 401, 403, or 429."""
    owned = client is None
    if owned:
        import httpx

        client = httpx.Client(follow_redirects=True, timeout=timeout)
    pause = sleep or _pause
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }
    last_error = None
    try:
        for attempt in range(attempts):
            try:
                response = client.get(url, headers=headers)
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
                if attempt + 1 < attempts:
                    pause(attempt)
                    continue
                return {"status": 0, "text": "", "error": last_error, "content_type": "", "url": url}
            status = response.status_code
            content_type = response.headers.get("Content-Type", "")
            if status in RETRY_STATUS and attempt + 1 < attempts:
                pause(attempt, response.headers.get("Retry-After"))
                continue
            data = response.content
            if len(data) > MAX_BYTES:
                return {
                    "status": status,
                    "text": "",
                    "error": "response_too_large",
                    "content_type": content_type,
                    "url": url,
                }
            return {
                "status": status,
                "text": data.decode("utf-8-sig", "replace"),
                "error": None,
                "content_type": content_type,
                "url": url,
            }
    finally:
        if owned:
            client.close()
    return {"status": 0, "text": "", "error": last_error or "fetch_failed", "content_type": "", "url": url}


def make_live_fetch(config):
    import httpx

    client = httpx.Client(follow_redirects=True, timeout=30)

    def direct(url):
        return http_get(url, client=client)

    fetch = build_fetch(config, direct)
    fetch.close = client.close
    return fetch
