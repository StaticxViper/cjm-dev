#!/usr/bin/env python3
"""Discovery sources for crm_enrich.

Maps listings come from BusinessDiscoverySession (Playwright). Emails come
only from pages of the matched website via the existing validators. This
module does not request Google web search result pages.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse
import re

from bs4 import BeautifulSoup

from crm_enrich_match import (
    display_name,
    name_prefilter_pass,
    normalize_match_name,
)
from crm_enrich_robots import robots_allowed
from email_discovery import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONTACT_PAGE_PATHS,
    _domains_match,
    _host_from_url,
    extract_emails_from_html,
    inspect_website,
    is_valid_us_phone,
    score_email_confidence,
    validate_email,
)
from leadenrich import name_similarity
from leadenrich_playwright import visit_website
from website_quality import (
    analyze_website_quality,
    is_social_or_directory_url,
    normalize_website_url,
    website_label,
)
from email_discovery import is_directory_host

# Legacy Places API list prices (USD per 1,000). Confirm the SKUs on the key
# before a live run; Google changes these. Find Place + Place Details.
FIND_PLACE_USD_PER_1000 = 17.0
PLACE_DETAILS_USD_PER_1000 = 17.0
FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"

_OWNER_TITLES = ("founder", "owner", "co-founder", "cofounder", "principal", "proprietor")


def estimate_places_cost(lead_count):
    """Worst-case legacy Places spend: one Find Place and up to two Details each."""
    leads = max(0, int(lead_count or 0))
    find_calls = leads
    detail_calls = leads * 2
    usd = (
        find_calls * FIND_PLACE_USD_PER_1000
        + detail_calls * PLACE_DETAILS_USD_PER_1000
    ) / 1000.0
    return {
        "find_place_calls": find_calls,
        "details_calls": detail_calls,
        "find_place_usd_per_1000": FIND_PLACE_USD_PER_1000,
        "details_usd_per_1000": PLACE_DETAILS_USD_PER_1000,
        "estimated_usd": round(usd, 2),
    }


def format_places_cost(estimate):
    return (
        "places_api estimate (legacy Find Place + Place Details, confirm in Cloud Console): "
        f"{estimate['find_place_calls']} Find Place x ${estimate['find_place_usd_per_1000']:.0f}/1000 + "
        f"{estimate['details_calls']} Place Details x ${estimate['details_usd_per_1000']:.0f}/1000 "
        f"= about ${estimate['estimated_usd']:.2f}"
    )


class MapsPlaywrightSource:
    """One Maps browser session. Stops itself on a block page or the search cap."""

    def __init__(self, session, counter, max_searches):
        self.session = session
        self.counter = counter
        self.max_searches = max_searches
        self.blocked = False
        self.status = "ok"

    def _blocked_now(self):
        if self.blocked or getattr(self.session, "google_blocked", False):
            self.blocked = True
            self.status = "blocked"
            return True
        return False

    def listings_for(self, lead, queries, city, state):
        if self._blocked_now():
            return [], "blocked"
        if not queries:
            return [], "ok"
        if self.counter["searches"] >= self.max_searches:
            self.status = "cap"
            return [], "cap"
        keyword = display_name((lead or {}).get("business_name")) or (lead or {}).get("business_name") or ""
        listings = self._search(keyword, city, state, queries[0])
        if self._blocked_now():
            return [], "blocked"
        if not listings and len(queries) > 1 and self.counter["searches"] < self.max_searches:
            listings = self._search(keyword, city, state, queries[1])
            if self._blocked_now():
                return list(listings or []), "blocked"
        merged = self._enrich_top(lead, list(listings or []))
        if self._blocked_now():
            return merged, "blocked"
        self.status = "ok"
        return merged, "ok"

    def _search(self, keyword, city, state, query):
        self.counter["searches"] += 1
        return self.session.search_listings(
            keyword,
            city or "",
            state or "",
            max_pages=1,
            max_results=5,
            query=query,
        )

    def _enrich_top(self, lead, listings):
        passing = [item for item in listings if name_prefilter_pass(lead, item)]
        lead_norm = normalize_match_name((lead or {}).get("business_name"))
        passing.sort(
            key=lambda item: name_similarity(
                lead_norm,
                normalize_match_name(item.get("business_name") or item.get("name")),
            ),
            reverse=True,
        )
        chosen = {id(item) for item in passing[:2]}
        merged = []
        for item in listings:
            if id(item) not in chosen or self._blocked_now():
                merged.append(item)
                continue
            detail = self.session.enrich_listing(item)
            merged.append(detail or item)
        return merged


def _as_listing(item):
    return {
        "business_name": item.get("business_name") or item.get("name"),
        "place_id": item.get("place_id"),
        "address": item.get("address") or item.get("formatted_address"),
        "business_status": item.get("business_status"),
        "phone": item.get("phone") or item.get("phone_google"),
        "website": item.get("website"),
        "rating": item.get("rating"),
        "user_ratings_total": item.get("user_ratings_total"),
        "category": item.get("category"),
        "profile_url": item.get("profile_url"),
    }


class PlacesApiSource:
    """Official Places API. Opt-in. Never required, and never a first-result pick."""

    def __init__(self, api_key, counter, max_searches, find_fn=None, details_fn=None):
        self.api_key = api_key
        self.counter = counter
        self.max_searches = max_searches
        self.find_fn = find_fn or find_places
        self.details_fn = details_fn or _default_details
        self.status = "ok"
        self.blocked = False

    def listings_for(self, lead, queries, city, state):
        del city, state
        if not queries:
            return [], "ok"
        if self.counter["searches"] >= self.max_searches:
            self.status = "cap"
            return [], "cap"
        try:
            found = self.find_fn(queries[0], self.api_key) or []
        except Exception as exc:
            self.status = "error"
            raise exc
        self.counter["searches"] += 1
        listings = [_as_listing(item) for item in found]
        if not listings and len(queries) > 1 and self.counter["searches"] < self.max_searches:
            try:
                found = self.find_fn(queries[1], self.api_key) or []
            except Exception as exc:
                self.status = "error"
                raise exc
            self.counter["searches"] += 1
            listings = [_as_listing(item) for item in found]
        passing = [item for item in listings if name_prefilter_pass(lead, item)]
        lead_norm = normalize_match_name((lead or {}).get("business_name"))
        passing.sort(
            key=lambda item: name_similarity(
                lead_norm,
                normalize_match_name(item.get("business_name")),
            ),
            reverse=True,
        )
        enriched_ids = {id(item) for item in passing[:2]}
        merged = []
        for item in listings:
            if id(item) not in enriched_ids or not item.get("place_id"):
                merged.append(item)
                continue
            if self.counter["searches"] >= self.max_searches:
                merged.append(item)
                continue
            details = self.details_fn(item["place_id"], self.api_key) or {}
            self.counter["searches"] += 1
            merged.append(_as_listing({**item, **_details_to_listing(details)}))
        self.status = "ok"
        return merged, "ok"


def _details_to_listing(details):
    return {
        "phone": details.get("phone_google") or details.get("phone"),
        "website": details.get("website"),
        "address": details.get("address"),
        "business_status": details.get("business_status"),
        "rating": details.get("rating"),
        "user_ratings_total": details.get("user_ratings_total"),
        "business_name": details.get("business_name") or details.get("name"),
        "category": details.get("category"),
    }


def _default_details(place_id, api_key):
    from leadgen import get_place_details
    return get_place_details(place_id, api_key)


def find_places(query, api_key, get_fn=None):
    """Return every Find Place candidate. Callers score them; index 0 is not special."""
    import requests

    getter = get_fn or requests.get
    response = getter(
        FIND_PLACE_URL,
        params={
            "input": query,
            "inputtype": "textquery",
            "fields": "place_id,name,formatted_address,business_status",
            "key": api_key,
        },
        timeout=15,
    )
    data = response.json()
    status = data.get("status")
    if status not in (None, "OK", "ZERO_RESULTS"):
        raise RuntimeError(f"Find Place status {status}")
    listings = []
    for item in data.get("candidates") or []:
        listings.append({
            "business_name": item.get("name"),
            "place_id": item.get("place_id"),
            "address": item.get("formatted_address"),
            "business_status": item.get("business_status"),
        })
    return listings


def _origin(url):
    raw = url if "://" in (url or "") else f"https://{url}"
    parsed = urlparse(raw)
    if not parsed.netloc:
        return ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://{parsed.netloc}"


def fetch_robots_txt(url, get_fn):
    origin = _origin(url)
    if not origin or get_fn is None:
        return ""
    try:
        response = get_fn(origin + "/robots.txt", timeout=10)
    except TypeError:
        try:
            response = get_fn(origin + "/robots.txt")
        except Exception:
            return ""
    except Exception:
        return ""
    status = getattr(response, "status_code", 200) or 200
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = 200
    if status >= 400:
        return ""
    return getattr(response, "text", "") or ""


def _path_allowed(robots_txt, url):
    if not robots_txt:
        return True
    return robots_allowed(robots_txt, url)


def website_is_rejected(url):
    if not url:
        return True
    return is_directory_host(url) or is_social_or_directory_url(url)


def _page_text(html):
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _accept_email(email, lead, website, page_url, page_text):
    valid = validate_email(email)
    if not valid:
        return None
    confidence = score_email_confidence(
        valid,
        lead,
        page_url=page_url,
        page_text=page_text,
        website=website,
    )
    domain = valid.rsplit("@", 1)[-1]
    domain_ok = _domains_match(domain, _host_from_url(website))
    if confidence == CONFIDENCE_HIGH:
        return valid, "high"
    if confidence == CONFIDENCE_MEDIUM and domain_ok:
        return valid, "medium"
    return None


def _split_person(name):
    parts = [part for part in re.split(r"\s+", (name or "").strip()) if part]
    if len(parts) < 2:
        return None
    return parts[0], " ".join(parts[1:])


def _person_title_ok(node):
    title = node.get("jobTitle") or node.get("roleName") or ""
    if isinstance(title, list):
        title = " ".join(str(item) for item in title)
    title = str(title).lower()
    return any(word in title for word in _OWNER_TITLES)


def _walk_people(node, found):
    if isinstance(node, list):
        for item in node:
            _walk_people(item, found)
        return
    if not isinstance(node, dict):
        return
    types = node.get("@type") or ""
    if isinstance(types, list):
        types = " ".join(str(item) for item in types)
    types = str(types).lower()
    if "person" in types and _person_title_ok(node):
        name = node.get("name")
        if isinstance(name, str):
            found.append(name)
    founder = node.get("founder")
    if isinstance(founder, dict):
        name = founder.get("name")
        if isinstance(name, str):
            found.append(name)
    elif isinstance(founder, list):
        for item in founder:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                found.append(item["name"])
    for value in node.values():
        if isinstance(value, (dict, list)):
            _walk_people(value, found)


def extract_contact_name(html):
    """First/last name from explicit JSON-LD Person data. Never guessed."""
    if not html:
        return None
    import json
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for script in soup.find_all("script", attrs={"type": lambda value: value and "ld+json" in value.lower()}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        _walk_people(data, found)
    for name in found:
        split = _split_person(name)
        if split:
            return {"contact_first_name": split[0], "contact_last_name": split[1]}
    return None


def quality_label(url, html):
    if not url or not html:
        return None
    try:
        cheap = {
            "url": normalize_website_url(url),
            "reachable": True,
            "https": str(url).lower().startswith("https"),
        }
        analysis = analyze_website_quality(url, html=html, cheap=cheap)
    except Exception:
        return None
    score = analysis.get("website_quality_score")
    if score is None:
        return None
    return website_label(score)


def collect_website(url, lead, session=None, get_fn=None, visit_fn=None):
    """Visit the matched site only. Returns emails, phones, html, and a status."""
    if website_is_rejected(url):
        return {"status": "skipped", "emails": [], "html": "", "page_url": url, "quality": None}
    robots_txt = fetch_robots_txt(url, get_fn) if get_fn is not None else ""
    home = normalize_website_url(url)
    if not _path_allowed(robots_txt, home):
        return {"status": "robots_disallowed", "emails": [], "html": "", "page_url": home, "quality": None}
    parsed = urlparse(home)
    base = f"{parsed.scheme}://{parsed.netloc}"
    contact_ok = all(
        _path_allowed(robots_txt, urljoin(base + "/", path.lstrip("/")))
        for path in CONTACT_PAGE_PATHS
    )
    visitor = visit_fn or visit_website
    html = ""
    emails = []
    page_url = home
    if contact_ok:
        visited = visitor(session, home)
        html = (visited or {}).get("html") or ""
        emails = list((visited or {}).get("emails") or [])
        page_url = (visited or {}).get("final_url") or (visited or {}).get("url") or home
        if not emails and html:
            emails = extract_emails_from_html(html, website=home)
    else:
        inspected = inspect_website(home, max_pages=1)
        emails = list(inspected.get("emails") or [])
        page_url = inspected.get("page_url") or home
    if not emails and html:
        emails = extract_emails_from_html(html, website=home)
    page_text = _page_text(html)
    accepted = []
    probe = dict(lead or {})
    probe["website"] = home
    for email in emails:
        picked = _accept_email(email, probe, home, page_url, page_text or page_url)
        if picked:
            accepted.append(picked)
    contact = extract_contact_name(html)
    return {
        "status": "ok",
        "emails": accepted,
        "html": html,
        "page_url": page_url,
        "quality": quality_label(home, html),
        "contact": contact,
        "phones": [],
    }


def email_confidence_value(level, match_score):
    if level == "high":
        return int(match_score)
    if level == "medium":
        return max(0, int(match_score) - 10)
    return 0


def usable_phone(phone):
    return phone if is_valid_us_phone(phone) else None
