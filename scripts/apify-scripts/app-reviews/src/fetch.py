"""Direct HTTP only. No proxy, no CAPTCHA solver, no browser.

robots.txt is read once per host and evaluated with the longest-match helper.
Per RFC 9309 a 4xx robots answer means no rules; a 5xx or network failure
means the host is skipped for this run. HTTP 401, 403, and 429 are not
retried. A 5xx or a network error is retried once.
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse

try:
    from .runtime import USER_AGENT, prepare_imports
except ImportError:
    from runtime import USER_AGENT, prepare_imports


MAX_BYTES = 32 * 1024 * 1024
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
            if 200 <= status < 300:
                robots_cache[origin] = {"kind": "rules", "text": loaded.get("text") or ""}
            elif 400 <= status < 500:
                robots_cache[origin] = {"kind": "rules", "text": ""}
            else:
                robots_cache[origin] = {
                    "kind": "error",
                    "error": loaded.get("error") or f"robots.txt answered HTTP {status}",
                }
        decision = robots_cache[origin]
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
            time.sleep(min(2.0, float(retry_after)))
            return
        except (TypeError, ValueError):
            pass
    time.sleep(random.uniform(0.4, 1.2) * (attempt + 1))


def _content_type(response):
    headers = getattr(response, "headers", None) or {}
    if not hasattr(headers, "get"):
        return ""
    return headers.get("Content-Type") or headers.get("content-type") or ""


def http_get(url, timeout=30, attempts=2, client=None):
    """GET one URL. 5xx and network errors are retried once. 401, 403, and 429 are not."""
    owned = client is None
    if owned:
        import httpx

        client = httpx.Client(follow_redirects=True, timeout=timeout)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
    }
    last_error = None
    try:
        for attempt in range(attempts):
            try:
                response = client.get(url, headers=headers)
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
                if attempt + 1 < attempts:
                    _pause(attempt)
                    continue
                return {"status": 0, "text": "", "error": last_error, "content_type": "", "url": url}
            status = response.status_code
            content_type = _content_type(response)
            if status in RETRY_STATUS and attempt + 1 < attempts:
                retry_after = None
                response_headers = getattr(response, "headers", None) or {}
                if hasattr(response_headers, "get"):
                    retry_after = response_headers.get("Retry-After")
                _pause(attempt, retry_after)
                continue
            data = response.content or b""
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
