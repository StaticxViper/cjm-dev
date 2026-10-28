"""Close and pacing helpers shared by the Google Playwright sessions.

Launch flags stay on each session. Maps discovery and email search do not use
the same browser arguments or viewport, so this module does not launch Chromium.
"""

from __future__ import annotations

import random
import time


def is_google_block_page(html, url=""):
    """Return True only for clear Google sorry/traffic interstitial pages.

    Maps pages include a noscript "enable javascript" fallback; that alone is
    not treated as a block. Email search uses its own marker list on top of this.
    """
    current = (url or "").lower()
    if "/sorry/" in current or "google.com/sorry" in current:
        return True
    haystack = f"{current} {html or ''}".lower()
    if "unusual traffic" in haystack or "detected unusual traffic" in haystack:
        return True
    if "our systems have detected" in haystack and "automated" in haystack:
        return True
    return False


def close_playwright_handles(handles, on_error):
    """Call close/stop on ``(obj, label, method)`` triples. Errors are logged, not raised."""
    for obj, label, method in handles:
        closer = getattr(obj, method, None) if obj is not None else None
        if closer is None:
            continue
        try:
            closer()
        except Exception as exc:
            on_error(label, exc)


def sleep_between(done_count, fixed_delay, min_delay, max_delay):
    """Skip the first call. A fixed delay wins over the random range."""
    if done_count <= 0:
        return
    if fixed_delay is not None:
        time.sleep(fixed_delay)
        return
    time.sleep(random.uniform(min_delay, max_delay))


class GoogleBrowserCore:
    """Browser handle fields plus close. Subclasses launch the page themselves."""

    def __init__(self):
        self.google_blocked = False
        self._playwright = None
        self._browser = None
        self._page = None

    def close_browser(self, on_error):
        page, browser, playwright = self._page, self._browser, self._playwright
        self._page = None
        self._browser = None
        self._playwright = None
        close_playwright_handles(
            (
                (page, "page", "close"),
                (browser, "browser", "close"),
                (playwright, "playwright", "stop"),
            ),
            on_error,
        )
