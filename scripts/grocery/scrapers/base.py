"""Shared Playwright session, delay, and block detection.

One Chromium profile, a normal desktop user agent, and a delay between pages.
No stealth plugins, proxy rotation, or CAPTCHA solving.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from grocery.models import ProductRecord
from grocery.scrapers.extract import visible_text
from helper_scripts.browser.backoff import backoff_seconds

logger = logging.getLogger("grocery")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
_BLOCK_PHRASES = (
    "sorry, we just need to make sure you're not a robot",
    "enter the characters you see below",
    "verify you are human",
    "verify you are a human",
    "type the characters you see in this image",
    "robot check",
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass
class PageFetch:
    html: str
    url: str
    status: int | None
    error: str | None = None


def is_retryable_status(status: int | None) -> bool:
    return status in RETRYABLE_STATUS


def classify_block(html: str, url: str = "") -> str | None:
    """Return 'blocked' when the page is a robot check. Ordinary product HTML is kept."""
    current = (url or "").lower()
    if "/errors/validatecaptcha" in current or "/sorry/" in current:
        return "blocked"
    title_match = _TITLE.search(html or "")
    title = (title_match.group(1) if title_match else "").strip().lower()
    if "robot check" in title or "captcha" in title:
        return "blocked"
    text = visible_text(html).lower()
    if any(phrase in text for phrase in _BLOCK_PHRASES):
        return "blocked"
    return None


class BrowserSession:
    """One browser and one context for a run so store cookies survive page changes."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 30000,
        min_delay_s: float = 2.0,
        storage_state: str | None = None,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.min_delay_s = min_delay_s
        self.storage_state = storage_state
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._last_fetch: float | None = None

    def __enter__(self) -> BrowserSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)

    def page(self):
        if self._page is not None:
            return self._page
        self.start()
        kwargs = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 720},
            "locale": "en-US",
        }
        if self.storage_state and Path(self.storage_state).is_file():
            kwargs["storage_state"] = self.storage_state
        self._context = self._browser.new_context(**kwargs)
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self._page

    def save_storage(self, path: Path) -> None:
        if self._context is None:
            raise RuntimeError("browser context is not open")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(path))

    def _pause_between_pages(self) -> None:
        if self._last_fetch is None:
            self._last_fetch = time.monotonic()
            return
        remaining = self.min_delay_s - (time.monotonic() - self._last_fetch)
        if remaining > 0:
            time.sleep(remaining)
        self._last_fetch = time.monotonic()

    def fetch(self, url: str) -> PageFetch:
        last_error = "fetch_failed"
        for attempt in range(MAX_ATTEMPTS):
            self._pause_between_pages()
            try:
                page = self.page()
                response = page.goto(url, wait_until="domcontentloaded")
                status = response.status if response is not None else None
                html = page.content()
                final_url = page.url
            except Exception as exc:  # noqa: BLE001 — retry, then record the failure
                last_error = f"fetch_failed: {exc}"
                logger.info("fetch failed for %s: %s", url, exc)
                if attempt + 1 < MAX_ATTEMPTS:
                    time.sleep(backoff_seconds(attempt, self.min_delay_s))
                continue
            if is_retryable_status(status) and attempt + 1 < MAX_ATTEMPTS:
                time.sleep(backoff_seconds(attempt, self.min_delay_s))
                continue
            if status is not None and status >= 400:
                return PageFetch(html=html, url=final_url, status=status, error=f"http_{status}")
            blocked = classify_block(html, final_url)
            if blocked:
                return PageFetch(html=html, url=final_url, status=status, error=blocked)
            return PageFetch(html=html, url=final_url, status=status, error=None)
        return PageFetch(html="", url=url, status=None, error=last_error)

    def try_shoprite_zip(self, zip_code: str) -> bool:
        """Fill a ZIP field on the ShopRite home page when one is present."""
        page = self.page()
        self._pause_between_pages()
        page.goto("https://shop.shoprite.com/", wait_until="domcontentloaded")
        selectors = (
            "input[name='zip']",
            "input[name='zipCode']",
            "input[placeholder*='ZIP' i]",
            "input[aria-label*='ZIP' i]",
            "input[id*='zip' i]",
        )
        field = None
        for selector in selectors:
            field = page.query_selector(selector)
            if field is not None:
                break
        if field is None:
            return False
        field.fill(zip_code)
        field.press("Enter")
        page.wait_for_timeout(1000)
        return True

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
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None


class BaseScraper:
    provider = ""

    def __init__(self, session: BrowserSession | None = None):
        self.session = session

    def search_url_for(self, query: str) -> str:
        raise NotImplementedError

    def parse_html(self, html: str, url: str) -> ProductRecord:
        raise NotImplementedError

    def parse_search(self, html: str, url: str) -> list[ProductRecord]:
        raise NotImplementedError

    def scrape_url(self, url: str) -> ProductRecord:
        if self.session is None:
            return ProductRecord(product_url=url, error="no_browser")
        fetched = self.session.fetch(url)
        if fetched.error:
            return ProductRecord(product_url=fetched.url or url, error=fetched.error)
        return self.parse_html(fetched.html, fetched.url or url)

    def search(self, query: str) -> list[ProductRecord]:
        url = self.search_url_for(query)
        if self.session is None:
            return [ProductRecord(product_url=url, error="no_browser")]
        fetched = self.session.fetch(url)
        if fetched.error:
            return [ProductRecord(product_url=fetched.url or url, error=fetched.error)]
        return self.parse_search(fetched.html, fetched.url or url)


def store_context_error(storage_exists: bool, zip_code: str, zip_confirmed: bool) -> str | None:
    if storage_exists or zip_confirmed:
        return None
    if not (zip_code or "").strip():
        return "store_context_missing"
    return "store_context_unconfirmed"


def encoded_query(query: str) -> str:
    return quote_plus(query)
