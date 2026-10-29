"""HTTP fetch with a request cap. A challenge response is returned as-is.

Playwright is not launched. A Cloudflare or Turnstile body is not retried
through a browser.
"""

from __future__ import annotations

import http.cookiejar
import random
import time
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urljoin, urlparse

try:
    from .adapters.base import is_challenge
    from .politeness import Pacer
    from .runtime import USER_AGENT, prepare_imports
except ImportError:
    from adapters.base import is_challenge
    from politeness import Pacer
    from runtime import USER_AGENT, prepare_imports


MAX_BYTES = 80 * 1024 * 1024
HTML_MAX_BYTES = 2 * 1024 * 1024
_REDIRECTS = {301, 302, 303, 307, 308}


def _cap():
    return {"status": 0, "text": "", "error": "request_cap", "content_type": "", "final_url": ""}


def _pause(attempt):
    time.sleep(random.uniform(0.4, 1.2) * (attempt + 1))


class _StopRedirect(urlrequest.HTTPRedirectHandler):
    """Leave 3xx to the caller so Set-Cookie is stored before the next hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener(jar):
    return urlrequest.build_opener(
        urlrequest.HTTPCookieProcessor(jar),
        _StopRedirect(),
    )


def _byte_limit(content_type, posted):
    if posted or (content_type and "html" in content_type.lower()):
        return HTML_MAX_BYTES
    return MAX_BYTES


def _read_capped(response, limit):
    length = response.headers.get("Content-Length") if response.headers else None
    if length and str(length).isdigit() and int(length) > limit:
        return None
    data = response.read(limit + 1)
    if len(data) > limit:
        return None
    return data


def http_exchange(url, data=None, timeout=120, attempts=3, opener=None, jar=None):
    """GET or POST one URL, following a few redirects on the same cookie jar.

    Retries 429 and 5xx. Does not launch a browser. HTML bodies are capped
    at 2 MB so a license page cannot be treated like a statewide file.
    """
    own_jar = jar or http.cookiejar.CookieJar()
    client = opener or _opener(own_jar)
    last_error = None
    posted = data is not None
    current = url
    payload = data
    parsed_start = urlparse(url)
    referer = f"{parsed_start.scheme}://{parsed_start.netloc}/" if parsed_start.netloc else url
    for attempt in range(attempts):
        hops = 0
        while hops < 5:
            try:
                parsed = urlparse(current)
                origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else url
                headers = {
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,text/csv;q=0.8,*/*;q=0.7",
                    "Accept-Language": "en-US,en;q=0.9",
                    # The CSLB detail page returns "Request Rejected" unless the
                    # navigation carries a same-site referer.
                    "Referer": url if payload is not None else referer,
                }
                req_data = payload
                if req_data is not None:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    headers["Origin"] = origin
                req = urlrequest.Request(current, data=req_data, headers=headers)
                try:
                    response = client.open(req, timeout=timeout)
                except urlerror.HTTPError as exc:
                    own_jar.extract_cookies(exc, req)
                    if exc.code in _REDIRECTS and hops < 4:
                        location = exc.headers.get("Location") if exc.headers else None
                        if not location:
                            return {
                                "status": exc.code,
                                "text": "",
                                "error": "redirect_without_location",
                                "content_type": "",
                                "final_url": current,
                            }
                        if exc.code in (301, 302, 303):
                            payload = None
                        referer = current
                        current = urljoin(current, location)
                        hops += 1
                        continue
                    content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
                    body = ""
                    if exc.fp is not None and exc.code not in _REDIRECTS:
                        limit = _byte_limit(content_type, posted)
                        raw = exc.read(min(limit, 8000) + 1)
                        body = raw[:8000].decode("utf-8", "replace")
                    if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                        last_error = f"HTTP {exc.code}"
                        _pause(attempt)
                        break
                    return {
                        "status": exc.code,
                        "text": body,
                        "error": None,
                        "content_type": content_type,
                        "final_url": current,
                    }
                status = getattr(response, "status", 200) or 200
                content_type = response.headers.get("Content-Type", "")
                limit = _byte_limit(content_type, posted)
                raw = _read_capped(response, limit)
                response.close()
                if raw is None:
                    return {
                        "status": status,
                        "text": "",
                        "error": "response_too_large",
                        "content_type": content_type,
                        "final_url": current,
                    }
                text = raw.decode("utf-8-sig", "replace")
                if status == 429 or status >= 500:
                    last_error = f"HTTP {status}"
                    if attempt + 1 < attempts:
                        _pause(attempt)
                        break
                    return {
                        "status": status,
                        "text": text,
                        "error": last_error,
                        "content_type": content_type,
                        "final_url": current,
                    }
                return {
                    "status": status,
                    "text": text,
                    "error": None,
                    "content_type": content_type,
                    "final_url": current,
                }
            except Exception as exc:
                last_error = str(exc)
                if attempt + 1 < attempts:
                    _pause(attempt)
                    break
                return {
                    "status": 0,
                    "text": "",
                    "error": last_error,
                    "content_type": "",
                    "final_url": current,
                }
        else:
            continue
        continue
    return {
        "status": 0,
        "text": "",
        "error": last_error or "fetch_failed",
        "content_type": "",
        "final_url": url,
    }


def http_get(url, timeout=120, attempts=3, opener=None, jar=None):
    """GET one URL. Retries 429 and 5xx. Does not follow a challenge with a browser."""
    return http_exchange(url, timeout=timeout, attempts=attempts, opener=opener, jar=jar)


def open_stream(url, timeout=120, max_bytes=MAX_BYTES):
    """Open a download and return (response, error). Does not read the body."""
    req = urlrequest.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/csv,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    })
    try:
        response = urlrequest.urlopen(req, timeout=timeout)
    except Exception as exc:
        return None, str(exc)
    length = response.headers.get("Content-Length") if response.headers else None
    if length and str(length).isdigit() and int(length) > max_bytes:
        response.close()
        return None, "response_too_large"
    return response, None


def iter_response_lines(response, max_bytes=MAX_BYTES):
    """Yield decoded lines from an open response. Closing the generator closes it."""
    total = 0
    pending = b""
    try:
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError("response_too_large")
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                yield line.decode("utf-8-sig", "replace")
        if pending:
            yield pending.decode("utf-8-sig", "replace")
    finally:
        response.close()


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
    jar = http.cookiejar.CookieJar()
    client = _opener(jar)

    def _guard(url):
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
                "final_url": url,
            }
        if decision["kind"] == "error":
            return {
                "status": 0,
                "text": "",
                "error": decision.get("error") or "robots_fetch_failed",
                "content_type": "",
                "final_url": url,
            }
        if not _robots_allowed(decision.get("text") or "", url):
            return {
                "status": 0,
                "text": "",
                "error": "robots_disallowed",
                "content_type": "",
                "final_url": url,
            }
        if not pacer.acquire():
            return _cap()
        return None

    def fetch(url, data=None):
        failed = _guard(url)
        if failed is not None:
            return failed
        return http_exchange(url, data=data, opener=client, jar=jar)

    def stream_lines(url):
        """Line iterator for a large file, or an error dict when the fetch cannot start."""
        failed = _guard(url)
        if failed is not None:
            return failed
        response, error = open_stream(url)
        if error:
            return {
                "status": 0,
                "text": "",
                "error": error,
                "content_type": "",
                "final_url": url,
            }
        return iter_response_lines(response)

    fetch.stream_lines = stream_lines
    return fetch
