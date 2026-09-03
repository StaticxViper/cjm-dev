#!/usr/bin/env python3
"""
leadgen.py

Local Business Lead Generation System

Run: python leadgen.py
"""
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import argparse
import requests
import re
import shutil
import time
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from helper_scripts.utils.logger.logger import setup_logger
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
import os
from dotenv import load_dotenv
from leadfilter import load_existing_place_ids, is_new_place
from email_discovery import (
    EmailDiscoverySession,
    enrich_lead_with_email,
    extract_emails_from_html,
    lead_emails,
    lead_has_valid_email,
    lead_has_valid_phone,
    validate_email,
)

load_dotenv()

# -----------------------------
# Configurable constants
# -----------------------------
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PLACES_SLEEP = 2  # seconds between place detail / next_page_token attempts
CONTACTED_FILE = "contacted.txt"
DASHBOARD_BASE_URL = "https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1"
DASHBOARD_BULK_ENDPOINT = "/leads-ingest-bulk"

_LEADGEN_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = _LEADGEN_DIR / "leadgen_settings.json"
KEYWORD_CATEGORIES = json.load(open(_LEADGEN_DIR / "keywords.json"))
COORDS_DATA = json.load(open(_LEADGEN_DIR / "coords.json"))
FRANCHISE_DATA = json.load(open(_LEADGEN_DIR / "franchises.json"))
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
MIN_USEFUL_HTML_LENGTH = 200
VALID_OBJECTIVES = ("phone", "email", "either", "both")
PERSISTED_SETTINGS_KEYS = (
    "min_score",
    "min_reviews",
    "filter_franchises",
    "objective",
    "require_website",
    "lead_enrichment",
    "output_mode",
    "json_output",
)

SCORE_WEIGHTS = {
    "no_website": 40,
    "no_https": 18,
    "no_viewport": 14,
    "short_html": 14,
    "no_cta": 4,
    "has_email": 6,
    "low_rating": 1,
    "low_reviews": 1,
    "unknown_status": 2,
}
assert sum(SCORE_WEIGHTS.values()) == 100

REVIEW_MAX_AGE_MONTHS = 18
US_PHONE_RE = re.compile(r"^(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$")
CLOSED_STATUSES = frozenset({"CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"})
OWNER_NAME_FALSE_POSITIVES = frozenset({
    "he", "she", "they", "him", "her", "them", "his", "very", "really", "also",
    "just", "still", "always", "never", "everyone", "someone", "anyone",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "service", "company", "business", "team", "staff", "crew", "guy", "guys",
    "lady", "man", "woman", "people", "customer", "customers",
    "next", "time", "owner", "manager", "was", "is", "great", "amazing",
    "excellent", "wonderful", "helpful", "fantastic", "the", "our", "my",
})
OWNER_NAME_PATTERNS = [
    re.compile(
        r"(?i)(?:ask for|talk to|speak (?:with|to)|call|meet)\s+([A-Z][a-z]+)"
    ),
    re.compile(
        r"([A-Z][a-z]+)\s+(?i:was|is)\s+(?i:great|amazing|excellent|wonderful|helpful|fantastic)"
    ),
    re.compile(r"(?i)(?:owner|manager)\s+([A-Z][a-z]+)"),
    re.compile(r"([A-Z][a-z]+)\s+(?i:the\s+)?(?i:owner|manager)"),
]

logger = setup_logger(
    name="leadgen",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)


def _default_keywords():
    return list(KEYWORD_CATEGORIES.keys())


def _default_locations():
    locations = []
    for state, cities in COORDS_DATA.items():
        for city, coords in cities.items():
            locations.append((state, city, coords))
    return locations


@dataclass
class LeadgenConfig:
    min_score: int = 55
    output_mode: str = "json"
    json_output: str = "leads_output.json"
    search_radius: int = 50000
    max_workers: int = 12
    keywords: list = field(default_factory=_default_keywords)
    locations: list = field(default_factory=_default_locations)
    dashboard_bulk: bool = True
    filter_franchises: bool = True
    min_reviews: int = 0
    objective: str = "phone"
    require_website: bool = False
    lead_enrichment: bool = True


