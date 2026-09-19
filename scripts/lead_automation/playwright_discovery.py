#!/usr/bin/env python3
"""
playwright_discovery.py

Browser-based Google Maps business discovery for leadgen.

Uses one Playwright browser/context/page for a whole run. Does not call
Google Places APIs. Must not import leadgen.
"""
from __future__ import annotations

from urllib.parse import quote_plus, urlparse, unquote
import hashlib
import random
import re
import time

from helper_scripts.utils.logger.logger import setup_logger

logger = setup_logger(
    name="leadgen",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)

BROWSER_TIMEOUT = 45
SEARCH_DELAY_MIN = 2.0
SEARCH_DELAY_MAX = 4.5
DETAIL_DELAY_MIN = 1.2
DETAIL_DELAY_MAX = 2.8
SCROLL_PAUSE = 2.2
SEARCH_RETRIES = 1

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}

PLACE_HREF_RE = re.compile(r"/maps/place/", re.I)
CHIJ_RE = re.compile(r"(?:!19s|place_id[=:])(ChIJ[\w-]+)")
HEX_FID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
RATING_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)")
REVIEWS_RE = re.compile(r"\(([0-9,]+)\)")
CARD_PHONE_RE = re.compile(
    r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)
END_OF_LIST_MARKERS = (
    "you've reached the end of the list",
    "you have reached the end of the list",
)
VALID_AREA_EXPANSIONS = ("off", "light", "dense")
AREA_EXPANSION_EXTRA_POINTS = {
    "off": 0,
    "light": 4,
    "dense": 8,
}


def is_google_block_page(html, url=""):
    """Return True only for clear Google sorry/traffic interstitial pages.

    Maps pages include a noscript "enable javascript" fallback; that alone is
    not treated as a block.
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


def _strip_label(value, prefixes):
    if not value:
        return None
    text = str(value).strip()
    lower = text.lower()
    for prefix in prefixes:
        if lower.startswith(prefix.lower()):
            text = text[len(prefix):].strip(" :")
            break
    return text.strip() or None


def normalize_profile_url(url):
    """Collapse a Maps place URL to a stable identity key."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path or "")
        # Prefer place path without query/fragment noise.
        if "/maps/place/" in path:
            # Keep /maps/place/<name>/ if present; drop trailing data when possible.
            parts = path.split("/maps/place/", 1)[1]
            name = parts.split("/")[0]
            fid = None
            m = HEX_FID_RE.search(url) or HEX_FID_RE.search(unquote(parsed.query or ""))
            if m:
                fid = m.group(1).lower()
            chij = None
            m2 = CHIJ_RE.search(url)
            if m2:
                chij = m2.group(1)
            if chij:
                return f"https://www.google.com/maps/place/?q=place_id:{chij}"
            if fid:
                return f"https://www.google.com/maps/place/?q={fid}"
            if name:
                return f"https://www.google.com/maps/place/{name}"
        return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    except Exception:
        return str(url).split("?")[0].split("#")[0]


def extract_place_id_from_url(url):
    """Return a Google place_id (ChIJ...) or a stable maps: fallback id."""
    if not url:
        return None
    m = CHIJ_RE.search(url)
    if m:
        return m.group(1)
    m = HEX_FID_RE.search(url)
    if m:
        return f"maps:{m.group(1).lower()}"
    stable = normalize_profile_url(url)
    if stable:
        digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:20]
        return f"maps:{digest}"
    return None


def _parse_rating_block(text):
    rating = None
    reviews = None
    if not text:
        return rating, reviews
    cleaned = text.replace("\n", " ").strip()
    m = RATING_RE.search(cleaned)
    if m:
        try:
            rating = float(m.group(1))
        except ValueError:
            rating = None
    m = REVIEWS_RE.search(cleaned)
    if m:
        try:
            reviews = int(m.group(1).replace(",", ""))
        except ValueError:
            reviews = None
    return rating, reviews


def parse_latlng(coords):
    """Parse coords.json 'lat,lng' (or a 2-tuple) into floats."""
    if coords is None:
        return None
    if isinstance(coords, (tuple, list)) and len(coords) >= 2:
        try:
            return float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            return None
    parts = str(coords).split(",")
    if len(parts) < 2:
        return None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None


def normalize_area_expansion(value, default="off"):
    if isinstance(value, str) and value.strip().lower() in VALID_AREA_EXPANSIONS:
        return value.strip().lower()
    return default


