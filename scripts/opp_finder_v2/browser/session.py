"""One Chromium browser per run and a fresh context per site.

No stealth plugins, proxy rotation, or fingerprint spoofing. A storage-state
file is loaded only after the pipeline's login gate has passed.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("opp-finder-v2")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class BrowserSession:
    def __init__(self, *, headless: bool = True, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None

    def start(self) -> None:
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)

    def new_page(self, storage_state: str | None = None):
        self.start()
        if self._context is not None:
            try:
                self._context.close()
            except Exception as exc:  # noqa: BLE001 — replace the context anyway
                logger.debug("Failed closing previous context: %s", exc)
            self._context = None
        kwargs = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 720},
            "locale": "en-US",
        }
        if storage_state:
            kwargs["storage_state"] = storage_state
        self._context = self._browser.new_context(**kwargs)
        page = self._context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return page

    def close(self) -> None:
        for closer, label in (
            (getattr(self._context, "close", None), "context"),
            (getattr(self._browser, "close", None), "browser"),
            (getattr(self._playwright, "stop", None), "playwright"),
        ):
            if closer is None:
                continue
            try:
                closer()
            except Exception as exc:  # noqa: BLE001 — cleanup must not raise
                logger.debug("Failed closing %s: %s", label, exc)
        self._context = None
        self._browser = None
        self._playwright = None
