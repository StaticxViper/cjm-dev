"""HTTP fetch for Zillow search and listing pages.

A headless browser is fingerprinted by PerimeterX even when the exit IP is
residential, and a plain Python client is fingerprinted by its TLS handshake.
The search result HTML already contains the listing JSON, so the platform path
requests that document with a Chrome impersonation session through Apify Proxy.
One spare residential session is used for a single retry after a block. Later
requests stay on that second session and do not keep rotating.
"""

from __future__ import annotations

import logging
import random
import re
import time
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

log = logging.getLogger("apify")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_MAX_BYTES = 4 * 1024 * 1024
_SECRET_RE = re.compile(r"//[^/\s@]+@")
_SOFT_BLOCK = (
    "px-captcha",
    "captcha-delivery",
    "access to this page has been denied",
    "request rejected",
    "perimeterx",
)


def _public_error(exc):
    return _SECRET_RE.sub("//", str(exc))[:300]


def _headers(url):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-CH-UA": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
    }
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("zillow.com"):
        headers["Referer"] = "https://www.zillow.com/"
        headers["Sec-Fetch-Site"] = "same-origin"
    else:
        headers["Sec-Fetch-Site"] = "none"
    return headers


def _has_listing_payload(html):
    text = html or ""
    if "__NEXT_DATA__" in text:
        return True
    lowered = text.lower()
    if "homedetails" in lowered and "_zpid" in lowered:
        return True
    return '"zpid"' in lowered


def _blocked(is_blocked_page, url, html, status):
    if is_blocked_page(url, html, status):
        return True
    if status in (403, 429, 503):
        return True
    if _has_listing_payload(html):
        return False
    if _is_zillow(url):
        return True
    lowered = (html or "").lower()
    return any(bit in lowered for bit in _SOFT_BLOCK)


def _read(response):
    data = response.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        data = data[:_MAX_BYTES]
    return data.decode("utf-8", "replace")


def _result(url, html, status, final, error=""):
    import zillow_agents

    if error and not html:
        return zillow_agents.FetchResult(url=url, error=error)
    blocked = _blocked(zillow_agents.is_blocked_page, final or url, html, status)
    return zillow_agents.FetchResult(
        url=url,
        html="" if blocked else html,
        status=status,
        final_url=final or url,
        blocked=blocked,
        error=error,
    )


def urllib_transport(url, proxy_url, timeout=45):
    """One GET through a proxy URL. The proxy credential is not included in errors."""
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
    handlers = [urlrequest.ProxyHandler(proxies)] if proxies else []
    opener = urlrequest.build_opener(*handlers)
    request = urlrequest.Request(url, headers=_headers(url))
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200) or 200
            html = _read(response)
            final = response.geturl() or url
    except urlerror.HTTPError as exc:
        status = exc.code
        raw = exc.read(_MAX_BYTES) if exc.fp is not None else b""
        html = raw.decode("utf-8", "replace")
        final = url
    except Exception as exc:
        return _result(url, "", 0, url, _public_error(exc))
    return _result(url, html, status, final or url)


class ChromeTransport:
    """One Chrome-impersonation cookie session per proxy URL.

    The first Zillow request on a session loads the homepage so the search
    request carries that cookie. A block still belongs to the caller, which
    retries once on the spare proxy URL.
    """

    def __init__(self, timeout=45):
        self.timeout = timeout
        self._sessions = {}
        self._warmed = set()
        self._fallback = None

    def _session(self, proxy_url):
        session = self._sessions.get(proxy_url)
        if session is not None:
            return session
        from curl_cffi import requests as curl_requests

        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        session = curl_requests.Session(impersonate="chrome", proxies=proxies)
        self._sessions[proxy_url] = session
        return session

    def _get(self, session, url):
        response = session.get(url, timeout=self.timeout, allow_redirects=True)
        html = response.text or ""
        if len(html) > _MAX_BYTES:
            html = html[:_MAX_BYTES]
        final = str(response.url or url)
        return _result(url, html, int(response.status_code or 0), final)

    def __call__(self, url, proxy_url):
        try:
            session = self._session(proxy_url)
        except Exception as exc:
            log.info("Chrome impersonation is unavailable (%s). Using the Python client.", type(exc).__name__)
            if self._fallback is None:
                self._fallback = urllib_transport
            return self._fallback(url, proxy_url, timeout=self.timeout)
        try:
            if proxy_url not in self._warmed and _is_zillow(url) and not url.rstrip("/").endswith("zillow.com"):
                self._warmed.add(proxy_url)
                try:
                    session.get("https://www.zillow.com/", timeout=self.timeout, allow_redirects=True)
                except Exception as exc:
                    log.info("Zillow homepage warmup failed: %s", _public_error(exc))
            return self._get(session, url)
        except Exception as exc:
            return _result(url, "", 0, url, _public_error(exc))


def make_proxy_fetch(proxy_urls, transport=None, sleep=None):
    """Fetch with the first proxy URL, then one retry on the spare URL.

    ``proxy_urls`` is one or two Apify proxy URLs. The second is used only
    after a block or a transport failure, and only once for the run.
    """
    import zillow_agents

    urls = [item for item in (proxy_urls or []) if item]
    if not urls:
        raise RuntimeError("Apify Proxy is required for Zillow requests on the platform.")
    send = transport or ChromeTransport()
    pause = sleep or time.sleep
    state = {"index": 0, "gave_up": False, "requests": 0, "rotations": 0, "paused": False}

    def fetch(url):
        if state["gave_up"] and _is_zillow(url):
            return zillow_agents.FetchResult(url=url, blocked=True, error="already_blocked")
        if state["paused"]:
            pause(random.uniform(1.5, 2.5))
        state["paused"] = True
        result = send(url, urls[state["index"]])
        state["requests"] += 1
        if _should_retry(result) and state["rotations"] < 1 and state["index"] + 1 < len(urls):
            state["index"] += 1
            state["rotations"] += 1
            log.info("Zillow blocked the first residential session. Retrying once on a new session.")
            result = send(url, urls[state["index"]])
            state["requests"] += 1
        if result.blocked:
            state["gave_up"] = True
        return result

    fetch.request_count = lambda: state["requests"]
    fetch.rotation_count = lambda: state["rotations"]
    return fetch


def _is_zillow(url):
    host = (urlparse(url or "").hostname or "").lower()
    return host == "zillow.com" or host.endswith(".zillow.com")


def _should_retry(result):
    if result.blocked:
        return True
    if result.error and not result.html:
        return True
    return False