def area_search_multiplier(mode):
    """How many Maps queries run per keyword×city (center + extra points)."""
    mode = normalize_area_expansion(mode)
    return 1 + AREA_EXPANSION_EXTRA_POINTS.get(mode, 0)


def expansion_points(coords, mode="off"):
    """Lat/lng points around a city center used to break Maps' ~120 result cap."""
    mode = normalize_area_expansion(mode)
    parsed = parse_latlng(coords)
    if not parsed or mode == "off":
        return []
    lat, lng = parsed
    if mode == "light":
        delta = 0.12  # ~13 km
        return [
            (lat + delta, lng),
            (lat - delta, lng),
            (lat, lng + delta),
            (lat, lng - delta),
        ]
    delta = 0.08  # ~9 km; 3x3 grid minus center
    points = []
    for d_lat in (-delta, 0.0, delta):
        for d_lng in (-delta, 0.0, delta):
            if d_lat == 0.0 and d_lng == 0.0:
                continue
            points.append((lat + d_lat, lng + d_lng))
    return points


def parse_card_fields(card_text, extra=None):
    """Pull phone/website/rating/address from a Maps results-feed card."""
    extra = extra or {}
    fields = {}
    website = (extra.get("website") or "").strip()
    if website:
        try:
            host = urlparse(website).netloc.lower()
        except Exception:
            host = ""
        if "google." not in host and "googleusercontent." not in host:
            fields["website"] = website

    rating_text = extra.get("ratingText") or extra.get("rating_text") or ""
    reviews_text = extra.get("reviewsText") or extra.get("reviews_text") or ""
    rating, reviews = _parse_rating_block(f"{rating_text} {reviews_text}".strip())
    if rating is None and rating_text:
        rating, _ = _parse_rating_block(rating_text)
    if rating is not None:
        fields["rating"] = rating
    if reviews is None and reviews_text:
        _, reviews = _parse_rating_block(reviews_text)
    if reviews is not None:
        fields["user_ratings_total"] = reviews

    text = card_text or ""
    phone_match = CARD_PHONE_RE.search(text)
    if phone_match:
        fields["phone_google"] = phone_match.group(0)

    for line in text.splitlines():
        if "·" not in line:
            continue
        left, right = line.split("·", 1)
        left, right = left.strip(), right.strip()
        if left and "category" not in fields:
            fields["category"] = left
        if right and "address" not in fields:
            fields["address"] = right
        break
    return fields


def business_dedupe_key(entry):
    """Stable multi-field identity for aggressive deduplication."""
    place_id = (entry.get("place_id") or "").strip()
    if place_id:
        return ("place_id", place_id.lower())

    profile = normalize_profile_url(entry.get("profile_url") or "")
    if profile:
        return ("profile_url", profile.lower())

    name = re.sub(r"\s+", " ", (entry.get("business_name") or "").strip().lower())
    phone_digits = re.sub(r"\D", "", str(entry.get("phone_google") or ""))
    if len(phone_digits) == 11 and phone_digits.startswith("1"):
        phone_digits = phone_digits[1:]
    if name and len(phone_digits) == 10:
        return ("name_phone", name, phone_digits)

    address = re.sub(r"\s+", " ", (entry.get("address") or "").strip().lower())
    address = re.sub(r"[^\w\s,]", "", address)
    if name and address:
        return ("name_address", name, address)

    if name:
        return ("name", name)
    return None


