"""HTTP fetch with a request cap. A challenge response is returned as-is.

Playwright is not launched. A Cloudflare or Turnstile body is not retried
through a browser.
"""

from __future__ import annotations

import random
import time
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

try:
    from .adapters.base import is_challenge
    from .politeness import Pacer
    from .runtime import USER_AGENT, prepare_imports
except ImportError:
    from adapters.base import is_challenge
    from politeness import Pacer
    from runtime import USER_AGENT, prepare_imports


MAX_BYTES = 80 * 1024 * 1024


def _cap():
    return {"status": 0, "text": "", "error": "request_cap", "content_type": ""}


def _pause(attempt):
    time.sleep(random.uniform(0.4, 1.2) * (attempt + 1))


def http_get(url, timeout=120, attempts=3):
    """GET one URL. Retries 429 and 5xx. Does not follow a challenge with a browser."""
    last_error = None
    for attempt in range(attempts):
        try:
            req = urlrequest.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/csv,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            })
            with urlrequest.urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", 200) or 200
                content_type = response.headers.get("Content-Type", "")
                length = response.headers.get("Content-Length")
                if length and str(length).isdigit() and int(length) > MAX_BYTES:
                    return {
                        "status": status,
                        "text": "",
                        "error": "response_too_large",
                        "content_type": content_type,
                    }
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
                    return {
                        "status": status,
                        "text": text,
                        "error": last_error,
                        "content_type": content_type,
                    }
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


def _robots_allowed(robots_txt, url):
    prepare_imports()
    from crm_enrich_robots import robots_allowed

    return robots_allowed(robots_txt, url, "*")


def _read_robots(origin):
    result = http_get(origin + "/robots.txt", timeout=30, attempts=2)
    text = result.get("text") or ""
    if is_challenge(text, result.get("content_type") or ""):
        return {"kind": "captcha", "text": text}
    status = result.get("status") or 0
    if status == 404:
        return {"kind": "rules", "text": ""}
    if result.get("error"):
        return {"kind": "error", "error": result["error"]}
    if status >= 400:
        return {"kind": "error", "error": f"HTTP {status} for robots.txt"}
    return {"kind": "rules", "text": text}


def make_fetch(delay_seconds=2.0, max_requests=4, sleep=None):
    """Return fetch(url) paced like opp_finder_v2, with a robots check per host."""
    pacer = Pacer(
        min_s=delay_seconds,
        max_s=delay_seconds + 1.5,
        max_requests=max_requests,
        sleep=sleep,
    )
    robots_cache = {}

    def fetch(url):
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in robots_cache:
            if not pacer.acquire():
                return _cap()
            robots_cache[origin] = _read_robots(origin)
        decision = robots_cache[origin]
        if decision["kind"] == "captcha":
            return {
                "status": 403,
                "text": decision.get("text") or "",
                "error": "captcha",
                "content_type": "text/html",
            }
        if decision["kind"] == "error":
            return {
                "status": 0,
                "text": "",
                "error": decision.get("error") or "robots_fetch_failed",
                "content_type": "",
            }
        if not _robots_allowed(decision.get("text") or "", url):
            return {"status": 0, "text": "", "error": "robots_disallowed", "content_type": ""}
        if not pacer.acquire():
            return _cap()
        return http_get(url)

    return fetch
