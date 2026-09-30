"""Reusable Playwright browser session for opp_finder."""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from utils.constants import BLOCK_MARKERS, FETCH_HEADERS, USER_AGENT

logger = logging.getLogger("opp-finder")


def is_block_page(html: str | None, url: str = "") -> bool:
    haystack = f"{url or ''} {html or ''}".lower()
    return any(marker in haystack for marker in BLOCK_MARKERS)


class BrowserSession:
    """One Chromium instance per run with pacing, retries, and cleanup."""

    def __init__(self, browser_cfg: dict[str, Any] | None = None):
        cfg = browser_cfg or {}
        self.headless = bool(cfg.get("headless", True))
        self.timeout_ms = int(float(cfg.get("timeout_seconds", 30)) * 1000)
        self.retries = int(cfg.get("navigation_retries", 1))
        self.delay_min = float(cfg.get("delay_min_seconds", 2.5))
        self.delay_max = float(cfg.get("delay_max_seconds", 6.0))
        self.screenshot_on_error = bool(cfg.get("screenshot_on_error", False))
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._nav_count = 0
        self.blocked_sources: set[str] = set()

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def start(self) -> None:
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    def close(self) -> None:
        for closer, label in (
            (getattr(self._page, "close", None), "page"),
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
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    @property
    def page(self):
        if self._page is None:
            self.start()
        return self._page

    def _pace(self) -> None:
        if self._nav_count <= 0:
            return
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def mark_blocked(self, source: str, reason: str = "CAPTCHA or block page") -> None:
        self.blocked_sources.add(source)
        logger.warning("[BLOCKED] %s — %s. Skipping source.", source, reason)

    def is_blocked(self, source: str) -> bool:
        return source in self.blocked_sources

    def goto(
        self,
        url: str,
        *,
        source: str = "browser",
        wait_until: str = "domcontentloaded",
    ) -> tuple[str, str]:
        """Navigate and return (final_url, html). Empty html on hard failure."""
        if self.is_blocked(source):
            return "", ""
        self._pace()
        page = self.page
        html = ""
        final_url = url
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                page.goto(url, wait_until=wait_until, timeout=self.timeout_ms)
                final_url = page.url or url
                html = page.content() or ""
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.debug("[%s] Navigation attempt %d failed: %s", source, attempt + 1, exc)
                if attempt < self.retries:
                    time.sleep(1.0)
        self._nav_count += 1
        if last_error is not None and not html:
            logger.error("[%s] Failed to load %s: %s", source, url, last_error)
            if self.screenshot_on_error:
                self._debug_screenshot(source)
            return "", ""
        if is_block_page(html, final_url):
            self.mark_blocked(source)
            return final_url, ""
        return final_url, html

    def google_search(self, query: str, *, num: int = 10) -> tuple[str, str]:
        url = f"https://www.google.com/search?hl=en&num={num}&q={quote_plus(query)}"
        return self.goto(url, source="google")

    def _debug_screenshot(self, source: str) -> None:
        try:
            out = Path(__file__).resolve().parents[1] / "output" / f"debug_{source}_{int(time.time())}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(out))
            logger.debug("Saved debug screenshot to %s", out)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Screenshot failed: %s", exc)
