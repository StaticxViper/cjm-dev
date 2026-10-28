#!/usr/bin/env python3
"""Search criteria, Zillow URL building, HTML parsers, and dedupe keys.

No browser and no network. Listing pages are read from HTML fixtures in tests
and from Playwright responses in the pipeline.
"""
from __future__ import annotations

from pathlib import Path
import sys

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[1]
_SCRIPTS = _SCRIPT_DIR.parent
_LEAD = _SCRIPTS / "lead_automation"
for _entry in (_REPO_ROOT, _SCRIPTS, _LEAD):
    _text = str(_entry)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from html import unescape
from urllib.parse import quote
import hashlib
import json
import re

from bs4 import BeautifulSoup

from crm_enrich_match import normalize_match_name
from email_discovery import is_valid_us_phone, validate_email


HOME_TYPE_KEYS = {
    "house": "sf",
    "single_family": "sf",
    "singlefamily": "sf",
    "sf": "sf",
    "condo": "con",
    "condominium": "con",
    "con": "con",
    "townhouse": "tow",
    "townhome": "tow",
    "tow": "tow",
    "multi": "mf",
    "multi_family": "mf",
    "multifamily": "mf",
    "mf": "mf",
    "manufactured": "manu",
    "mobile": "manu",
    "manu": "manu",
    "land": "land",
    "lot": "land",
    "apartment": "apa",
    "apa": "apa",
}
ALL_HOME_TYPE_KEYS = ("sf", "mf", "manu", "tow", "con", "land", "apa")

BOOL_FLAGS = (
    ("forSaleByAgent", True),
    ("forSaleByOwner", False),
    ("forRent", False),
    ("sold", False),
)
INT_FIELDS = ("priceMin", "priceMax", "bedsMin", "bathsMin", "resultsLimit")

AGENT_CSV_FIELDS = (
    "agent_name",
    "brokerage",
    "phone",
    "email",
    "license",
    "profile_url",
    "enrichment_source",
    "enrichment_source_url",
    "confidence",
    "listing_addresses",
    "listing_ids",
)
LISTING_CSV_FIELDS = (
    "listing_id",
    "address",
    "price",
    "status",
    "beds",
    "baths",
    "sqft",
    "url",
    "agent_name",
    "brokerage",
    "phone",
    "email",
    "license",
    "profile_url",
    "area",
)

_NEXT_DATA_RE = re.compile(
    r"<script[^>]*id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
    re.I | re.S,
)
_LD_JSON_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.I | re.S,
)
_ZPID_RE = re.compile(r"(\d+)_zpid", re.I)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_BEDS_RE = re.compile(r"(\d+(?:\.\d+)?)\s+beds?\b", re.I)
_BATHS_RE = re.compile(r"(\d+(?:\.\d+)?)\s+baths?\b", re.I)
_SQFT_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s+(?:sq\.?\s*ft|sqft)\b", re.I)
_LICENSE_RE = re.compile(r"\blicen[sc]e\s*#?\s*[:.]?\s*([A-Z0-9-]{4,})", re.I)


