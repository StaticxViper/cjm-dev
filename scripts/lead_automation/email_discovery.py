#!/usr/bin/env python3
"""
email_discovery.py

Google-search and website email discovery for leadgen.

Playwright is used only for Google result pages. Website fetches use requests
+ BeautifulSoup. This module must not import leadgen.
"""
from html import unescape
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
import json
import random
import re
import time

import requests
from bs4 import BeautifulSoup
from helper_scripts.utils.logger.logger import setup_logger

logger = setup_logger(
    name="leadgen",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)

MAX_GOOGLE_SEARCHES_PER_LEAD = 5
MAX_WEBSITE_PAGES_PER_LEAD = 6
REQUEST_TIMEOUT = 15
BROWSER_TIMEOUT = 30
SEARCH_DELAY_MIN = 3.0
SEARCH_DELAY_MAX = 7.0
SEARCH_RETRIES = 1

CONTACT_PAGE_PATHS = (
    "/contact",
    "/contact-us",
    "/contact.html",
    "/about",
    "/about-us",
    "/get-in-touch",
)

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
)
US_PHONE_RE = re.compile(
    r"^(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$"
)
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
STATE_RE = re.compile(r"\b([A-Z]{2})\b")

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
JUNK_DOMAINS = frozenset({
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "test.net",
    "domain.com",
    "email.com",
    "yourdomain.com",
    "sentry.io",
    "wixpress.com",
    "facebook.com",
    "fb.com",
})
JUNK_LOCAL_PARTS = frozenset({
    "example",
    "test",
    "email",
    "yourname",
    "youremail",
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "mailer-daemon",
    "postmaster",
})
PREFERRED_LOCAL_PARTS = (
    "info",
    "contact",
    "office",
    "sales",
    "hello",
    "admin",
    "support",
    "owner",
)
CONSUMER_DOMAINS = frozenset({
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "live.com",
    "msn.com",
    "ymail.com",
})
DIRECTORY_HOSTS = frozenset({
    "facebook.com",
    "yelp.com",
    "yellowpages.com",
    "bbb.org",
    "mapquest.com",
    "bing.com",
    "google.com",
    "apple.com",
    "tripadvisor.com",
    "angi.com",
    "homeadvisor.com",
    "thumbtack.com",
    "nextdoor.com",
    "linkedin.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "wikipedia.org",
    "craigslist.org",
})
CAPTCHA_MARKERS = (
    "unusual traffic",
    "detected unusual traffic",
    "our systems have detected",
    "enable javascript",
    "recaptcha",
    "/sorry/",
    "google.com/sorry",
)

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
SOURCE_WEBSITE = "website"
SOURCE_GOOGLE = "google"

NAME_STOPWORDS = frozenset({
    "the", "a", "an", "and", "of", "llc", "inc", "incorporated", "co", "corp",
    "corporation", "ltd", "limited", "company", "pllc", "lp", "llp",
})