def load_saved_settings(path=None):
    """Load persisted run defaults from leadgen_settings.json (excludes keywords/locations)."""
    settings_path = Path(path) if path is not None else SETTINGS_PATH
    if not settings_path.exists():
        return {}
    try:
        with open(settings_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to load settings from %s: %s", settings_path, e)
        return {}
    if not isinstance(data, dict):
        return {}

    # Migrate legacy CSV settings keys to JSON.
    if "output_mode" in data and data["output_mode"] == "csv":
        data["output_mode"] = "json"
    if "json_output" not in data and data.get("csv_output"):
        path_val = str(data["csv_output"])
        if path_val.lower().endswith(".csv"):
            path_val = path_val[:-4] + ".json"
        data["json_output"] = path_val

    migrated = _migrate_objective_from_settings(data)
    if migrated:
        data["objective"] = migrated

    return {k: data[k] for k in PERSISTED_SETTINGS_KEYS if k in data}


def save_settings(config, path=None):
    """Persist run defaults from a LeadgenConfig (excludes keywords/locations)."""
    settings_path = Path(path) if path is not None else SETTINGS_PATH
    payload = {
        "min_score": config.min_score,
        "min_reviews": config.min_reviews,
        "filter_franchises": config.filter_franchises,
        "objective": normalize_objective(config.objective),
        "require_website": config.require_website,
        "lead_enrichment": config.lead_enrichment,
        "output_mode": config.output_mode,
        "json_output": config.json_output,
    }
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return payload


def config_from_saved_settings(path=None):
    """Build LeadgenConfig from hardcoded defaults plus any saved settings file."""
    config = LeadgenConfig()
    saved = load_saved_settings(path=path)
    if not saved:
        return config
    if "min_score" in saved:
        try:
            config.min_score = int(saved["min_score"])
        except (TypeError, ValueError):
            pass
    if "min_reviews" in saved:
        try:
            config.min_reviews = int(saved["min_reviews"])
        except (TypeError, ValueError):
            pass
    if "filter_franchises" in saved:
        config.filter_franchises = bool(saved["filter_franchises"])
    if "objective" in saved:
        config.objective = normalize_objective(saved["objective"])
    if "require_website" in saved:
        config.require_website = bool(saved["require_website"])
    if "lead_enrichment" in saved:
        config.lead_enrichment = bool(saved["lead_enrichment"])
    if "output_mode" in saved and saved["output_mode"] in ("json", "dashboard", "both"):
        config.output_mode = saved["output_mode"]
    if "json_output" in saved and saved["json_output"]:
        config.json_output = str(saved["json_output"])
    return config


def normalize_objective(value, default="phone"):
    """Return a valid objective string, falling back to default."""
    if isinstance(value, str) and value.strip().lower() in VALID_OBJECTIVES:
        return value.strip().lower()
    return default


def objective_from_require_flags(require_phone, require_email):
    """Map legacy require_phone/require_email flags to a single objective."""
    if require_phone and require_email:
        return "both"
    if require_phone:
        return "phone"
    if require_email:
        return "email"
    return "either"


def _migrate_objective_from_settings(data):
    """Return an objective from new or legacy settings keys, or None."""
    if not isinstance(data, dict):
        return None
    if data.get("objective") in VALID_OBJECTIVES:
        return data["objective"]
    if "require_phone" in data or "require_email" in data:
        return objective_from_require_flags(
            bool(data.get("require_phone", False)),
            bool(data.get("require_email", False)),
        )
    return None


def lead_meets_objective(lead, objective):
    """Hard qualification: score cannot override a missing required contact."""
    objective = normalize_objective(objective)
    has_phone = lead_has_valid_phone(lead)
    has_email = lead_has_valid_email(lead)
    if objective == "phone":
        return has_phone
    if objective == "email":
        return has_email
    if objective == "either":
        return has_phone or has_email
    if objective == "both":
        return has_phone and has_email
    return False


def should_run_email_discovery(lead, objective):
    """True when the Google/website email workflow should run for this lead."""
    objective = normalize_objective(objective)
    if objective == "phone":
        return False
    has_email = lead_has_valid_email(lead)
    has_phone = lead_has_valid_phone(lead)
    if objective == "email":
        return not has_email
    if objective == "either":
        return not has_email and not has_phone
    if objective == "both":
        return not has_email or not has_phone
    return False


def get_places(location, radius, keywords, api_key):
    """Use Nearby Search to gather place_ids for given keywords and location."""
    base = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    places = {}
    for kw in keywords:
        logger.critical("Searching for keyword '%s' around location %s", kw, location)
        params = {
            "location": location,
            "radius": radius,
            "keyword": kw,
            "key": api_key,
        }
        url = base
        while True:
            try:
                r = requests.get(url, params=params, timeout=10)
                data = r.json()

                logger.info("HTTP Status Code: %s", r.status_code)
                logger.info("Places Status: %s", data.get("status"))
                logger.info("Error Message: %s", data.get("error_message"))
                logger.info("Results Count: %d", len(data.get("results", [])))

            except Exception as e:
                logger.error("Nearby search failed for keyword %s: %s", kw, e)
                break
            data = r.json()
            results = data.get("results", [])
            for p in results:
                pid = p.get("place_id")
                if not pid:
                    continue
                if pid in places:
                    continue
                places[pid] = {
                    "business_name": p.get("name"),
                    "place_id": pid,
                    "rating": p.get("rating"),
                    "user_ratings_total": p.get("user_ratings_total"),
                    "address": p.get("vicinity") or p.get("formatted_address"),
                    "niche_key": kw,
                }
            next_token = data.get("next_page_token")
            if next_token:
                time.sleep(PLACES_SLEEP)
                params = {"pagetoken": next_token, "key": api_key}
                continue
            break
    logger.info("Collected %d unique places", len(places))
    return list(places.values())


def get_place_details(place_id, api_key):
    """Fetch Place Details for a single place_id."""
    base = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": (
            "website,formatted_phone_number,formatted_address,name,place_id,"
            "business_status,reviews,rating,user_ratings_total"
        ),
        "reviews_sort": "newest",
        "key": api_key,
    }
    empty = {
        "website": None,
        "phone_google": None,
        "address": None,
        "business_status": None,
        "reviews": [],
        "rating": None,
        "user_ratings_total": None,
    }
    try:
        r = requests.get(base, params=params, timeout=10)
        data = r.json()
        result = data.get("result", {})
        return {
            "website": result.get("website"),
            "phone_google": result.get("formatted_phone_number"),
            "address": result.get("formatted_address"),
            "business_status": result.get("business_status"),
            "reviews": result.get("reviews") or [],
            "rating": result.get("rating"),
            "user_ratings_total": result.get("user_ratings_total"),
        }
    except Exception as e:
        logger.error("Place details failed for %s: %s", place_id, e)
        return dict(empty)


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