class BusinessDiscoverySession:
    """One Playwright browser for multi-page Maps discovery."""

    def __init__(self, delay=None, detail_delay=None):
        self.google_blocked = False
        self._playwright = None
        self._browser = None
        self._page = None
        self._searches_done = 0
        self._details_done = 0
        self._delay = delay
        self._detail_delay = detail_delay
        self.stats = {
            "searches_performed": 0,
            "locations_searched": 0,
            "pages_processed": 0,
            "businesses_discovered": 0,
            "detail_pages_opened": 0,
            "errors": 0,
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        page, browser, playwright = self._page, self._browser, self._playwright
        self._page = None
        self._browser = None
        self._playwright = None
        for closer, label in (
            (getattr(page, "close", None), "page"),
            (getattr(browser, "close", None), "browser"),
            (getattr(playwright, "stop", None), "playwright"),
        ):
            if closer is None:
                continue
            try:
                closer()
            except Exception as exc:
                logger.error("[Playwright] Failed to close %s: %s", label, exc)

    def _ensure_browser(self):
        if self.google_blocked:
            return None
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            logger.error("[Playwright] Playwright is not available: %s", exc)
            self.google_blocked = True
            return None
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._page = self._browser.new_page(
                user_agent=FETCH_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            self._page.set_default_timeout(BROWSER_TIMEOUT * 1000)
            return self._page
        except Exception as exc:
            logger.error("[Playwright] Failed to start browser: %s", exc)
            self.google_blocked = True
            self.close()
            return None

    def _sleep_between_searches(self):
        if self._searches_done <= 0:
            return
        if self._delay is not None:
            time.sleep(self._delay)
            return
        time.sleep(random.uniform(SEARCH_DELAY_MIN, SEARCH_DELAY_MAX))

    def _sleep_between_details(self):
        if self._details_done <= 0:
            return
        if self._detail_delay is not None:
            time.sleep(self._detail_delay)
            return
        time.sleep(random.uniform(DETAIL_DELAY_MIN, DETAIL_DELAY_MAX))

    def _dismiss_consent(self, page):
        for sel in (
            'button:has-text("Accept all")',
            'button:has-text("Reject all")',
            'button:has-text("I agree")',
            'button:has-text("Accept")',
        ):
            try:
                btn = page.locator(sel).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=2000)
                    time.sleep(1)
                    return
            except Exception:
                continue

    def _feed_reached_end(self, page):
        try:
            body = (page.inner_text("body") or "").lower()
        except Exception:
            body = ""
        return any(marker in body for marker in END_OF_LIST_MARKERS)

    def _collect_listing_links(self, page):
        """Return ordered unique listings, including phone/website/rating from cards."""
        raw = page.evaluate(
            """() => {
              const out = [];
              const seen = new Set();
              const articles = document.querySelectorAll('div[role="article"], div.Nv2PK');
              const nodes = articles.length
                ? articles
                : document.querySelectorAll('a[href*="/maps/place/"]');
              for (const node of nodes) {
                const a = (node.matches && node.matches('a[href*="/maps/place/"]'))
                  ? node
                  : node.querySelector('a[href*="/maps/place/"]');
                if (!a) continue;
                const href = a.href || '';
                if (!href || seen.has(href)) continue;
                const name = (a.getAttribute('aria-label') || '').trim();
                if (!name) continue;
                seen.add(href);
                let website = '';
                for (const link of node.querySelectorAll('a[href]')) {
                  const h = link.href || '';
                  const label = (
                    link.getAttribute('aria-label') || link.innerText || ''
                  ).toLowerCase();
                  if (!h || h.includes('google.') || h.includes('/maps/')) continue;
                  if (label.includes('website') || label.includes('visit')) {
                    website = h;
                    break;
                  }
                }
                const ratingEl = node.querySelector('.MW4etd');
                const reviewsEl = node.querySelector('.UY7F9');
                out.push({
                  name,
                  href,
                  cardText: (node.innerText || '').trim(),
                  website,
                  ratingText: ratingEl ? ratingEl.innerText : '',
                  reviewsText: reviewsEl ? reviewsEl.innerText : '',
                });
              }
              return out;
            }"""
        )
        listings = []
        seen_keys = set()
        for item in raw or []:
            href = item.get("href") or ""
            name = (item.get("name") or "").strip()
            if not href or not PLACE_HREF_RE.search(href):
                continue
            place_id = extract_place_id_from_url(href)
            key = place_id or normalize_profile_url(href) or name.lower()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            entry = {
                "business_name": name,
                "profile_url": href,
                "place_id": place_id,
            }
            extra = parse_card_fields(
                item.get("cardText") or "",
                extra=item,
            )
            entry.update({k: v for k, v in extra.items() if v not in (None, "")})
            listings.append(entry)
        return listings

    def _scroll_feed(self, page):
        try:
            feed = page.locator('div[role="feed"]')
            if feed.count() == 0:
                page.mouse.wheel(0, 4000)
                return False
            handle = feed.element_handle()
            if handle is None:
                return False
            page.evaluate(
                """(el) => {
                  el.scrollTo(0, el.scrollHeight);
                }""",
                handle,
            )
            page.evaluate(
                """() => {
                  const items = document.querySelectorAll(
                    'div[role="feed"] a[href*="/maps/place/"]'
                  );
                  if (items.length) {
                    items[items.length - 1].scrollIntoView({block: 'end'});
                  }
                }"""
            )
            return True
        except Exception as exc:
            logger.error("[Playwright] Feed scroll failed: %s", exc)
            return False

    def _click_next_page(self, page):
        """Try classic next-page controls when present (Local/Maps variants)."""
        selectors = (
            'button[aria-label="Next page"]',
            'button[aria-label*="Next page"]',
            'a[aria-label="Next page"]',
            '#pnnext',
            'a#pnnext',
        )
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if not loc.count():
                    continue
                disabled = loc.get_attribute("disabled")
                aria_disabled = (loc.get_attribute("aria-disabled") or "").lower()
                if disabled is not None or aria_disabled in ("true", "1"):
                    continue
                if not loc.is_visible():
                    continue
                loc.click(timeout=3000)
                return True
            except Exception:
                continue
        return False

    def search_location(
        self,
        keyword,
        city,
        state,
        coords=None,
        max_pages=20,
        max_results=400,
        area_expansion="off",
    ):
        """Search a city plus optional nearby map cells; return unique listings."""
        queries = [f"{keyword} near {city}, {state}"]
        for lat, lng in expansion_points(coords, area_expansion):
            queries.append(f"{keyword} near {lat:.4f},{lng:.4f}")

        collected = []
        seen_keys = set()
        max_results = max(1, int(max_results or 1))
        for query in queries:
            if self.google_blocked:
                break
            remaining = max_results - len(collected)
            if remaining <= 0:
                break
            batch = self.search_listings(
                keyword,
                city,
                state,
                max_pages=max_pages,
                max_results=remaining,
                query=query,
            )
            for item in batch:
                key = item.get("place_id") or normalize_profile_url(
                    item.get("profile_url")
                )
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                collected.append(item)
        return collected

    def search_listings(
        self,
        keyword,
        city,
        state,
        max_pages=20,
        max_results=400,
        query=None,
    ):
        """Paginate Maps results for one keyword/location. Returns listing stubs."""
        if self.google_blocked:
            return []
        page = self._ensure_browser()
        if page is None:
            return []

        query = query or f"{keyword} near {city}, {state}"
        search_url = "https://www.google.com/maps/search/" + quote_plus(query)
        logger.critical("[Playwright] Searching: %s — %s, %s", keyword, city, state)
        self._sleep_between_searches()

        html = ""
        current_url = search_url
        last_error = None
        for attempt in range(SEARCH_RETRIES + 1):
            try:
                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT * 1000,
                )
                self._dismiss_consent(page)
                time.sleep(2.5)
                current_url = page.url or search_url
                html = page.content() or ""
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                logger.info("[Playwright] Search attempt %d failed: %s", attempt + 1, exc)
                if attempt < SEARCH_RETRIES:
                    time.sleep(1.5)

        self._searches_done += 1
        self.stats["searches_performed"] += 1

        if last_error is not None and not html:
            logger.error("[Playwright] Search failed for %s: %s", query, last_error)
            self.stats["errors"] += 1
            return []

        if is_google_block_page(html, current_url):
            if not self.google_blocked:
                logger.error(
                    "[Playwright] CAPTCHA or block page detected; skipping further searches"
                )
            self.google_blocked = True
            self.stats["errors"] += 1
            return []

        collected = []
        seen_keys = set()
        stagnant_pages = 0
        max_pages = max(1, int(max_pages or 1))
        max_results = max(1, int(max_results or 1))

        for page_num in range(1, max_pages + 1):
            try:
                # Wait briefly for feed cards to settle.
                try:
                    page.locator('a[href*="/maps/place/"]').first.wait_for(
                        state="attached", timeout=8000
                    )
                except Exception:
                    pass
                time.sleep(0.8)
                listings = self._collect_listing_links(page)
                new_on_page = 0
                for item in listings:
                    key = item.get("place_id") or normalize_profile_url(item.get("profile_url"))
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    collected.append(item)
                    new_on_page += 1
                    if len(collected) >= max_results:
                        break

                self.stats["pages_processed"] += 1
                logger.critical(
                    "[Playwright] Page %d: %d businesses found",
                    page_num,
                    new_on_page,
                )

                if len(collected) >= max_results:
                    logger.critical(
                        "[Playwright] Reached max results per search (%d).",
                        max_results,
                    )
                    break

                if new_on_page == 0:
                    stagnant_pages += 1
                else:
                    stagnant_pages = 0

                if stagnant_pages >= 2 or self._feed_reached_end(page):
                    logger.critical("[Playwright] No additional results found.")
                    break

                if page_num >= max_pages:
                    break

                advanced = False
                before = len(seen_keys)
                if self._click_next_page(page):
                    advanced = True
                else:
                    advanced = self._scroll_feed(page)

                if not advanced:
                    logger.critical("[Playwright] No additional results found.")
                    break

                # Wait for the feed to grow after scroll/next instead of a single pause.
                grew = False
                deadline = time.time() + SCROLL_PAUSE + 1.5
                while time.time() < deadline:
                    time.sleep(0.4)
                    after_listings = self._collect_listing_links(page)
                    after = before
                    for item in after_listings:
                        key = (
                            item.get("place_id")
                            or normalize_profile_url(item.get("profile_url"))
                        )
                        if key and key not in seen_keys:
                            after += 1
                    if after > before:
                        grew = True
                        break
                    self._scroll_feed(page)
                if not grew and new_on_page == 0:
                    stagnant_pages += 1
                    if stagnant_pages >= 2:
                        logger.critical("[Playwright] No additional results found.")
                        break
            except Exception as exc:
                logger.error("[Playwright] Failed processing page %d: %s", page_num, exc)
                self.stats["errors"] += 1
                continue

        logger.critical("[Playwright] Total discovered: %d", len(collected))
        self.stats["businesses_discovered"] += len(collected)
        return collected

    def enrich_listing(self, listing):
        """Open a Maps place page and fill phone/website/address/rating fields."""
        if self.google_blocked:
            return dict(listing)
        page = self._ensure_browser()
        if page is None:
            return dict(listing)

        url = listing.get("profile_url")
        if not url:
            return dict(listing)

        self._sleep_between_details()
        entry = dict(listing)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT * 1000)
            time.sleep(1.8)
            self._dismiss_consent(page)
            if is_google_block_page(page.content() or "", page.url or ""):
                logger.error("[Playwright] CAPTCHA or block page on detail view")
                self.google_blocked = True
                self.stats["errors"] += 1
                return entry

            detail = page.evaluate(
                """() => {
                  const out = {};
                  const h1 = document.querySelector('h1');
                  if (h1 && h1.innerText) out.name = h1.innerText.trim();
                  const addr = document.querySelector('button[data-item-id="address"]');
                  if (addr) out.address = addr.getAttribute('aria-label') || addr.innerText;
                  const phone = document.querySelector('button[data-item-id^="phone"]');
                  if (phone) out.phone = phone.getAttribute('aria-label') || phone.innerText;
                  const web = document.querySelector('a[data-item-id="authority"]');
                  if (web) {
                    out.website = web.href || '';
                    out.website_label = web.getAttribute('aria-label') || '';
                  }
                  const rating = document.querySelector('div.F7nice');
                  if (rating) out.rating_block = rating.innerText;
                  const cat = document.querySelector('button[jsaction*=\"category\"], button[jsaction*=\"pane.rating.category\"]');
                  if (cat) out.category = (cat.innerText || '').trim();
                  out.url = location.href;
                  return out;
                }"""
            )
            self._details_done += 1
            self.stats["detail_pages_opened"] += 1

            if detail.get("name"):
                entry["business_name"] = detail["name"]
            address = _strip_label(detail.get("address"), ("Address",))
            if address:
                entry["address"] = address
            phone = _strip_label(detail.get("phone"), ("Phone",))
            if phone:
                entry["phone_google"] = phone
            website = (detail.get("website") or "").strip()
            if website and "google." not in urlparse(website).netloc.lower():
                entry["website"] = website
            rating, reviews = _parse_rating_block(detail.get("rating_block"))
            if rating is not None:
                entry["rating"] = rating
            if reviews is not None:
                entry["user_ratings_total"] = reviews
            if detail.get("category"):
                entry["category"] = detail["category"]
            detail_url = detail.get("url") or page.url or url
            entry["profile_url"] = detail_url
            place_id = extract_place_id_from_url(detail_url) or entry.get("place_id")
            if place_id:
                entry["place_id"] = place_id
        except Exception as exc:
            logger.error(
                "[Playwright] Detail fetch failed for %s: %s",
                listing.get("business_name"),
                exc,
            )
            self.stats["errors"] += 1
        return entry


def dedupe_businesses(businesses):
    """Deduplicate a list of business dicts; returns (unique_list, duplicates_removed)."""
    unique = []
    seen = set()
    duplicates = 0
    for entry in businesses:
        key = business_dedupe_key(entry)
        if key is None:
            unique.append(entry)
            continue
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(entry)
    return unique, duplicates