def is_valid_us_phone(phone):
    """Return True if phone is present and matches a valid US format."""
    if not phone or not str(phone).strip():
        return False
    phone = str(phone).strip()
    if US_PHONE_RE.match(phone):
        return True
    digits = re.sub(r"[^0-9]", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return len(digits) == 10


def _normalize_email(raw):
    if not raw:
        return ""
    value = unescape(str(raw)).strip()
    value = value.replace("mailto:", "", 1) if value.lower().startswith("mailto:") else value
    value = value.split("?", 1)[0].strip().strip(".,;:<>()[]\"'")
    return value.lower()


def validate_email(email):
    """Return a normalized email if it looks like a real public address, else ''."""
    email = _normalize_email(email)
    if not email or not EMAIL_RE.fullmatch(email):
        return ""
    if any(email.endswith(ext) for ext in IMAGE_EXTS):
        return ""
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return ""
    if domain in JUNK_DOMAINS or any(domain.endswith("." + d) for d in JUNK_DOMAINS):
        return ""
    if local in JUNK_LOCAL_PARTS or local.startswith("noreply") or local.startswith("no-reply"):
        return ""
    if ".." in email or email.startswith(".") or domain.startswith("."):
        return ""
    return email


def extract_emails_from_html(html, soup=None, website=None):
    """Return unique validated emails found in HTML and mailto links."""
    text = unescape(html or "")
    found = set()
    for match in EMAIL_RE.findall(text):
        email = validate_email(match)
        if email:
            found.add(email)

    if soup is None and text:
        soup = BeautifulSoup(text, "html.parser")
    if soup is not None:
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if href.lower().startswith("mailto:"):
                email = validate_email(href)
                if email:
                    found.add(email)
        for email in _extract_schema_emails(soup):
            found.add(email)

    ranked = sorted(found, key=lambda e: _email_rank(e, website))
    return ranked


def _extract_schema_emails(soup):
    emails = []
    for script in soup.find_all("script", attrs={"type": lambda t: t and "ld+json" in t.lower()}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        emails.extend(_walk_schema_emails(data))
    return emails


def _walk_schema_emails(node):
    found = []
    if isinstance(node, dict):
        value = node.get("email")
        if isinstance(value, str):
            email = validate_email(value)
            if email:
                found.append(email)
        elif isinstance(value, list):
            for item in value:
                email = validate_email(item)
                if email:
                    found.append(email)
        for child in node.values():
            found.extend(_walk_schema_emails(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(_walk_schema_emails(child))
    return found


def _email_rank(email, website=None):
    local, _, domain = email.partition("@")
    preferred = 0 if local in PREFERRED_LOCAL_PARTS else 1
    consumer = 1 if domain in CONSUMER_DOMAINS else 0
    site_match = 1
    host = _host_from_url(website)
    if host and _domains_match(domain, host):
        site_match = 0
    return (site_match, preferred, consumer, email)


def lead_has_valid_email(lead):
    return bool(lead_emails(lead))


def lead_emails(lead):
    raw = lead.get("email") if lead else None
    if isinstance(raw, (list, tuple)):
        candidates = raw
    else:
        candidates = str(raw or "").split(";")
    emails = []
    seen = set()
    for item in candidates:
        email = validate_email(item)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def lead_has_valid_phone(lead):
    if not lead:
        return False
    if is_valid_us_phone(lead.get("phone_google")):
        return True
    website_phones = lead.get("phone_website") or ""
    if isinstance(website_phones, (list, tuple)):
        parts = website_phones
    else:
        parts = str(website_phones).split(";")
    return any(is_valid_us_phone(part) for part in parts)


def cache_key(lead, city=None, state=None):
    name = _normalize_name(lead.get("business_name") if lead else "")
    parts = parse_address_parts((lead or {}).get("address"), city, state)
    loc_city = _normalize_name(parts.get("city") or city or "")
    loc_state = str(parts.get("state") or state or "").strip().lower()
    return f"{name}|{loc_city}|{loc_state}"


def _normalize_name(value):
    text = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
    tokens = [t for t in text.split() if t and t not in NAME_STOPWORDS]
    return " ".join(tokens)


def parse_address_parts(address, city=None, state=None):
    """Best-effort US address split: street, city, state, zip."""
    parts = {"street": None, "city": city, "state": state, "zip": None}
    if not address or not str(address).strip():
        return parts
    text = str(address).strip()
    zip_match = ZIP_RE.search(text)
    if zip_match:
        parts["zip"] = zip_match.group(1)
    chunks = [c.strip() for c in text.split(",") if c.strip()]
    if chunks:
        parts["street"] = chunks[0]
        if len(chunks) >= 2 and not parts["city"]:
            maybe_city = chunks[1]
            if not STATE_RE.fullmatch(maybe_city.split()[0] if maybe_city else ""):
                parts["city"] = re.sub(r"\s+[A-Z]{2}\s+\d{5}.*$", "", maybe_city).strip() or maybe_city
        for chunk in chunks[1:]:
            state_match = STATE_RE.search(chunk)
            if state_match and not parts["state"]:
                parts["state"] = state_match.group(1)
                break
    if not parts["state"]:
        state_match = STATE_RE.search(text)
        if state_match:
            parts["state"] = state_match.group(1)
    return parts


def build_google_queries(lead, city=None, state=None, max_queries=MAX_GOOGLE_SEARCHES_PER_LEAD):
    """Targeted queries using as much known business data as possible."""
    name = (lead.get("business_name") or "").strip()
    if not name:
        return []
    addr = parse_address_parts(lead.get("address"), city, state)
    city = addr.get("city") or city
    state = addr.get("state") or state
    street = addr.get("street")
    zipc = addr.get("zip")
    phone = (lead.get("phone_google") or "").strip()
    quoted = f'"{name}"'

    queries = []
    if city and state:
        queries.append(f'{quoted} "{city}" {state} email')
        queries.append(f'{quoted} "{city}" {state} contact')
    if street and state:
        queries.append(f'{quoted} "{street}" {state} contact')
    if city:
        queries.append(f'{quoted} "{city}" contact us')
    if city and state:
        queries.append(f'{quoted} "{city}" {state}')
    if zipc:
        queries.append(f"{quoted} {zipc} email")
    if phone:
        queries.append(f"{quoted} {phone} email")
    queries.append(f'{quoted} "@gmail.com"')
    queries.append(f'{quoted} "@yahoo.com"')

    seen = set()
    out = []
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        out.append(query)
        if len(out) >= max_queries:
            break
    return out


def _host_from_url(url):
    if not url:
        return ""
    raw = url if "://" in str(url) else f"http://{url}"
    try:
        host = (urlparse(raw).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""
    return host


def _registrable_domain(host):
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _domains_match(email_domain, site_host):
    if not email_domain or not site_host:
        return False
    email_domain = email_domain.lower()
    site_host = site_host.lower().removeprefix("www.")
    return (
        email_domain == site_host
        or email_domain == _registrable_domain(site_host)
        or site_host.endswith("." + email_domain)
        or email_domain.endswith("." + _registrable_domain(site_host))
    )


def is_directory_host(url):
    host = _host_from_url(url)
    if not host:
        return True
    return any(host == d or host.endswith("." + d) for d in DIRECTORY_HOSTS)


def _name_tokens(name):
    return [t for t in _normalize_name(name).split() if len(t) > 1]


def _name_appears(name, text):
    if not name or not text:
        return False
    lowered = text.lower()
    if name.lower() in lowered:
        return True
    tokens = _name_tokens(name)
    if len(tokens) < 2:
        return bool(tokens) and tokens[0] in lowered
    return sum(1 for t in tokens if t in lowered) >= min(2, len(tokens))


def discover_business_website(results, lead):
    """Return the most likely official website from SERP results."""
    name = (lead.get("business_name") or "").strip()
    known = _host_from_url(lead.get("website"))
    if known and not is_directory_host(lead.get("website")):
        return lead.get("website")

    for result in results or []:
        url = (result.get("url") or "").strip()
        if not url or is_directory_host(url):
            continue
        title = result.get("title") or ""
        snippet = result.get("snippet") or ""
        if _name_appears(name, f"{title} {snippet}"):
            return url
    for result in results or []:
        url = (result.get("url") or "").strip()
        if url and not is_directory_host(url):
            return url
    return None


def score_email_confidence(email, lead, page_url=None, page_text="", website=None):
    """HIGH / MEDIUM / LOW based on domain match and corroborating signals."""
    email = validate_email(email)
    if not email:
        return CONFIDENCE_LOW
    domain = email.rsplit("@", 1)[-1]
    website = website or (lead.get("website") if lead else None)
    site_host = _host_from_url(website)
    text = (page_text or "").lower()
    url = (page_url or "").lower()
    name = (lead.get("business_name") if lead else "") or ""
    addr = parse_address_parts((lead or {}).get("address"))
    city = (addr.get("city") or "").lower()
    state = (addr.get("state") or "").lower()

    name_on_page = _name_appears(name, text) or _name_appears(name, url)
    contact_page = any(path in url for path in CONTACT_PAGE_PATHS)
    city_match = bool(city and city in text)
    state_match = bool(state and re.search(rf"\b{re.escape(state)}\b", text))
    phone_match = _phone_in_text(lead, page_text)
    domain_matches_site = _domains_match(domain, site_host)

    if domain_matches_site and (name_on_page or contact_page):
        return CONFIDENCE_HIGH
    if domain_matches_site:
        return CONFIDENCE_MEDIUM

    if domain in CONSUMER_DOMAINS:
        signals = sum([name_on_page, city_match or state_match, phone_match])
        if signals >= 2:
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_LOW

    if name_on_page and (city_match or state_match or phone_match or contact_page):
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _phone_in_text(lead, text):
    if not lead or not text:
        return False
    candidates = [lead.get("phone_google"), lead.get("phone_website")]
    digits_in_text = re.sub(r"[^0-9]", "", text)
    for raw in candidates:
        if not raw:
            continue
        for part in str(raw).split(";"):
            digits = re.sub(r"[^0-9]", "", part)
            if len(digits) == 11 and digits.startswith("1"):
                digits = digits[1:]
            if len(digits) == 10 and digits in digits_in_text:
                return True
    return False


def _normalize_website_url(url):
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def fetch_html(url, timeout=REQUEST_TIMEOUT):
    """GET url and return response text, or raise."""
    response = requests.get(
        url,
        timeout=timeout,
        headers=FETCH_HEADERS,
        allow_redirects=True,
    )
    return response.text or ""


def extract_phones_from_html(html):
    """Return sorted unique US-format phones found in HTML."""
    matches = re.findall(
        r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        html or "",
    )
    cleaned = set()
    for match in matches:
        digits = re.sub(r"[^0-9]", "", match)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            cleaned.add("(+1) {}-{}-{}".format(digits[0:3], digits[3:6], digits[6:10]))
    return sorted(cleaned)


def inspect_website(url, max_pages=MAX_WEBSITE_PAGES_PER_LEAD):
    """Fetch homepage plus a few contact/about pages; extract emails and phones."""
    result = {
        "emails": [],
        "phones": [],
        "https": False,
        "has_viewport": False,
        "html_length": 0,
        "has_cta": False,
        "page_text": "",
        "page_url": url,
        "error": None,
    }
    if not url:
        return result
    url = _normalize_website_url(url)
    result["https"] = url.lower().startswith("https://")
    result["page_url"] = url

    pages_fetched = 0
    emails = []
    phones = set()
    texts = []
    try:
        html = fetch_html(url)
        pages_fetched += 1
    except Exception as exc:
        result["error"] = str(exc)
        logger.info("[WEBSITE] Failed to fetch %s: %s", url, exc)
        return result

    result["html_length"] = len(html)
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("meta", attrs={"name": lambda x: x and x.lower() == "viewport"}):
        result["has_viewport"] = True
    page_text = soup.get_text(separator=" ", strip=True)
    texts.append(page_text)
    result["has_cta"] = any(kw in page_text.lower() for kw in ("call", "contact", "quote", "estimate"))
    emails = extract_emails_from_html(html, soup=soup, website=url)
    phones.update(extract_phones_from_html(html))

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if not emails:
        logger.info("[WEBSITE] Checking contact page")
        for path in CONTACT_PAGE_PATHS:
            if pages_fetched >= max_pages:
                break
            page_url = urljoin(base + "/", path.lstrip("/"))
            try:
                page_html = fetch_html(page_url)
            except Exception:
                continue
            pages_fetched += 1
            page_soup = BeautifulSoup(page_html, "html.parser")
            emails = extract_emails_from_html(page_html, soup=page_soup, website=url)
            phones.update(extract_phones_from_html(page_html))
            texts.append(page_soup.get_text(separator=" ", strip=True))
            result["page_url"] = page_url
            if emails:
                break

    result["emails"] = emails
    result["phones"] = sorted(phones)
    result["page_text"] = " ".join(texts)
    return result


def parse_google_results(html):
    """Parse organic Google result titles, URLs, and snippets."""
    soup = BeautifulSoup(html or "", "html.parser")
    results = []
    seen = set()

    def _add(url, title, snippet):
        url = _clean_google_url(url)
        if not url or url in seen or is_directory_host(url) and "google.com" in (_host_from_url(url) or ""):
            if not url or url in seen:
                return
        if url in seen:
            return
        if _host_from_url(url).endswith("google.com"):
            return
        seen.add(url)
        results.append({"title": title or "", "url": url, "snippet": snippet or ""})

    for block in soup.select("div.g"):
        link = block.find("a", href=True)
        if not link:
            continue
        title_el = block.find("h3")
        snippet_el = block.select_one(".VwiC3b") or block.find("span")
        _add(
            link.get("href"),
            title_el.get_text(" ", strip=True) if title_el else link.get_text(" ", strip=True),
            snippet_el.get_text(" ", strip=True) if snippet_el else "",
        )

    if not results:
        for link in soup.select("#search a[href], #rso a[href], a[href]"):
            href = link.get("href") or ""
            if not href.startswith("http") and not href.startswith("/url?"):
                continue
            title = link.get_text(" ", strip=True)
            parent = link.find_parent("div")
            snippet = parent.get_text(" ", strip=True) if parent else ""
            _add(href, title, snippet)
            if len(results) >= 10:
                break
    return results


def _clean_google_url(url):
    if not url:
        return ""
    if url.startswith("/url?"):
        query = parse_qs(urlparse(url).query)
        url = (query.get("q") or query.get("url") or [""])[0]
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        return ""
    return url


def is_google_block_page(html, url=""):
    haystack = f"{url or ''} {html or ''}".lower()
    return any(marker in haystack for marker in CAPTCHA_MARKERS)


class EmailDiscoverySession:
    """One Playwright browser per location batch, plus an in-run cache."""

    def __init__(self, delay=None):
        self.google_blocked = False
        self.cache = {}
        self._playwright = None
        self._browser = None
        self._page = None
        self._searches_done = 0
        self._delay = delay

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
                logger.error("[GOOGLE] Failed to close %s: %s", label, exc)

    def _ensure_browser(self):
        if self.google_blocked:
            return None
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            logger.error("[GOOGLE] Playwright is not available: %s", exc)
            self.google_blocked = True
            return None
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._page = self._browser.new_page(
                user_agent=FETCH_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 720},
            )
            self._page.set_default_timeout(BROWSER_TIMEOUT * 1000)
            return self._page
        except Exception as exc:
            logger.error("[GOOGLE] Failed to start browser: %s", exc)
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

    def search(self, query):
        """Return organic results for a Google query, or [] if blocked/failed."""
        if self.google_blocked:
            return []
        page = self._ensure_browser()
        if page is None:
            return []
        self._sleep_between_searches()
        search_url = "https://www.google.com/search?hl=en&num=10&q=" + quote_plus(query)
        logger.info("[GOOGLE] Searching: %s", query)
        html = ""
        current_url = search_url
        last_error = None
        for attempt in range(SEARCH_RETRIES + 1):
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT * 1000)
                current_url = page.url or search_url
                html = page.content() or ""
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                logger.info("[GOOGLE] Search attempt %d failed: %s", attempt + 1, exc)
                if attempt < SEARCH_RETRIES:
                    time.sleep(1)
        self._searches_done += 1
        if last_error is not None and not html:
            logger.error("[GOOGLE] Search failed for %s: %s", query, last_error)
            return []
        if is_google_block_page(html, current_url):
            if not self.google_blocked:
                logger.error("[GOOGLE] CAPTCHA or block page detected; skipping further searches")
            self.google_blocked = True
            return []
        results = parse_google_results(html)
        snippet_emails = extract_emails_from_html(html)
        if snippet_emails:
            results.append({
                "title": "",
                "url": "",
                "snippet": " ".join(snippet_emails),
                "emails": snippet_emails,
            })
        return results


def _accept_confidence(confidence):
    return confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM)


def _apply_email(lead, email, source, confidence, website=None, phones=None, analysis=None):
    lead["email"] = email
    lead["has_email"] = True
    lead["email_source"] = source
    lead["email_confidence"] = confidence
    if website and not (lead.get("website") or "").strip():
        lead["website"] = website
    if phones and not lead_has_valid_phone(lead):
        lead["phone_website"] = ";".join(phones)
    if analysis:
        for key in ("https", "has_viewport", "html_length", "has_cta"):
            if key in analysis:
                lead[key] = analysis[key]
    logger.info("[EMAIL] Found: %s", email)
    logger.info("[EMAIL] Confidence: %s", confidence.upper())
    return lead


def enrich_lead_with_email(lead, city=None, state=None, session=None):
    """Best-effort Google/website enrichment. Mutates and returns lead."""
    if lead is None:
        return lead
    own_session = session is None
    if session is None:
        session = EmailDiscoverySession()
    key = cache_key(lead, city, state)
    cached = session.cache.get(key)
    if cached:
        logger.info("[EMAIL] Using cached discovery for %s", lead.get("business_name"))
        for field in (
            "email", "has_email", "email_source", "email_confidence",
            "website", "phone_website", "https", "has_viewport", "html_length", "has_cta",
        ):
            if field in cached and not lead.get(field):
                lead[field] = cached[field]
        return lead

    if lead_has_valid_email(lead) and lead_has_valid_phone(lead):
        session.cache[key] = dict(lead)
        return lead

    name = lead.get("business_name") or "unknown"
    try:
        website = (lead.get("website") or "").strip()
        if website and not lead_has_valid_email(lead):
            inspected = inspect_website(website)
            accepted = _pick_accepted_email(
                inspected.get("emails") or [],
                lead,
                page_url=inspected.get("page_url"),
                page_text=inspected.get("page_text") or "",
                website=website,
            )
            if accepted:
                _apply_email(
                    lead,
                    accepted[0],
                    SOURCE_WEBSITE,
                    accepted[1],
                    website=website,
                    phones=inspected.get("phones"),
                    analysis=inspected,
                )
                session.cache[key] = dict(lead)
                return lead

        if session.google_blocked:
            logger.info("[EMAIL] No reliable email found")
            session.cache[key] = dict(lead)
            return lead

        queries = build_google_queries(lead, city=city, state=state)
        known_website = website
        for query in queries:
            if session.google_blocked:
                break
            if lead_has_valid_email(lead) and (
                lead_has_valid_phone(lead) or not known_website
            ):
                break
            results = session.search(query)
            for result in results:
                snippet = result.get("snippet") or ""
                snippet_emails = result.get("emails") or extract_emails_from_html(snippet)
                page_url = result.get("url") or ""
                for email in snippet_emails:
                    confidence = score_email_confidence(
                        email,
                        lead,
                        page_url=page_url,
                        page_text=f"{result.get('title') or ''} {snippet}",
                        website=lead.get("website") or known_website,
                    )
                    if _accept_confidence(confidence):
                        _apply_email(lead, email, SOURCE_GOOGLE, confidence)
                        session.cache[key] = dict(lead)
                        return lead

                found_site = discover_business_website([result], lead)
                if not found_site or is_directory_host(found_site):
                    continue
                if _host_from_url(found_site) == _host_from_url(known_website):
                    continue
                logger.info("[GOOGLE] Found possible website: %s", _host_from_url(found_site) or found_site)
                inspected = inspect_website(found_site)
                if inspected.get("error") and not inspected.get("emails"):
                    continue
                if not (lead.get("website") or "").strip():
                    lead["website"] = _normalize_website_url(found_site)
                    known_website = lead["website"]
                    for field in ("https", "has_viewport", "html_length", "has_cta"):
                        if inspected.get(field) is not None:
                            lead[field] = inspected[field]
                if inspected.get("phones") and not lead_has_valid_phone(lead):
                    lead["phone_website"] = ";".join(inspected["phones"])
                accepted = _pick_accepted_email(
                    inspected.get("emails") or [],
                    lead,
                    page_url=inspected.get("page_url") or found_site,
                    page_text=inspected.get("page_text") or "",
                    website=lead.get("website") or found_site,
                )
                if accepted:
                    _apply_email(
                        lead,
                        accepted[0],
                        SOURCE_GOOGLE,
                        accepted[1],
                        website=lead.get("website") or found_site,
                        phones=inspected.get("phones"),
                        analysis=inspected,
                    )
                    session.cache[key] = dict(lead)
                    return lead

        if not lead_has_valid_email(lead):
            logger.info("[EMAIL] No reliable email found")
        session.cache[key] = dict(lead)
        return lead
    except Exception as exc:
        logger.error("[EMAIL] Enrichment failed for %s: %s", name, exc)
        return lead
    finally:
        if own_session:
            session.close()


def _pick_accepted_email(emails, lead, page_url=None, page_text="", website=None):
    ranked = []
    for email in emails:
        confidence = score_email_confidence(
            email,
            lead,
            page_url=page_url,
            page_text=page_text,
            website=website,
        )
        if _accept_confidence(confidence):
            ranked.append((email, confidence))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (0 if item[1] == CONFIDENCE_HIGH else 1, _email_rank(item[0], website)))
    return ranked[0]