def latest_review_timestamp(reviews):
    """Return the newest review unix timestamp, or None if no reviews."""
    if not reviews:
        return None
    times = [r.get("time") for r in reviews if r.get("time") is not None]
    return max(times) if times else None


def is_review_stale(latest_ts, months=REVIEW_MAX_AGE_MONTHS):
    """Return True if latest review is older than the given number of months."""
    if latest_ts is None:
        return False
    latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    return latest_dt < cutoff


def is_franchise(business_name, website, franchise_data=None):
    """Return True if business name or website matches known franchise lists."""
    data = franchise_data if franchise_data is not None else FRANCHISE_DATA
    name = (business_name or "").lower()
    for franchise_name in data.get("names") or []:
        if franchise_name and franchise_name.lower() in name:
            return True

    if website:
        try:
            host = urlparse(website if "://" in website else f"http://{website}").hostname or ""
            host = host.lower().removeprefix("www.")
            for domain in data.get("domains") or []:
                domain = (domain or "").lower().removeprefix("www.")
                if domain and (host == domain or host.endswith("." + domain)):
                    return True
        except Exception:
            pass
    return False


def extract_owner_names(reviews, max_names=5):
    """Extract likely owner/decision-maker names from review text."""
    if not reviews:
        return []
    found = []
    seen = set()
    for review in reviews:
        text = review.get("text") or ""
        if not text:
            continue
        for pattern in OWNER_NAME_PATTERNS:
            for match in pattern.finditer(text):
                name = " ".join(part.capitalize() for part in match.group(1).split())
                key = name.lower()
                first = key.split()[0]
                if first in OWNER_NAME_FALSE_POSITIVES or key in seen:
                    continue
                seen.add(key)
                found.append(name)
                if len(found) >= max_names:
                    return found
    return found


def passes_quality_filters(
    entry,
    filter_franchises=True,
    min_reviews=5,
    franchise_data=None,
    require_phone=True,
    require_website=False,
):
    """Return (passed, reason) for hard quality filters before website scraping."""
    status = entry.get("business_status")
    if status in CLOSED_STATUSES:
        return False, "closed_business"

    if filter_franchises and is_franchise(
        entry.get("business_name"),
        entry.get("website"),
        franchise_data=franchise_data,
    ):
        return False, "franchise"

    try:
        count = int(entry.get("user_ratings_total") or 0)
    except (TypeError, ValueError):
        count = 0
    if count < min_reviews:
        return False, "low_review_count"

    if require_phone and not is_valid_us_phone(entry.get("phone_google")):
        return False, "invalid_phone"

    if require_website and not (entry.get("website") or "").strip():
        return False, "no_website"

    reviews = entry.get("reviews") or []
    if reviews:
        latest = latest_review_timestamp(reviews)
        if latest is not None and is_review_stale(latest):
            return False, "stale_reviews"

    return True, ""


def _extract_emails_from_html(html, soup=None):
    """Return sorted unique emails found in HTML, filtering junk and false positives."""
    return extract_emails_from_html(html, soup=soup)


def _extract_phones_from_html(html):
    """Return sorted unique US-format phones found in HTML."""
    phone_matches = re.findall(
        r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        html or "",
    )
    cleaned_phones = set()
    for p in phone_matches:
        digits = re.sub(r"[^0-9]", "", p)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            cleaned_phones.add(
                "(+1) {}-{}-{}".format(digits[0:3], digits[3:6], digits[6:10])
            )
    return sorted(cleaned_phones)


def _fetch_html(url):
    """GET url and return response text, or raise."""
    r = requests.get(url, timeout=10, headers=FETCH_HEADERS, allow_redirects=True)
    return r.text or ""


