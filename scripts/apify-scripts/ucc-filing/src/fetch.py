"""Direct HTTP only. No proxy, no CAPTCHA solver, no browser.

robots.txt is read once per host. A 4xx robots answer means no rules. A 5xx
or a network failure skips that host. HTTP 401, 403, and 429 are not retried.
A 5xx on the data URL is retried once. The data URL is streamed and must
already carry a SODA ``$limit``.
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse

try:
    from .runtime import USER_AGENT, prepare_imports
    from .sources import guard_url
except ImportError:
    from runtime import USER_AGENT, prepare_imports
    from sources import guard_url


RETRY_STATUS = (500, 502, 503, 504)
ROBOTS_BYTES = 1_000_000
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


def _headers():
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
    }


def _content_type(response):
    headers = getattr(response, "headers", None) or {}
    if not hasattr(headers, "get"):
        return ""
    return headers.get("Content-Type") or headers.get("content-type") or ""


def _pause(attempt):
    time.sleep(random.uniform(0.4, 1.2) * (attempt + 1))


def _text(client, url):
    last = None
    for attempt in range(2):
        try:
            response = client.get(url, headers=_headers())
        except Exception as exc:
            last = str(exc) or exc.__class__.__name__
            if attempt == 0:
                _pause(attempt)
                continue
            return {"status": 0, "text": "", "error": last, "content_type": "", "chunks": None, "url": url}
        status = response.status_code
        if status in RETRY_STATUS and attempt == 0:
            _pause(attempt)
            continue
        body = response.content or b""
        if len(body) > ROBOTS_BYTES:
            body = body[:ROBOTS_BYTES]
        return {
            "status": status,
            "text": body.decode("utf-8-sig", "replace"),
            "error": None,
            "content_type": _content_type(response),
            "chunks": None,
            "url": url,
        }
    return {"status": 0, "text": "", "error": last or "fetch_failed", "content_type": "", "chunks": None, "url": url}


def _stream(client, url):
    """Open a streamed GET. The body is not read until the caller iterates ``chunks``."""
    last = None
    for attempt in range(2):
        cm = client.stream("GET", url, headers=_headers())
        try:
            response = cm.__enter__()
        except Exception as exc:
            last = str(exc) or exc.__class__.__name__
            if attempt == 0:
                _pause(attempt)
                continue
            return {"status": 0, "text": "", "error": last, "content_type": "", "chunks": None, "url": url}
        status = response.status_code
        if status in RETRY_STATUS and attempt == 0:
            cm.__exit__(None, None, None)
            _pause(attempt)
            continue
        if status != 200:
            body = b""
            try:
                body = response.read(4096)
            except Exception:
                body = b""
            cm.__exit__(None, None, None)
            return {
                "status": status,
                "text": body.decode("utf-8-sig", "replace"),
                "error": None,
                "content_type": _content_type(response),
                "chunks": None,
                "url": url,
            }

        def chunks(bound_cm=cm, bound_response=response):
            try:
                for chunk in bound_response.iter_bytes(chunk_size=32768):
                    yield chunk
            finally:
                bound_cm.__exit__(None, None, None)

        return {
            "status": 200,
            "text": "",
            "error": None,
            "content_type": _content_type(response),
            "chunks": chunks(),
            "url": url,
        }
    return {"status": 0, "text": "", "error": last or "fetch_failed", "content_type": "", "chunks": None, "url": url}


def build_fetch(config, direct, sleep=None):
    """Robots and pacing around ``direct(request)``. Stream bodies are not read here."""
    pacer = _Pacer(config["delay_seconds"], sleep)
    cache = {}

    def fetch(request):
        url = request["url"]
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in cache:
            pacer.wait()
            robots_url = origin + "/robots.txt"
            loaded = direct({"method": "GET", "url": robots_url, "stream": False}) or {}
            status = int(loaded.get("status") or 0)
            if 200 <= status < 300:
                cache[origin] = {"kind": "rules", "text": loaded.get("text") or ""}
            elif 400 <= status < 500:
                cache[origin] = {"kind": "rules", "text": ""}
            else:
                cache[origin] = {
                    "kind": "error",
                    "error": loaded.get("error") or f"robots.txt answered HTTP {status}",
                }
        decision = cache[origin]
        if decision["kind"] == "error":
            return {
                "status": 0,
                "error": "robots_unavailable",
                "detail": decision["error"],
                "text": "",
                "chunks": None,
                "url": url,
            }
        if not _robots_allowed(decision.get("text") or "", url):
            return {
                "status": 0,
                "error": "robots_disallowed",
                "text": "",
                "chunks": None,
                "url": url,
            }
        if request.get("stream"):
            blocked = guard_url(url)
            if blocked:
                return {"status": 0, "error": blocked, "text": "", "chunks": None, "url": url}
        pacer.wait()
        return direct(request) or {"status": 0, "error": "fetch_failed", "text": "", "chunks": None, "url": url}

    fetch.pacer = pacer
    return fetch


def make_live_fetch(config):
    """httpx client. Caller closes it with ``fetch.close()``."""
    import httpx

    client = httpx.Client(follow_redirects=True, timeout=60.0)

    def direct(request):
        if request.get("stream"):
            return _stream(client, request["url"])
        return _text(client, request["url"])

    fetch = build_fetch(config, direct)
    fetch.close = client.close
    return fetch
