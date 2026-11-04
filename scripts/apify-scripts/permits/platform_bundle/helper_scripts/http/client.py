"""Session-aware HTTP GET with an optional retry policy.

Callers that do not retry today pass a one-attempt policy, which is the default.
Callers that already retry pass the same attempt count and delay they used before.
"""

from __future__ import annotations

import random
import time
from urllib import error as urlerror
from urllib import request as urlrequest

import requests

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
HTML_JSON_ACCEPT = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"


def html_headers():
    """Browser headers used by lead website fetches."""
    return {
        "User-Agent": CHROME_USER_AGENT,
        "Accept": HTML_ACCEPT,
        "Accept-Language": "en-US,en;q=0.9",
    }


def html_json_headers():
    """Headers used by new-business polite_get and robots fetches."""
    return {
        "User-Agent": CHROME_USER_AGENT,
        "Accept": HTML_JSON_ACCEPT,
    }


class RetryPolicy:
    """How many times to try, and how long to wait after a failed attempt.

    ``delay(attempt, retry_after)`` returns seconds. ``attempt`` is the
    zero-based index of the attempt that just failed. ``retry_after`` is the
    header value or None.
    """

    def __init__(self, attempts=1, delay=None, retry_status=None):
        self.attempts = max(1, int(attempts))
        self._delay = delay or (lambda attempt, retry_after: 0.0)
        if retry_status is None:
            retry_status = lambda status: status == 429 or status >= 500
        self._retry_status = retry_status

    def delay(self, attempt, retry_after=None):
        return float(self._delay(attempt, retry_after) or 0.0)

    def sleep(self, attempt, retry_after=None):
        seconds = self.delay(attempt, retry_after)
        if seconds > 0:
            time.sleep(seconds)

    def retries_status(self, status):
        if isinstance(status, bool) or not isinstance(status, int):
            return False
        return bool(self._retry_status(status))


def polite_delay(attempt, retry_after=None):
    """Exponential pause used between polite_get attempts after the first.

    Retry-After is applied by polite_get itself. Attempt 0 returns 0 because
    the caller sleeps its rate-limit jitter before the first request.
    """
    del retry_after
    if attempt <= 0:
        return 0.0
    return min(30.0, (2 ** (attempt - 1)) + random.uniform(0, 0.5))


def actor_text_delay(attempt, retry_after=None):
    """Jittered backoff used by Apify fetch_text. Retry-After is ignored."""
    del retry_after
    return random.uniform(0.4, 1.2) * (attempt + 1)


def requests_get(
    url,
    *,
    timeout=10,
    headers=None,
    params=None,
    session=None,
    allow_redirects=True,
    policy=None,
    getter=None,
):
    """GET via requests. Default policy is a single attempt.

    ``getter`` lets callers pass ``requests.get`` from their own module so
    existing tests that patch that name still see the call. ``session.get``
    is used when ``session`` is set and ``getter`` is omitted.
    """
    policy = policy or RetryPolicy(attempts=1)
    if getter is None:
        getter = session.get if session is not None else requests.get
    last_error = None
    response = None
    for attempt in range(policy.attempts):
        try:
            kwargs = {"timeout": timeout, "allow_redirects": allow_redirects}
            if headers is not None:
                kwargs["headers"] = headers
            if params is not None:
                kwargs["params"] = params
            response = getter(url, **kwargs)
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 >= policy.attempts:
                raise
            policy.sleep(attempt, None)
            continue
        status = getattr(response, "status_code", 200)
        if policy.retries_status(status) and attempt + 1 < policy.attempts:
            retry_after = None
            response_headers = getattr(response, "headers", None)
            if response_headers is not None:
                retry_after = response_headers.get("Retry-After")
            policy.sleep(attempt, retry_after)
            continue
        return response
    if last_error:
        raise last_error
    return response


def fetch_url_text(url, attempts=3, timeout=20, headers=None, policy=None):
    """GET a text URL with urllib. Same retry rules as the historical fetch_text.

    Retries 429 and 5xx. HTTP 501 and other codes outside
    (429, 500, 502, 503, 504) raise immediately, matching the previous helper.
    """
    if policy is None:
        policy = RetryPolicy(attempts=attempts, delay=actor_text_delay)
    headers = headers or {"User-Agent": CHROME_USER_AGENT}
    last = None
    for attempt in range(policy.attempts):
        try:
            req = urlrequest.Request(url, headers=headers)
            with urlrequest.urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", 200) or 200
                body = response.read().decode("utf-8", "replace")
                if status == 429 or status >= 500:
                    raise RuntimeError(f"HTTP {status} for {url}")
                return body
        except urlerror.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            last = exc
        if attempt + 1 < policy.attempts:
            policy.sleep(attempt, None)
    raise RuntimeError(f"Failed to fetch {url}: {last}")