def _normalize_website_url(url):
    """Normalize scheme for scraping; prefer https for bare hosts."""
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def _https_upgrade_url(url):
    """Return an https:// variant of an http:// URL, or None if not applicable."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "http":
        return None
    return parsed._replace(scheme="https").geturl()


def analyze_website(url):
    """Fetch a website and extract emails, phones, https status, viewport, and basic quality signals.

    If the homepage has no emails, also tries common contact/about paths on the same origin.
    """
    result = {
        "emails": [],
        "phones_website": [],
        "https": False,
        "has_viewport": False,
        "html_length": 0,
        "has_title": False,
        "has_cta": False,
        "error": None,
    }
    if not url:
        return result

    url = _normalize_website_url(url)
    result["https"] = url.lower().startswith("https://")

    try:
        html = _fetch_html(url)
        if len(html) < MIN_USEFUL_HTML_LENGTH:
            https_url = _https_upgrade_url(url)
            if https_url:
                try:
                    https_html = _fetch_html(https_url)
                    if len(https_html) > len(html):
                        html = https_html
                        url = https_url
                        result["https"] = True
                except Exception:
                    pass
    except Exception as e:
        https_url = _https_upgrade_url(url)
        if https_url:
            try:
                html = _fetch_html(https_url)
                url = https_url
                result["https"] = True
            except Exception as e2:
                result["error"] = str(e2)
                return result
        else:
            result["error"] = str(e)
            return result

    result["html_length"] = len(html)
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        result["has_title"] = True

    mv = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "viewport"})
    if mv:
        result["has_viewport"] = True

    emails = set(_extract_emails_from_html(html, soup=soup))
    phones = set(_extract_phones_from_html(html))

    text = soup.get_text(separator=" ").lower()
    cta_keywords = ["call", "contact", "quote", "estimate"]
    result["has_cta"] = any(kw in text for kw in cta_keywords)

    if not emails:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in CONTACT_PAGE_PATHS:
            page_url = urljoin(base + "/", path.lstrip("/"))
            try:
                page_html = _fetch_html(page_url)
            except Exception:
                continue
            page_soup = BeautifulSoup(page_html, "html.parser")
            emails.update(_extract_emails_from_html(page_html, soup=page_soup))
            phones.update(_extract_phones_from_html(page_html))
            if emails:
                break

    result["emails"] = sorted(emails)
    result["phones_website"] = sorted(phones)
    return result


def score_lead(
    has_website,
    https,
    has_viewport,
    html_length,
    has_email,
    has_cta,
    rating,
    user_ratings_total,
    business_status=None,
):
    """Return integer lead_score 0-100 (higher = worse digital presence / better outreach target)."""
    w = SCORE_WEIGHTS
    raw = 0
    max_possible = w["low_rating"] + w["low_reviews"] + w["has_email"] + w["unknown_status"]

    if not has_website:
        max_possible += w["no_website"]
        raw += w["no_website"]
    else:
        max_possible += w["no_https"] + w["no_viewport"] + w["short_html"] + w["no_cta"]
        if not https:
            raw += w["no_https"]
        if not has_viewport:
            raw += w["no_viewport"]
        try:
            if html_length < 5000:
                raw += w["short_html"]
        except Exception:
            raw += w["short_html"]
        if not has_cta:
            raw += w["no_cta"]

    if has_email:
        raw += w["has_email"]
    if not business_status:
        raw += w["unknown_status"]

    try:
        if rating is None or float(rating) < 4.5:
            raw += w["low_rating"]
    except Exception:
        raw += w["low_rating"]
    try:
        if user_ratings_total is None or int(user_ratings_total) < 15:
            raw += w["low_reviews"]
    except Exception:
        raw += w["low_reviews"]

    if not max_possible:
        return 0
    return round(raw / max_possible * 100)


def process_businesses(
    businesses,
    api_key,
    existing_ids,
    contacted_emails,
    min_score=80,
    max_workers=12,
    filter_franchises=True,
    min_reviews=5,
    require_website=False,
    objective="phone",
    city=None,
    state=None,
):
    """Given list of basic business entries, enrich with place details and analyze websites concurrently."""
    objective = normalize_objective(objective)
    enriched = []
    quality_rejects = {}
    logger.critical("Fetching place details for %d businesses", len(businesses))
    for b in businesses:
        place_id = b.get("place_id")
        details = get_place_details(place_id, api_key)
        time.sleep(PLACES_SLEEP)
        entry = {
            "business_name": b.get("business_name"),
            "place_id": place_id,
            "address": details.get("address") or b.get("address"),
            "phone_google": details.get("phone_google"),
            "website": details.get("website"),
            "rating": details.get("rating") if details.get("rating") is not None else b.get("rating"),
            "user_ratings_total": (
                details.get("user_ratings_total")
                if details.get("user_ratings_total") is not None
                else b.get("user_ratings_total")
            ),
            "business_status": details.get("business_status"),
            "reviews": details.get("reviews") or [],
            "niche_key": b.get("niche_key"),
        }
        if not entry.get("address"):
            logger.info(
                "No address from Places for %s (%s)",
                entry.get("business_name"),
                place_id,
            )
        ok, reason = passes_quality_filters(
            entry,
            filter_franchises=filter_franchises,
            min_reviews=min_reviews,
            require_phone=(objective == "phone"),
            require_website=require_website,
        )
        if not ok:
            quality_rejects[reason] = quality_rejects.get(reason, 0) + 1
            continue
        enriched.append(entry)

    if quality_rejects:
        for reason, count in sorted(quality_rejects.items()):
            logger.info("Quality filter rejected %d leads: %s", count, reason)

    unique = {}
    for e in enriched:
        key = e.get("website") or e.get("business_name")
        if key in unique:
            continue
        unique[key] = e
    businesses_unique = list(unique.values())
    logger.critical("After deduplication: %d businesses", len(businesses_unique))

    analyses = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_map = {}
        for b in businesses_unique:
            url = b.get("website")
            if url:
                future = ex.submit(analyze_website, url)
            else:
                future = ex.submit(
                    lambda: {
                        "emails": [],
                        "phones_website": [],
                        "https": False,
                        "has_viewport": False,
                        "html_length": 0,
                        "has_title": False,
                        "has_cta": False,
                        "error": None,
                    }
                )
            future_map[future] = b
        for fut in as_completed(future_map):
            b = future_map[fut]
            try:
                analyses[b.get("place_id")] = fut.result()
            except Exception as e:
                logger.error("Website analysis failed for %s: %s", b.get("website"), e)
                analyses[b.get("place_id")] = {
                    "emails": [],
                    "phones_website": [],
                    "https": False,
                    "has_viewport": False,
                    "html_length": 0,
                    "has_title": False,
                    "has_cta": False,
                    "error": str(e),
                }

    rows = []
    filtered_below_min = 0
    filtered_objective = 0
    session = EmailDiscoverySession() if objective != "phone" else None
    try:
        for b in businesses_unique:
            place_id = b.get("place_id")
            if not place_id:
                continue

            if not is_new_place(place_id, existing_ids):
                continue

            a = analyses.get(place_id, {})
            emails = a.get("emails") or []
            emails_clean = []
            seen_emails = set()
            for raw in emails:
                email = validate_email(raw)
                if email and email not in seen_emails:
                    seen_emails.add(email)
                    emails_clean.append(email)

            row = {
                "business_name": b.get("business_name"),
                "place_id": place_id,
                "address": b.get("address") or "",
                "phone_google": b.get("phone_google"),
                "phone_website": ";".join(a.get("phones_website", [])) if a.get("phones_website") else None,
                "email": ";".join(emails_clean),
                "has_email": bool(emails_clean),
                "website": b.get("website"),
                "rating": b.get("rating"),
                "user_ratings_total": b.get("user_ratings_total"),
                "business_status": b.get("business_status"),
                "https": a.get("https", False),
                "has_viewport": a.get("has_viewport", False),
                "html_length": a.get("html_length", 0),
                "has_cta": a.get("has_cta", False),
                "niche_key": b.get("niche_key"),
            }
            if emails_clean:
                row["email_source"] = "website"

            if session is not None and should_run_email_discovery(row, objective):
                logger.info("[EMAIL] Processing: %s", row.get("business_name"))
                if not emails_clean:
                    logger.info("[EMAIL] No email found in primary source")
                try:
                    enrich_lead_with_email(row, city=city, state=state, session=session)
                except Exception as e:
                    logger.error("[EMAIL] Enrichment failed for %s: %s", row.get("business_name"), e)

            emails_clean = lead_emails(row)
            row["email"] = ";".join(emails_clean)
            row["has_email"] = bool(emails_clean)

            if any(email in contacted_emails for email in emails_clean):
                continue

            has_website = bool(row.get("website"))
            lead_score = score_lead(
                has_website,
                row.get("https", False),
                row.get("has_viewport", False),
                row.get("html_length", 0),
                row.get("has_email"),
                row.get("has_cta", False),
                row.get("rating"),
                row.get("user_ratings_total"),
                row.get("business_status"),
            )
            logger.info("[SCORE] Lead score: %s", lead_score)
            row["lead_score"] = lead_score

            if lead_score < min_score:
                filtered_below_min += 1
                continue

            if not lead_meets_objective(row, objective):
                logger.info("[OBJECTIVE] %s -> FAIL", objective)
                logger.info("[LEAD] Rejected")
                filtered_objective += 1
                continue

            logger.info("[OBJECTIVE] %s -> PASS", objective)
            logger.info("[LEAD] Qualified")

            owner_names = extract_owner_names(b.get("reviews") or [])
            row["owner_names"] = ";".join(owner_names) if owner_names else None
            row.pop("has_cta", None)
            rows.append(row)
    finally:
        if session is not None:
            session.close()

    if filtered_objective:
        logger.info("Filtered %d leads that failed objective %s", filtered_objective, objective)
    if filtered_below_min:
        logger.info(
            "Filtered %d leads below minimum score %d",
            filtered_below_min,
            min_score,
        )
    return rows


def save_results(rows, json_path):
    """Append lead rows to a JSON array file, deduping by place_id (or website+name)."""
    existing = []
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                existing = loaded
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Failed to read existing leads from %s: %s", json_path, e)
            existing = []

    combined = list(existing) + list(rows)
    seen_place_ids = set()
    seen_fallback = set()
    deduped = []
    for row in combined:
        place_id = row.get("place_id")
        if place_id:
            if place_id in seen_place_ids:
                continue
            seen_place_ids.add(place_id)
        else:
            key = (row.get("website") or "", row.get("business_name") or "")
            if key in seen_fallback:
                continue
            seen_fallback.add(key)
        deduped.append(row)

    def _score_key(row):
        try:
            return -int(row.get("lead_score") or 0)
        except (TypeError, ValueError):
            return 0

    deduped.sort(key=_score_key)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2)
        f.write("\n")
    if existing:
        logger.info("Appended and saved %d total leads to %s", len(deduped), json_path)
    else:
        logger.critical("Saved %d leads to %s", len(deduped), json_path)


def extract_real_email(raw_email_field):
    emails = (raw_email_field or "").split(";")
    for e in emails:
        e = e.strip().lower()
        if e and "sentry" not in e and "wixpress" not in e:
            return e
    return ""


def send_to_dashboard(rows):
    """Bulk-ingest qualifying leads to the dashboard API."""
    from helper_scripts.api_manager import APIManager as api

    payload = []
    for row in rows:
        niche_key = row.get("niche_key")
        category = KEYWORD_CATEGORIES.get(niche_key, niche_key)
        payload.append({
            "business_name": row["business_name"],
            "address": row.get("address") or "",
            "phone": row.get("phone_google") or "",
            "email": extract_real_email(row.get("email") or ""),
            "category": category,
            "tags": ["lead_automation", "google-places-api"],
            "score": int(row["lead_score"]),
        })

    if not payload:
        logger.info("No leads to send to dashboard")
        return

    logger.critical("Sending %d leads to dashboard (bulk ingest)", len(payload))
    api().build_request(
        base_url=DASHBOARD_BASE_URL,
        endpoint=DASHBOARD_BULK_ENDPOINT,
        json_body=payload,
        api="Lead Ingest",
        method="POST",
        timeout=60.0,
    )


def enrich_missing_emails(rows):
    """Fill in missing emails from Facebook Pages; returns the rows that gained one.

    leadenrich imports leadgen for dashboard ingest, so it is imported here
    rather than at module level. Enrichment is best effort: a failure must not
    cost the run its leads.
    """
    from leadenrich import EnrichConfig, enrich_leads

    try:
        enriched = enrich_leads(rows, EnrichConfig())
    except Exception as e:
        logger.error("Lead enrichment failed: %s", e)
        return []

    if enriched:
        logger.critical("Enrichment found emails for %d leads", len(enriched))
    return enriched


def _is_contacted(row, contacted_emails):
    """True if any email on the row has already been contacted."""
    emails = [e.strip().lower() for e in (row.get("email") or "").split(";") if e.strip()]
    return any(email in contacted_emails for email in emails)


def _prompt_int(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid number, using default {default}.")
        return default


def _prompt_bool(prompt, default=True):
    default_label = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{default_label}]: ").strip().lower()
    if not raw:
        return default
    if raw in ("y", "yes", "true", "1"):
        return True
    if raw in ("n", "no", "false", "0"):
        return False
    print(f"Invalid choice, using default {default}.")
    return default


def _prompt_output_mode(default="json"):
    labels = {"1": "json", "2": "dashboard", "3": "both"}
    default_num = {"json": "1", "dashboard": "2", "both": "3"}.get(default, "1")
    raw = input(f"Output: 1=JSON  2=Dashboard  3=Both [{default_num}]: ").strip()
    if not raw:
        return default
    return labels.get(raw, default)


def _prompt_objective(default="phone"):
    labels = {"1": "phone", "2": "email", "3": "either", "4": "both"}
    default_num = {"phone": "1", "email": "2", "either": "3", "both": "4"}.get(default, "1")
    raw = input(
        f"Objective: 1=phone  2=email  3=either  4=both [{default_num}]: "
    ).strip()
    if not raw:
        return normalize_objective(default)
    return labels.get(raw, normalize_objective(default))


def _prompt_text(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else default


def _locations_by_state(coords_data=None):
    """Return {state: [(city, coords), ...]} from coords.json data."""
    data = coords_data if coords_data is not None else COORDS_DATA
    grouped = {}
    for state, cities in data.items():
        grouped[state] = [(city, coords) for city, coords in cities.items()]
    return grouped


def _parse_index_selection(raw, max_index):
    """Parse '1,3,5' into 0-based indices; empty string means all."""
    if not raw.strip():
        return None
    indices = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            idx = int(part) - 1
            if 0 <= idx < max_index:
                indices.append(idx)
        except ValueError:
            continue
    return indices


def _terminal_width(fallback=80):
    try:
        return max(40, shutil.get_terminal_size(fallback=(fallback, 24)).columns)
    except Exception:
        return fallback


def _format_numbered_items_horizontal(items, width=None):
    """Format '1) label  2) label ...' wrapping across terminal width."""
    if width is None:
        width = _terminal_width()
    lines = []
    current = ""
    for i, label in enumerate(items, 1):
        cell = f"{i}) {label}"
        if not current:
            current = cell
            continue
        candidate = f"{current}  {cell}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = cell
    if current:
        lines.append(current)
    return "\n".join(lines)


def _prompt_keywords(keyword_map):
    """Prompt user to select keywords from keywords.json."""
    keys = list(keyword_map.keys())
    print("\n--- Keywords (keywords.json) ---")
    labels = [f"{kw} -> {keyword_map[kw]}" for kw in keys]
    print(_format_numbered_items_horizontal(labels))
    raw = input("Enter numbers (comma-separated) or press Enter for all: ").strip()
    indices = _parse_index_selection(raw, len(keys))
    if indices is None:
        return list(keys)
    selected = [keys[i] for i in indices]
    return selected or list(keys)


def _prompt_locations(all_locations):
    """Prompt user to select locations from coords.json, grouped by state."""
    by_state = _locations_by_state()
    print("\n--- Locations (coords.json) ---")
    index_map = []
    for state, cities in by_state.items():
        print(f"\n{state}:")
        state_items = []
        for city, coords in cities:
            index_map.append((state, city, coords))
            state_items.append(city)
        # Global numbering continues across states; format only this state's slice.
        start = len(index_map) - len(state_items) + 1
        width = _terminal_width()
        current = ""
        lines = []
        for offset, city in enumerate(state_items):
            cell = f"{start + offset}) {city}"
            if not current:
                current = cell
                continue
            candidate = f"{current}  {cell}"
            if len(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = cell
        if current:
            lines.append(current)
        print("\n".join(lines))
    raw = input("\nEnter numbers (comma-separated) or press Enter for all: ").strip()
    indices = _parse_index_selection(raw, len(index_map))
    if indices is None:
        return list(all_locations)
    selected = [index_map[i] for i in indices]
    return selected or list(all_locations)


def interactive_select_locations_and_keywords():
    """Return (keywords, locations) from interactive pickers."""
    keywords = _prompt_keywords(KEYWORD_CATEGORIES)
    locations = _prompt_locations(_default_locations())
    return keywords, locations


def interactive_customize_config(base_config=None):
    """Walk through customization prompts for persisted defaults (no keywords/locations)."""
    cfg = base_config or config_from_saved_settings()
    print("\n--- Customize Lead Generation Defaults ---")
    cfg.min_score = _prompt_int("Minimum score", cfg.min_score)
    cfg.min_reviews = _prompt_int("Minimum review count", cfg.min_reviews)
    cfg.filter_franchises = _prompt_bool("Filter out franchises/chains", cfg.filter_franchises)
    cfg.objective = _prompt_objective(cfg.objective)
    cfg.require_website = _prompt_bool("Require website", cfg.require_website)
    cfg.lead_enrichment = _prompt_bool(
        "Lead enrichment (find missing emails on Facebook)",
        cfg.lead_enrichment,
    )
    cfg.output_mode = _prompt_output_mode(cfg.output_mode)
    cfg.json_output = _prompt_text("JSON output path", cfg.json_output)
    return cfg


def _print_config_summary(config, include_run_scope=True):
    print("\n--- Configuration ---")
    print(f"  Min score:         {config.min_score}")
    print(f"  Min reviews:       {config.min_reviews}")
    print(f"  Filter franchises: {config.filter_franchises}")
    print(f"  Objective:         {config.objective}")
    print(f"  Require website:   {config.require_website}")
    print(f"  Lead enrichment:   {config.lead_enrichment}")
    print(f"  Output:            {config.output_mode}")
    print(f"  JSON path:         {config.json_output}")
    if include_run_scope:
        print(f"  Keywords:          {', '.join(config.keywords)}")
        locs = ", ".join(f"{city}, {state}" for state, city, _ in config.locations)
        print(f"  Locations:         {locs}")
    print()


def interactive_run_config():
    """Load saved defaults, prompt keywords/locations, return config or None if cancelled."""
    cfg = config_from_saved_settings()
    cfg.keywords, cfg.locations = interactive_select_locations_and_keywords()
    _print_config_summary(cfg)
    confirm = input("Run with these settings? [Y/n]: ").strip().lower()
    if confirm in ("n", "no"):
        return None
    return cfg


def interactive_main_menu():
    """Show startup menu and return a LeadgenConfig, or None to exit."""
    while True:
        saved = load_saved_settings()
        defaults_note = (
            f"min score {saved.get('min_score', 80)}, "
            f"output {saved.get('output_mode', 'json')}"
            if saved
            else "min score 80, save to JSON"
        )
        print("\n=== Lead Generation ===")
        print(f"1) Run ({defaults_note}; choose keywords & locations)")
        print("2) Customize settings (save defaults, do not run)")
        print("3) Exit")
        choice = input("Select [1]: ").strip() or "1"
        if choice == "3":
            return None
        if choice == "2":
            cfg = interactive_customize_config()
            save_settings(cfg)
            _print_config_summary(cfg, include_run_scope=False)
            print(f"Defaults saved to {SETTINGS_PATH.name}. Returning to menu.")
            continue
        if choice == "1":
            return interactive_run_config()
        print("Invalid choice. Please select 1, 2, or 3.")


def parse_args():
    parser = argparse.ArgumentParser(description="Local business lead generation")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Skip interactive menu and use defaults",
    )
    parser.add_argument("--min-score", type=int, help="Minimum lead_score to keep (default 80)")
    parser.add_argument(
        "--min-reviews",
        type=int,
        help="Minimum user_ratings_total to keep (default 5)",
    )
    parser.add_argument(
        "--filter-franchises",
        dest="filter_franchises",
        action="store_true",
        default=None,
        help="Exclude franchise/chain leads (default)",
    )
    parser.add_argument(
        "--no-filter-franchises",
        dest="filter_franchises",
        action="store_false",
        help="Allow franchise/chain leads",
    )
    parser.add_argument(
        "--objective",
        choices=list(VALID_OBJECTIVES),
        default=None,
        help="Hard contact requirement: phone, email, either, or both (default phone)",
    )
    parser.add_argument(
        "--require-phone",
        dest="require_phone",
        action="store_true",
        default=None,
        help="Legacy alias: require a valid phone (maps to --objective)",
    )
    parser.add_argument(
        "--no-require-phone",
        dest="require_phone",
        action="store_false",
        help="Legacy alias: do not require a phone (maps to --objective)",
    )
    parser.add_argument(
        "--require-website",
        dest="require_website",
        action="store_true",
        default=None,
        help="Require a website URL from Place Details",
    )
    parser.add_argument(
        "--no-require-website",
        dest="require_website",
        action="store_false",
        help="Allow leads without a website (default)",
    )
    parser.add_argument(
        "--require-email",
        dest="require_email",
        action="store_true",
        default=None,
        help="Legacy alias: require an email (maps to --objective)",
    )
    parser.add_argument(
        "--no-require-email",
        dest="require_email",
        action="store_false",
        help="Legacy alias: do not require an email (maps to --objective)",
    )
    parser.add_argument(
        "--lead-enrichment",
        dest="lead_enrichment",
        action="store_true",
        default=None,
        help="Look up missing emails on Facebook after scraping (default)",
    )
    parser.add_argument(
        "--no-lead-enrichment",
        dest="lead_enrichment",
        action="store_false",
        help="Skip Facebook email enrichment",
    )
    parser.add_argument(
        "--output",
        choices=["json", "dashboard", "both"],
        help="Output destination",
    )
    parser.add_argument("--json-path", help="JSON output path (default leads_output.json)")
    parser.add_argument("--keywords", nargs="+", help="Keyword subset from keywords.json")
    parser.add_argument(
        "--city",
        action="append",
        help="City name filter (repeatable); matches coords.json city names",
    )
    return parser.parse_args()


def _has_cli_overrides(args):
    return any([
        args.defaults,
        args.min_score is not None,
        args.min_reviews is not None,
        args.filter_franchises is not None,
        args.objective is not None,
        args.require_phone is not None,
        args.require_website is not None,
        args.require_email is not None,
        args.lead_enrichment is not None,
        args.output is not None,
        args.json_path is not None,
        args.keywords is not None,
        args.city is not None,
    ])


def config_from_args(args):
    """Build LeadgenConfig from saved defaults plus argparse overrides."""
    config = config_from_saved_settings()
    if args.min_score is not None:
        config.min_score = args.min_score
    if args.min_reviews is not None:
        config.min_reviews = args.min_reviews
    if args.filter_franchises is not None:
        config.filter_franchises = args.filter_franchises
    if args.objective is not None:
        config.objective = normalize_objective(args.objective)
    elif args.require_phone is not None or args.require_email is not None:
        require_phone = config.objective in ("phone", "both")
        require_email = config.objective in ("email", "both")
        if args.require_phone is not None:
            require_phone = args.require_phone
        if args.require_email is not None:
            require_email = args.require_email
        config.objective = objective_from_require_flags(require_phone, require_email)
    if args.require_website is not None:
        config.require_website = args.require_website
    if args.lead_enrichment is not None:
        config.lead_enrichment = args.lead_enrichment
    if args.output is not None:
        config.output_mode = args.output
    if args.json_path is not None:
        config.json_output = args.json_path
    if args.keywords is not None:
        config.keywords = args.keywords
    if args.city is not None:
        city_names = set()
        for entry in args.city:
            for part in entry.split(","):
                part = part.strip()
                if part:
                    city_names.add(part.lower())
        filtered = [
            loc for loc in _default_locations()
            if loc[1].lower() in city_names
        ]
        if filtered:
            config.locations = filtered
        else:
            logger.warning("No cities matched --city filter; using all locations")
    return config


def resolve_config(args):
    """Resolve final config from CLI flags and/or interactive menu."""
    if args.defaults:
        return config_from_args(args)
    if _has_cli_overrides(args):
        return config_from_args(args)
    return interactive_main_menu()


def run_leadgen(config):
    """Run lead generation with the given configuration."""
    if not GOOGLE_API_KEY or GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY":
        logger.error("Please set GOOGLE_API_KEY in .env before running.")
        return

    if config.output_mode in ("dashboard", "both") and not os.getenv("LEAD_INGEST_KEY"):
        logger.error("LEAD_INGEST_KEY is required for dashboard output mode.")
        return

    logger.critical("Loading contacted emails to avoid re-contacting...")
    if os.path.exists(CONTACTED_FILE):
        with open(CONTACTED_FILE, "r", encoding="utf-8") as f:
            contacted_emails = set(line.strip().lower() for line in f if line.strip())
    else:
        contacted_emails = set()

    existing_place_ids = load_existing_place_ids(config.json_output)
    total_rows = []

    for state, city, coords in config.locations:
        try:
            logger.critical(
                "Starting lead generation for %s, %s. Using Coords: %s",
                city,
                state,
                coords,
            )
            places = get_places(coords, config.search_radius, config.keywords, GOOGLE_API_KEY)
            if not places:
                logger.critical("No places found; moving to next location.")
                continue
            rows = process_businesses(
                places,
                GOOGLE_API_KEY,
                existing_place_ids,
                contacted_emails,
                min_score=config.min_score,
                max_workers=config.max_workers,
                filter_franchises=config.filter_franchises,
                min_reviews=config.min_reviews,
                require_website=config.require_website,
                objective=config.objective,
                city=city,
                state=state,
            )
            total_rows.extend(rows)
        except Exception as e:
            logger.error("Error processing businesses for %s, %s: %s", city, state, e)
            continue

    if not total_rows:
        logger.critical("No qualifying leads found.")
        return

    logger.critical("Found %d qualifying leads (min score %d)", len(total_rows), config.min_score)

    if config.lead_enrichment:
        enriched = enrich_missing_emails(total_rows)
        if enriched and contacted_emails:
            kept = [row for row in total_rows if not _is_contacted(row, contacted_emails)]
            if len(kept) != len(total_rows):
                logger.info(
                    "Dropped %d enriched leads already in %s",
                    len(total_rows) - len(kept),
                    CONTACTED_FILE,
                )
                total_rows = kept

    if config.output_mode in ("json", "both"):
        save_results(total_rows, config.json_output)

    if config.output_mode in ("dashboard", "both"):
        send_to_dashboard(total_rows)


def main():
    args = parse_args()
    config = resolve_config(args)
    if config is None:
        print("Exiting.")
        return
    run_leadgen(config)


if __name__ == "__main__":
    main()