def _as_bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _optional_int(data, key):
    if key not in data or data[key] is None or data[key] == "":
        return None
    try:
        return int(data[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer.") from exc


def _string_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,;\n]+", value) if any(mark in value for mark in ",;\n") else [value]
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        raise ValueError("Expected a string or list of strings.")
    cleaned = []
    for item in parts:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def normalize_criteria(data):
    """Validate search input. Zip codes or areas are required."""
    if not isinstance(data, dict):
        raise ValueError("Search input must be a JSON object.")
    out = {}
    try:
        out["zipCodes"] = _string_list(data.get("zipCodes"))
        out["areas"] = _string_list(data.get("areas"))
    except ValueError as exc:
        raise ValueError("zipCodes and areas must be strings or lists.") from exc
    if not out["zipCodes"] and not out["areas"]:
        raise ValueError("zipCodes or areas is required.")
    for key in INT_FIELDS:
        value = _optional_int(data, key)
        if value is not None:
            out[key] = value
    if "resultsLimit" not in out:
        out["resultsLimit"] = 100
    if data.get("daysOnZillow") not in (None, ""):
        out["daysOnZillow"] = str(data["daysOnZillow"]).strip()
    for key, default in BOOL_FLAGS:
        out[key] = _as_bool(data.get(key), default) if key in data else default
    try:
        out["homeTypes"] = _string_list(data.get("homeTypes"))
    except ValueError as exc:
        raise ValueError("homeTypes must be a string or list.") from exc
    return out


def search_areas(criteria):
    """Zip codes first, then city, county, and other area strings."""
    return list(criteria.get("zipCodes") or []) + list(criteria.get("areas") or [])


def criteria_hash(criteria):
    payload = json.dumps(criteria, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _home_type_key(value):
    token = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return HOME_TYPE_KEYS.get(token)


def build_filter_state(criteria):
    """Zillow searchQueryState.filterState. False excludes a category."""
    state = {"sort": {"value": "globalrelevanceex"}}
    price = {}
    if criteria.get("priceMin") is not None:
        price["min"] = criteria["priceMin"]
    if criteria.get("priceMax") is not None:
        price["max"] = criteria["priceMax"]
    if price:
        state["price"] = price
    if criteria.get("bedsMin") is not None:
        state["beds"] = {"min": criteria["bedsMin"]}
    if criteria.get("bathsMin") is not None:
        state["baths"] = {"min": criteria["bathsMin"]}
    if criteria.get("daysOnZillow"):
        state["doz"] = {"value": str(criteria["daysOnZillow"])}
    state["fsba"] = {"value": bool(criteria.get("forSaleByAgent"))}
    state["fsbo"] = {"value": bool(criteria.get("forSaleByOwner"))}
    state["fr"] = {"value": bool(criteria.get("forRent"))}
    state["rs"] = {"value": bool(criteria.get("sold"))}
    wanted = set()
    for item in criteria.get("homeTypes") or []:
        key = _home_type_key(item)
        if key:
            wanted.add(key)
    if wanted:
        for key in ALL_HOME_TYPE_KEYS:
            if key not in wanted:
                state[key] = {"value": False}
    return state


def build_search_url(area, criteria, page=1):
    """List URL for one area and page. Page 1 omits the pagination object."""
    term = str(area).strip()
    state = {
        "usersSearchTerm": term,
        "filterState": build_filter_state(criteria),
        "isMapVisible": False,
        "isListVisible": True,
    }
    page_num = int(page or 1)
    if page_num > 1:
        state["pagination"] = {"currentPage": page_num}
    encoded = quote(json.dumps(state, separators=(",", ":")), safe="")
    if re.fullmatch(r"\d{5}", term):
        path = f"/homes/{term}_rb/"
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-") or "homes"
        path = f"/{slug}/"
    return f"https://www.zillow.com{path}?searchQueryState={encoded}"


def slugify(value):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "area"


def area_file_slug(areas):
    """One area, first_last for up to three, otherwise a count."""
    slugs = [slugify(area) for area in areas]
    if not slugs:
        return "area"
    if len(slugs) == 1:
        return slugs[0]
    if len(slugs) <= 3:
        return f"{slugs[0]}_{slugs[-1]}"
    return f"{len(slugs)}areas"


def output_stems(run_date, areas):
    slug = area_file_slug(areas)
    return (
        f"zillow_agents_{run_date}_{slug}",
        f"zillow_listings_{run_date}_{slug}",
    )


def output_paths(output_dir, run_date, areas):
    agents, listings = output_stems(run_date, areas)
    base = Path(output_dir)
    return {
        "agents_json": base / f"{agents}.json",
        "agents_csv": base / f"{agents}.csv",
        "listings_json": base / f"{listings}.json",
        "listings_csv": base / f"{listings}.csv",
    }


def normalize_address(address):
    text = (address or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def listing_id_from_url(url):
    if not url:
        return ""
    match = _ZPID_RE.search(str(url))
    return match.group(1) if match else ""


def agent_key(record):
    """Normalized agent name plus brokerage. Blank when the name is missing."""
    name = normalize_match_name((record or {}).get("agent_name") or (record or {}).get("name") or "")
    brokerage = normalize_match_name((record or {}).get("brokerage") or "")
    if not name:
        return ""
    return f"{name}|{brokerage}"


def absolute_zillow_url(url):
    if not url:
        return ""
    text = unescape(str(url).strip())
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = "https://www.zillow.com" + text
    return text.split("#", 1)[0]


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _json_blobs(html):
    blobs = []
    for pattern in (_NEXT_DATA_RE, _LD_JSON_RE):
        for match in pattern.finditer(html or ""):
            raw = (match.group(1) or "").strip()
            if not raw:
                continue
            try:
                blobs.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return blobs


def _format_address(value):
    if isinstance(value, str):
        return " ".join(value.split())
    if not isinstance(value, dict):
        return ""
    street = value.get("streetAddress") or value.get("street") or ""
    city = value.get("city") or ""
    state = value.get("state") or ""
    zip_code = str(value.get("zipcode") or value.get("zipCode") or value.get("postalCode") or value.get("zip") or "")
    locality = ""
    if city and state:
        locality = f"{city}, {state} {zip_code}".strip()
    elif city or state or zip_code:
        locality = " ".join(part for part in (city, state, zip_code) if part)
    parts = [str(part).strip() for part in (street, locality) if str(part).strip()]
    return ", ".join(parts)


def _parse_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
        if not match:
            return None
        number = float(match.group(0))
    if number.is_integer():
        return int(number)
    return number


def _parse_price(value):
    number = _parse_number(value)
    if number is None:
        return None
    return int(number)


def _clean_phone(value):
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if not text:
        return ""
    if is_valid_us_phone(text):
        digits = re.sub(r"\D", "", text)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    return ""


def _first(obj, keys):
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        value = obj.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _blank_listing(url=""):
    return {
        "listing_id": listing_id_from_url(url),
        "url": absolute_zillow_url(url).split("?", 1)[0] if url else "",
        "address": "",
        "price": None,
        "status": "",
        "beds": None,
        "baths": None,
        "sqft": None,
        "agent_name": "",
        "brokerage": "",
        "phone": "",
        "email": "",
        "license": "",
        "profile_url": "",
        "area": "",
    }


def _apply_attribution(listing, attr):
    if not isinstance(attr, dict):
        return
    if not listing["agent_name"]:
        listing["agent_name"] = _first(attr, ("agentName", "name"))
    if not listing["brokerage"]:
        listing["brokerage"] = _first(attr, ("brokerName", "brokerageName", "broker"))
    if not listing["phone"]:
        listing["phone"] = _clean_phone(_first(attr, ("agentPhoneNumber", "phoneNumber", "phone")))
    if not listing["email"]:
        listing["email"] = validate_email(_first(attr, ("agentEmail", "email")))
    if not listing["license"]:
        listing["license"] = _first(attr, ("agentLicenseNumber", "licenseNumber", "license"))
    if not listing["profile_url"]:
        profile = _first(attr, ("profileUrl", "agentProfileUrl"))
        if profile:
            listing["profile_url"] = absolute_zillow_url(profile)


def _apply_listing_object(listing, obj):
    zpid = str(obj.get("zpid") or obj.get("listingId") or "").split(".")[0]
    if zpid.isdigit() and not listing["listing_id"]:
        listing["listing_id"] = zpid
    address = _format_address(obj.get("address") or obj.get("streetAddress"))
    if address and not listing["address"]:
        listing["address"] = address
    if listing["price"] is None:
        listing["price"] = _parse_price(obj.get("price") if obj.get("price") is not None else obj.get("unformattedPrice"))
    if listing["beds"] is None and obj.get("beds") is not None:
        listing["beds"] = _parse_number(obj.get("beds"))
    if listing["baths"] is None and obj.get("baths") is not None:
        listing["baths"] = _parse_number(obj.get("baths"))
    if listing["sqft"] is None:
        living = obj.get("livingArea")
        if living is None:
            living = obj.get("sqft") or obj.get("livingAreaValue")
        if living is not None:
            listing["sqft"] = _parse_number(living)
    if not listing["status"]:
        status = obj.get("homeStatus") or obj.get("listingStatus") or obj.get("status")
        if status:
            listing["status"] = str(status)
    _apply_attribution(listing, obj.get("attributionInfo"))
    detail = obj.get("detailUrl") or obj.get("hdpUrl") or obj.get("url")
    if detail and not listing["url"]:
        listing["url"] = absolute_zillow_url(detail).split("?", 1)[0]
    if not listing["listing_id"]:
        listing["listing_id"] = listing_id_from_url(listing["url"])


def _listing_score(obj, zpid):
    if not isinstance(obj, dict):
        return -1
    score = 0
    obj_zpid = str(obj.get("zpid") or "").split(".")[0]
    if zpid and obj_zpid == zpid:
        score += 5
    if _format_address(obj.get("address") or obj.get("streetAddress")):
        score += 3
    if obj.get("price") is not None or obj.get("unformattedPrice") is not None:
        score += 2
    if obj.get("beds") is not None:
        score += 1
    if isinstance(obj.get("attributionInfo"), dict):
        score += 3
    return score


def _fill_from_html(listing, html):
    soup = BeautifulSoup(html or "", "html.parser")
    if not listing["address"]:
        heading = soup.find("h1")
        if heading:
            listing["address"] = " ".join(heading.get_text(" ", strip=True).split())
    if listing["price"] is None:
        price_node = soup.select_one("[data-testid='price']")
        listing["price"] = _parse_price(price_node.get_text(" ", strip=True) if price_node else "")
    if not listing["status"]:
        status_node = soup.select_one("[data-testid='status']")
        if status_node:
            listing["status"] = status_node.get_text(" ", strip=True)
    agent_root = soup.select_one("[data-testid='listing-agent']") or soup
    if not listing["agent_name"]:
        node = agent_root.select_one("[data-testid='agent-name']")
        if node:
            listing["agent_name"] = node.get_text(" ", strip=True)
    if not listing["brokerage"]:
        node = agent_root.select_one("[data-testid='brokerage']")
        if node:
            listing["brokerage"] = node.get_text(" ", strip=True)
    if not listing["phone"]:
        node = agent_root.select_one("[data-testid='agent-phone']")
        listing["phone"] = _clean_phone(node.get_text(" ", strip=True) if node else "")
    if not listing["email"]:
        mailto = agent_root.select_one("a[href^='mailto:']")
        if mailto:
            listing["email"] = validate_email(mailto.get("href") or "")
    if not listing["license"]:
        node = agent_root.select_one("[data-testid='agent-license']")
        if node:
            listing["license"] = node.get_text(" ", strip=True)
    if not listing["profile_url"]:
        profile = soup.select_one("a[href*='/profile/']")
        if profile and profile.get("href"):
            listing["profile_url"] = absolute_zillow_url(profile.get("href"))
    text = soup.get_text(" ", strip=True)
    if listing["beds"] is None:
        match = _BEDS_RE.search(text)
        if match:
            listing["beds"] = _parse_number(match.group(1))
    if listing["baths"] is None:
        match = _BATHS_RE.search(text)
        if match:
            listing["baths"] = _parse_number(match.group(1))
    if listing["sqft"] is None:
        match = _SQFT_RE.search(text)
        if match:
            listing["sqft"] = _parse_number(match.group(1))
    if not listing["license"]:
        match = _LICENSE_RE.search(text)
        if match:
            listing["license"] = match.group(1)
    if not listing["phone"]:
        phone_match = re.search(r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
        if phone_match:
            listing["phone"] = _clean_phone(phone_match.group(0))
    if listing["price"] is None:
        price_match = re.search(r"\$[\d,]+", text)
        if price_match:
            listing["price"] = _parse_price(price_match.group(0))


def parse_listing_page(html, url=""):
    """Listing facts and the listing agent. Embedded JSON wins over visible text."""
    listing = _blank_listing(url)
    blobs = _json_blobs(html)
    best = None
    best_score = 2
    attributions = []
    for blob in blobs:
        for obj in _walk(blob):
            score = _listing_score(obj, listing["listing_id"])
            if score > best_score:
                best = obj
                best_score = score
            attr = obj.get("attributionInfo")
            if isinstance(attr, dict) and attr.get("agentName"):
                attributions.append(attr)
    if best is not None:
        _apply_listing_object(listing, best)
    if not listing["agent_name"]:
        for attr in attributions:
            _apply_attribution(listing, attr)
            if listing["agent_name"]:
                break
    _fill_from_html(listing, html)
    if url and not listing["url"]:
        listing["url"] = absolute_zillow_url(url).split("?", 1)[0]
    if not listing["listing_id"]:
        listing["listing_id"] = listing_id_from_url(listing["url"] or url)
    return listing


def _card_url(obj):
    if not isinstance(obj, dict):
        return ""
    for key in ("detailUrl", "hdpUrl", "propertyUrl", "url"):
        value = obj.get(key)
        if not isinstance(value, str):
            continue
        if "homedetails" in value and "_zpid" in value.lower():
            return absolute_zillow_url(value).split("?", 1)[0]
    return ""


def _html_listing_urls(html):
    found = []
    seen = set()
    for match in _HREF_RE.finditer(html or ""):
        href = unescape(match.group(1))
        if "homedetails" not in href or "_zpid" not in href.lower():
            continue
        url = absolute_zillow_url(href).split("?", 1)[0]
        zpid = listing_id_from_url(url)
        if not zpid or zpid in seen:
            continue
        seen.add(zpid)
        found.append({"listing_id": zpid, "url": url})
    return found


def _html_has_next(html):
    text = html or ""
    if re.search(r"rel=[\"']next[\"']", text, re.I):
        return True
    if re.search(r"aria-label=[\"']next page[\"']", text, re.I):
        return True
    return False


def parse_search_page(html):
    """Listing URLs from one search page, plus whether another page exists."""
    listings = []
    seen = set()
    has_next = False
    saw_next = False
    blobs = _json_blobs(html)
    for blob in blobs:
        for obj in _walk(blob):
            if "hasNextPage" in obj and isinstance(obj.get("hasNextPage"), bool):
                has_next = obj["hasNextPage"]
                saw_next = True
            if "currentPage" in obj and "totalPages" in obj:
                try:
                    has_next = int(obj["currentPage"]) < int(obj["totalPages"])
                    saw_next = True
                except (TypeError, ValueError):
                    pass
            url = _card_url(obj)
            if not url:
                continue
            zpid = listing_id_from_url(url) or str(obj.get("zpid") or "").split(".")[0]
            if not zpid or zpid in seen:
                continue
            seen.add(zpid)
            listings.append({"listing_id": zpid, "url": url})
    if not listings:
        for item in _html_listing_urls(html):
            if item["listing_id"] in seen:
                continue
            seen.add(item["listing_id"])
            listings.append(item)
    if not saw_next:
        has_next = _html_has_next(html)
    return {"listings": listings, "has_next": has_next}


def _blank_agent(listing):
    return {
        "agent_name": listing.get("agent_name") or "",
        "brokerage": listing.get("brokerage") or "",
        "phone": listing.get("phone") or "",
        "email": listing.get("email") or "",
        "license": listing.get("license") or "",
        "profile_url": listing.get("profile_url") or "",
        "enrichment_source": "",
        "enrichment_source_url": "",
        "confidence": "",
        "listing_ids": [],
        "listing_addresses": [],
        "area": listing.get("area") or "",
    }


def _fill_blank(dest, source, fields):
    for field in fields:
        if not str(dest.get(field) or "").strip() and str(source.get(field) or "").strip():
            dest[field] = source[field]


class Collection:
    """Listings and agents for one run. Dedupe by zpid, then normalized address."""

    def __init__(self):
        self.listings = []
        self.agents = []
        self._ids = set()
        self._addresses = set()
        self._agent_index = {}

    def known(self, listing_id="", address=""):
        if listing_id and str(listing_id) in self._ids:
            return True
        address_key = normalize_address(address)
        return bool(address_key and address_key in self._addresses)

    def add(self, listing):
        listing_id = str(listing.get("listing_id") or "").strip()
        address_key = normalize_address(listing.get("address"))
        if listing_id and listing_id in self._ids:
            return "duplicate"
        if address_key and address_key in self._addresses:
            return "duplicate"
        stored = dict(listing)
        self.listings.append(stored)
        if listing_id:
            self._ids.add(listing_id)
        if address_key:
            self._addresses.add(address_key)
        self._attach_agent(stored)
        return "added"

    def _attach_agent(self, listing):
        key = agent_key(listing)
        if not key:
            return
        index = self._agent_index.get(key)
        if index is None:
            agent = _blank_agent(listing)
            if listing.get("listing_id"):
                agent["listing_ids"].append(str(listing["listing_id"]))
            address = (listing.get("address") or "").strip()
            if address:
                agent["listing_addresses"].append(address)
            self._agent_index[key] = len(self.agents)
            self.agents.append(agent)
            return
        agent = self.agents[index]
        _fill_blank(
            agent,
            listing,
            ("agent_name", "brokerage", "phone", "email", "license", "profile_url", "area"),
        )
        listing_id = str(listing.get("listing_id") or "")
        if listing_id and listing_id not in agent["listing_ids"]:
            agent["listing_ids"].append(listing_id)
        address = (listing.get("address") or "").strip()
        if address and address not in agent["listing_addresses"]:
            agent["listing_addresses"].append(address)

    def load(self, payload):
        self.listings = []
        self.agents = []
        self._ids = set()
        self._addresses = set()
        self._agent_index = {}
        for listing in (payload or {}).get("listings") or []:
            if isinstance(listing, dict):
                self.add(listing)
        saved_agents = [
            dict(agent)
            for agent in ((payload or {}).get("agents") or [])
            if isinstance(agent, dict)
        ]
        if not saved_agents:
            return
        by_key = {}
        for agent in saved_agents:
            key = agent_key(agent)
            if key:
                by_key[key] = agent
        for index, agent in enumerate(self.agents):
            saved = by_key.get(agent_key(agent))
            if not saved:
                continue
            _fill_blank(
                agent,
                saved,
                (
                    "phone",
                    "email",
                    "license",
                    "profile_url",
                    "enrichment_source",
                    "enrichment_source_url",
                    "area",
                ),
            )
            if saved.get("confidence") not in (None, ""):
                agent["confidence"] = saved["confidence"]
            self.agents[index] = agent


def agent_csv_row(agent):
    row = {}
    for field in AGENT_CSV_FIELDS:
        value = agent.get(field, "")
        if field == "listing_addresses":
            value = "; ".join(agent.get("listing_addresses") or [])
        elif field == "listing_ids":
            value = "; ".join(str(item) for item in (agent.get("listing_ids") or []))
        if value is None:
            value = ""
        row[field] = value
    return row


def listing_csv_row(listing):
    row = {}
    for field in LISTING_CSV_FIELDS:
        value = listing.get(field, "")
        if value is None:
            value = ""
        row[field] = value
    return row
