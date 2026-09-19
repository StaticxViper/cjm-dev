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
from leadfilter import (
    load_existing_place_ids,
    load_existing_identities,
    is_new_place,
    is_new_identity,
)
from email_discovery import (
    EmailDiscoverySession,
    enrich_lead_with_email,
    extract_emails_from_html,
    lead_emails,
    lead_has_valid_email,
    lead_has_valid_phone,
    validate_email,
)
from playwright_discovery import (
    BusinessDiscoverySession,
    area_search_multiplier,
    business_dedupe_key,
    dedupe_businesses,
    extract_place_id_from_url,
    normalize_area_expansion,
)
from search_history import (
    DEFAULT_HISTORY_PATH,
    DEFAULT_USAGE_PATH,
    SearchHistory,
    update_usage_stats,
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
VALID_LEADGEN_TYPES = ("api_manager", "playwright")
VALID_AREA_EXPANSIONS = ("off", "light", "dense")
DEFAULT_LEADGEN_TYPE = "api_manager"
DEFAULT_PLAYWRIGHT_MAX_PAGES = 20
DEFAULT_PLAYWRIGHT_MAX_RESULTS_PER_SEARCH = 400
DEFAULT_PLAYWRIGHT_AREA_EXPANSION = "off"
LEADGEN_STAGE_TOTAL = 7
PERSISTED_SETTINGS_KEYS = (
    "min_score",
    "min_reviews",
    "filter_franchises",
    "objective",
    "require_website",
    "lead_enrichment",
    "output_mode",
    "json_output",
    "leadgen_type",
    "playwright_max_pages",
    "playwright_max_results_per_search",
    "playwright_area_expansion",
    "skip_searched",
    "search_history_path",
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


def log_stage(number, name, detail=None, total=LEADGEN_STAGE_TOTAL):
    """Emit a high-visibility stage marker for at-a-glance progress."""
    if detail:
        logger.critical("[STAGE %d/%d] %s — %s", number, total, name, detail)
    else:
        logger.critical("[STAGE %d/%d] %s", number, total, name)


def log_step(stage, step, name, detail=None):
    """Emit a step marker nested under a stage."""
    if detail:
        logger.info("[STEP %d.%d] %s — %s", stage, step, name, detail)
    else:
        logger.info("[STEP %d.%d] %s", stage, step, name)


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
    # Default preserves existing Places/API Manager behavior for saved configs.
    leadgen_type: str = DEFAULT_LEADGEN_TYPE
    playwright_max_pages: int = DEFAULT_PLAYWRIGHT_MAX_PAGES
    playwright_max_results_per_search: int = DEFAULT_PLAYWRIGHT_MAX_RESULTS_PER_SEARCH
    playwright_area_expansion: str = DEFAULT_PLAYWRIGHT_AREA_EXPANSION
    skip_searched: bool = True
    search_history_path: str = DEFAULT_HISTORY_PATH


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
        "leadgen_type": normalize_leadgen_type(config.leadgen_type),
        "playwright_max_pages": int(config.playwright_max_pages),
        "playwright_max_results_per_search": int(
            config.playwright_max_results_per_search
        ),
        "playwright_area_expansion": normalize_area_expansion(
            config.playwright_area_expansion
        ),
        "skip_searched": bool(config.skip_searched),
        "search_history_path": str(config.search_history_path or DEFAULT_HISTORY_PATH),
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
    if "leadgen_type" in saved:
        config.leadgen_type = normalize_leadgen_type(saved["leadgen_type"])
    if "playwright_max_pages" in saved:
        try:
            config.playwright_max_pages = max(1, int(saved["playwright_max_pages"]))
        except (TypeError, ValueError):
            pass
    if "playwright_max_results_per_search" in saved:
        try:
            config.playwright_max_results_per_search = max(
                1, int(saved["playwright_max_results_per_search"])
            )
        except (TypeError, ValueError):
            pass
    if "playwright_area_expansion" in saved:
        config.playwright_area_expansion = normalize_area_expansion(
            saved["playwright_area_expansion"]
        )
    if "skip_searched" in saved:
        config.skip_searched = bool(saved["skip_searched"])
    if "search_history_path" in saved and saved["search_history_path"]:
        config.search_history_path = str(saved["search_history_path"])
    return config


def normalize_leadgen_type(value, default=DEFAULT_LEADGEN_TYPE):
    """Return a valid leadgen_type string, falling back to default."""
    if isinstance(value, str) and value.strip().lower() in VALID_LEADGEN_TYPES:
        return value.strip().lower()
    return default


KEYWORD_GROUP_LABELS = {
    "home_exterior": "Home exterior",
    "home_interior": "Home interior",
    "cleaning": "Cleaning / junk",
    "auto": "Auto",
    "events": "Events / food",
    "pets": "Pets",
    "personal_care": "Personal care",
    "professional": "Professional services",
    "education_care": "Education / care",
    "other": "Other",
}
KEYWORD_GROUPS = {
    "home_exterior": [
        "landscaping",
        "lawn care",
        "tree service",
        "roofing",
        "fencing",
        "deck building",
        "garage door",
        "window installation",
        "siding",
        "gutter cleaning",
        "pressure washing",
        "concrete",
        "masonry",
    ],
    "home_interior": [
        "plumbing",
        "hvac",
        "electrician",
        "general contractor",
        "remodeling",
        "home renovation",
        "painting",
        "flooring",
        "carpentry",
        "handyman",
        "drywall",
        "appliance repair",
    ],
    "cleaning": [
        "window cleaning",
        "carpet cleaning",
        "house cleaning",
        "commercial cleaning",
        "junk removal",
        "upholstery cleaning",
    ],
    "auto": [
        "mobile detailing",
        "auto detailing",
        "auto repair",
        "tire shop",
        "towing",
        "car window tinting",
        "mobile mechanic",
    ],
    "events": [
        "photography",
        "wedding photography",
        "videography",
        "dj services",
        "event planning",
        "catering",
        "bakery",
        "florist",
    ],
    "pets": [
        "pet grooming",
        "dog walking",
        "pet sitting",
        "dog training",
    ],
    "personal_care": [
        "barber",
        "hair salon",
        "nail salon",
        "massage therapy",
        "personal trainer",
        "fitness studio",
        "tattoo shop",
        "med spa",
        "beauty salon",
    ],
    "professional": [
        "accounting",
        "bookkeeping",
        "tax preparation",
        "real estate agent",
        "insurance agency",
        "mortgage broker",
        "financial advisor",
        "law firm",
        "attorney",
        "private investigator",
    ],
    "education_care": [
        "tutoring",
        "music lessons",
        "driving school",
        "childcare",
        "senior care",
        "home care",
    ],
    "other": [
        "moving company",
        "pest control",
        "pool service",
        "pool cleaning",
        "locksmith",
    ],
}


def keyword_group_for(keyword):
    """Return the industry group key for a keywords.json term."""
    for group, names in KEYWORD_GROUPS.items():
        if keyword in names:
            return group
    return "other"


def listing_needs_detail(entry, config):
    """True when a Maps card is missing fields required by the current run."""
    objective = normalize_objective(config.objective)
    phone = (entry.get("phone_google") or "").strip()
    website = (entry.get("website") or "").strip()
    if objective in ("phone", "both") and not phone:
        return True
    if objective in ("email", "both") and not website:
        return True
    if objective == "either" and not phone and not website:
        return True
    if config.require_website and not website:
        return True
    min_reviews = int(config.min_reviews or 0)
    if min_reviews > 0:
        reviews = entry.get("user_ratings_total")
        if reviews is None:
            return True
        try:
            if int(reviews) < min_reviews:
                return True
        except (TypeError, ValueError):
            return True
    return False


def apply_high_volume_preset(config=None):
    """Tune a config for large Playwright runs (hundreds–thousands of leads)."""
    cfg = config or LeadgenConfig()
    cfg.leadgen_type = "playwright"
    cfg.playwright_max_pages = max(20, int(cfg.playwright_max_pages or 20))
    cfg.playwright_max_results_per_search = max(
        400, int(cfg.playwright_max_results_per_search or 400)
    )
    cfg.playwright_area_expansion = "light"
    cfg.skip_searched = True
    cfg.min_score = min(int(cfg.min_score), 55)
    cfg.min_reviews = 0
    cfg.filter_franchises = True
    cfg.objective = "phone"
    cfg.require_website = False
    cfg.lead_enrichment = False
    if cfg.output_mode not in ("json", "dashboard", "both"):
        cfg.output_mode = "json"
    return cfg


def estimate_discovery_volume(config):
    """Return a dict describing expected search count and lead yield."""
    n_kw = len(config.keywords or [])
    n_loc = len(config.locations or [])
    leadgen_type = normalize_leadgen_type(config.leadgen_type)
    expansion = normalize_area_expansion(
        getattr(config, "playwright_area_expansion", "off")
    )
    areas = area_search_multiplier(expansion) if leadgen_type == "playwright" else 1
    searches = n_kw * n_loc * areas
    # Maps typically returns 40–120 unique listings per query; area overlap is high.
    per_query_low = 40 if leadgen_type == "playwright" else 20
    per_query_high = 120 if leadgen_type == "playwright" else 60
    discovered_low = searches * per_query_low
    discovered_high = searches * per_query_high
    # Unique after cross-city overlap, then quality filters (~20–50% keep).
    unique_low = max(n_kw * n_loc * 15, int(discovered_low * 0.15))
    unique_high = max(unique_low, int(discovered_high * 0.45))
    return {
        "keywords": n_kw,
        "locations": n_loc,
        "areas_per_search": areas,
        "searches": searches,
        "discovered_low": discovered_low,
        "discovered_high": discovered_high,
        "unique_low": unique_low,
        "unique_high": unique_high,
        "leadgen_type": leadgen_type,
        "expansion": expansion,
    }


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


def get_places(location, radius, keywords, api_key, api_call_counter=None):
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
                if api_call_counter is not None:
                    api_call_counter["places_nearby"] = (
                        api_call_counter.get("places_nearby", 0) + 1
                    )
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
                    "search_term": kw,
                    "source": "api_manager",
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
    fetch_details=True,
    existing_identities=None,
    source="api_manager",
    api_call_counter=None,
):
    """Given list of basic business entries, enrich with place details and analyze websites concurrently.

    When fetch_details is False (Playwright path), Place Details API calls are skipped and
    fields already present on each business entry are used instead.
    """
    objective = normalize_objective(objective)
    enriched = []
    quality_rejects = {}
    if fetch_details:
        log_step(4, 2, "Fetch Place Details", f"{len(businesses)} businesses")
        logger.critical("Fetching place details for %d businesses", len(businesses))
    else:
        log_step(4, 2, "Use discovered fields", "Place Details API skipped")
        logger.critical(
            "Processing %d discovered businesses (Place Details API skipped)",
            len(businesses),
        )
    for b in businesses:
        place_id = b.get("place_id")
        if fetch_details:
            details = get_place_details(place_id, api_key)
            if api_call_counter is not None:
                api_call_counter["places_details"] = (
                    api_call_counter.get("places_details", 0) + 1
                )
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
                "profile_url": b.get("profile_url"),
                "source": b.get("source") or source,
                "search_term": b.get("search_term") or b.get("niche_key"),
                "location_searched": b.get("location_searched"),
            }
        else:
            entry = {
                "business_name": b.get("business_name"),
                "place_id": place_id,
                "address": b.get("address"),
                "phone_google": b.get("phone_google"),
                "website": b.get("website"),
                "rating": b.get("rating"),
                "user_ratings_total": b.get("user_ratings_total"),
                "business_status": b.get("business_status"),
                "reviews": b.get("reviews") or [],
                "niche_key": b.get("niche_key"),
                "profile_url": b.get("profile_url"),
                "source": b.get("source") or source,
                "search_term": b.get("search_term") or b.get("niche_key"),
                "location_searched": b.get("location_searched"),
                "category": b.get("category"),
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
        key = business_dedupe_key(e) or (e.get("website") or e.get("business_name"),)
        if key in unique:
            continue
        unique[key] = e
    businesses_unique = list(unique.values())
    log_step(
        4,
        3,
        "After quality filters + dedupe",
        f"{len(businesses_unique)} businesses remain",
    )
    logger.critical("After deduplication: %d businesses", len(businesses_unique))

    analyses = {}
    with_website = sum(1 for b in businesses_unique if (b.get("website") or "").strip())
    log_step(
        4,
        4,
        "Website analysis",
        f"{with_website} with website / {len(businesses_unique) - with_website} without",
    )
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
            analysis_key = b.get("place_id") or business_dedupe_key(b) or id(b)
            try:
                analyses[analysis_key] = fut.result()
            except Exception as e:
                logger.error("Website analysis failed for %s: %s", b.get("website"), e)
                analyses[analysis_key] = {
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
    if session is not None:
        log_step(4, 5, "Email discovery", f"objective={objective}")
    else:
        log_step(4, 5, "Email discovery", "skipped (objective=phone)")
    try:
        for b in businesses_unique:
            place_id = b.get("place_id")
            if existing_identities is not None:
                if not is_new_identity(b, existing_identities):
                    continue
            else:
                if not place_id:
                    continue
                if not is_new_place(place_id, existing_ids):
                    continue

            analysis_key = place_id or business_dedupe_key(b) or id(b)
            a = analyses.get(analysis_key, {})
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
                "profile_url": b.get("profile_url"),
                "source": b.get("source") or source,
                "search_term": b.get("search_term") or b.get("niche_key"),
                "location_searched": b.get("location_searched"),
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
        category = row.get("category") or KEYWORD_CATEGORIES.get(niche_key, niche_key)
        tags = [
            "lead_automation",
            "playwright" if (row.get("source") == "playwright") else "google-places-api",
        ]
        for extra in row.get("tags") or []:
            if extra and extra not in tags:
                tags.append(extra)
        payload.append({
            "business_name": row["business_name"],
            "address": row.get("address") or "",
            "phone": row.get("phone_google") or "",
            "email": extract_real_email(row.get("email") or ""),
            "category": category,
            "tags": tags,
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


def enrich_missing_emails(rows, leadgen_type=None):
    """Fill in missing emails / research leads; returns rows the enricher processed.

    API Manager discovery uses Facebook/Apify (leadenrich.py). Playwright discovery
    uses Google research (leadenrich_playwright.py). Both modules import leadgen
    lazily for dashboard ingest, so they are imported here rather than at module
    level. Enrichment is best effort: a failure must not cost the run its leads.
    """
    provider = normalize_leadgen_type(leadgen_type or DEFAULT_LEADGEN_TYPE)
    log_stage(5, "Lead enrichment", f"{len(rows)} qualifying leads ({provider})")
    try:
        if provider == "playwright":
            from leadenrich_playwright import EnrichConfig, enrich_leads

            log_step(5, 1, "Hand off to Playwright Google enrichment")
        else:
            from leadenrich import EnrichConfig, enrich_leads

            log_step(5, 1, "Hand off to Facebook enrichment")
        enriched = enrich_leads(rows, EnrichConfig())
    except Exception as e:
        logger.error("[STAGE 5] Lead enrichment failed: %s", e)
        return []

    if enriched:
        logger.critical(
            "[STEP 5.2] Enrichment updated %d leads",
            len(enriched),
        )
    else:
        log_step(5, 2, "Enrichment complete", "no new emails found")
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


def _prompt_leadgen_type(default=DEFAULT_LEADGEN_TYPE):
    labels = {"1": "api_manager", "2": "playwright"}
    default_num = {"api_manager": "1", "playwright": "2"}.get(
        normalize_leadgen_type(default), "1"
    )
    raw = input(
        f"Leadgen type: 1=API Manager  2=Playwright [{default_num}]: "
    ).strip()
    if not raw:
        return normalize_leadgen_type(default)
    return labels.get(raw, normalize_leadgen_type(default))


def _prompt_area_expansion(default=DEFAULT_PLAYWRIGHT_AREA_EXPANSION):
    labels = {"1": "off", "2": "light", "3": "dense"}
    current = normalize_area_expansion(default)
    default_num = {"off": "1", "light": "2", "dense": "3"}.get(current, "1")
    raw = input(
        "Area expansion (more leads per city): "
        "1=off  2=light (~5 map cells)  3=dense (~9 cells) "
        f"[{default_num}]: "
    ).strip()
    if not raw:
        return current
    return labels.get(raw, current)


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
    """Parse '1,3,5' or '1-4,8' into 0-based indices.

    Empty / 'all' means all (returns None). 'none' means nothing (returns []).
    """
    if not raw or not raw.strip():
        return None
    lowered = raw.strip().lower()
    if lowered in ("all", "*"):
        return None
    if lowered in ("none", "n"):
        return []
    indices = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and not part.startswith("-"):
            ends = part.split("-", 1)
            try:
                start = int(ends[0].strip())
                end = int(ends[1].strip())
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                idx = number - 1
                if 0 <= idx < max_index and idx not in indices:
                    indices.append(idx)
            continue
        try:
            idx = int(part) - 1
            if 0 <= idx < max_index and idx not in indices:
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


def _prompt_choice(title, options, default="1"):
    """Numbered single-choice prompt. options is [(key, label), ...]."""
    print(f"\n{title}")
    keys = []
    for key, label in options:
        keys.append(str(key))
        print(f"{key}) {label}")
    raw = input(f"Select [{default}]: ").strip() or str(default)
    if raw in keys:
        return raw
    print(f"Invalid choice, using {default}.")
    return str(default)


def _prompt_keyword_groups(keyword_map):
    keys = list(keyword_map.keys())
    present_groups = []
    for group, label in KEYWORD_GROUP_LABELS.items():
        names = [kw for kw in KEYWORD_GROUPS.get(group, []) if kw in keyword_map]
        extra = [kw for kw in keys if keyword_group_for(kw) == group and kw not in names]
        names.extend(extra)
        if names:
            present_groups.append((group, label, names))
    print("\nIndustry groups:")
    labels = [
        f"{label} ({len(names)})" for _group, label, names in present_groups
    ]
    print(_format_numbered_items_horizontal(labels))
    raw = input(
        "Enter group numbers or ranges (e.g. 1-3,5), or Enter for all groups: "
    ).strip()
    indices = _parse_index_selection(raw, len(present_groups))
    chosen = present_groups if indices is None else [
        present_groups[i] for i in indices
    ]
    selected = []
    seen = set()
    for _group, _label, names in chosen:
        for kw in names:
            if kw not in seen:
                seen.add(kw)
                selected.append(kw)
    return selected or list(keys)


def _prompt_keyword_numbers(keyword_map):
    keys = list(keyword_map.keys())
    print("\n--- Keywords ---")
    print(_format_numbered_items_horizontal(keys))
    raw = input(
        "Enter numbers/ranges (e.g. 1-8,12) or press Enter for all: "
    ).strip()
    indices = _parse_index_selection(raw, len(keys))
    if indices is None:
        return list(keys)
    return [keys[i] for i in indices] or list(keys)


def _prompt_keyword_search(keyword_map):
    keys = list(keyword_map.keys())
    needle = input("Search text (matches keyword names): ").strip().lower()
    if not needle:
        print("No search text; using all keywords.")
        return list(keys)
    matches = [kw for kw in keys if needle in kw.lower()]
    if not matches:
        print("No keywords matched; using all.")
        return list(keys)
    print(f"\nMatched {len(matches)} keyword(s):")
    print(_format_numbered_items_horizontal(matches))
    raw = input("Enter numbers/ranges from this list, or Enter for all matches: ").strip()
    indices = _parse_index_selection(raw, len(matches))
    if indices is None:
        return matches
    return [matches[i] for i in indices] or matches


def _prompt_keywords(keyword_map):
    """Prompt user to select keywords from keywords.json."""
    keys = list(keyword_map.keys())
    print(f"\n--- Keywords ({len(keys)} in keywords.json) ---")
    choice = _prompt_choice(
        "How do you want to choose keywords?",
        [
            ("1", f"All {len(keys)} keywords  (best for volume)"),
            ("2", "By industry group"),
            ("3", "Pick numbers / ranges  (e.g. 1-8,12)"),
            ("4", "Search by name"),
        ],
        default="1",
    )
    if choice == "2":
        selected = _prompt_keyword_groups(keyword_map)
    elif choice == "3":
        selected = _prompt_keyword_numbers(keyword_map)
    elif choice == "4":
        selected = _prompt_keyword_search(keyword_map)
    else:
        selected = list(keys)
    print(f"Selected {len(selected)} keyword(s).")
    return selected


def _prompt_locations_by_state(all_locations):
    by_state = _locations_by_state()
    states = list(by_state.keys())
    print("\nStates:")
    labels = [
        f"{state} ({len(cities)} cities)" for state, cities in by_state.items()
    ]
    print(_format_numbered_items_horizontal(labels))
    raw = input(
        "Enter state numbers, ranges, or codes (e.g. 1-3 or NJ,PA). Enter for all: "
    ).strip()
    if not raw:
        return list(all_locations)
    selected_states = set()
    tokens = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    numeric_raw = ",".join(t for t in tokens if t.isdigit() or "-" in t)
    code_tokens = [t.upper() for t in tokens if not (t.isdigit() or "-" in t)]
    if numeric_raw:
        indices = _parse_index_selection(numeric_raw, len(states))
        if indices is None:
            return list(all_locations)
        selected_states.update(states[i] for i in indices)
    for code in code_tokens:
        if code in by_state:
            selected_states.add(code)
        else:
            print(f"Unknown state '{code}', ignored.")
    if not selected_states:
        print("No states matched; using all locations.")
        return list(all_locations)
    selected = [
        loc for loc in all_locations if loc[0] in selected_states
    ]
    return selected or list(all_locations)


def _prompt_location_numbers(all_locations):
    by_state = _locations_by_state()
    print("\n--- Locations (coords.json) ---")
    index_map = []
    for state, cities in by_state.items():
        print(f"\n{state}:")
        state_items = []
        for city, coords in cities:
            index_map.append((state, city, coords))
            state_items.append(city)
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
    raw = input(
        "\nEnter numbers/ranges (e.g. 1-4,7) or press Enter for all: "
    ).strip()
    indices = _parse_index_selection(raw, len(index_map))
    if indices is None:
        return list(all_locations)
    selected = [index_map[i] for i in indices]
    return selected or list(all_locations)


def _prompt_locations(all_locations):
    """Prompt user to select locations from coords.json."""
    print(f"\n--- Locations ({len(all_locations)} cities in coords.json) ---")
    choice = _prompt_choice(
        "How do you want to choose locations?",
        [
            ("1", f"All {len(all_locations)} cities  (best for volume)"),
            ("2", "By state  (numbers or codes like NJ, PA)"),
            ("3", "Pick cities by number / range"),
        ],
        default="1",
    )
    if choice == "2":
        selected = _prompt_locations_by_state(all_locations)
    elif choice == "3":
        selected = _prompt_location_numbers(all_locations)
    else:
        selected = list(all_locations)
    print(
        f"Selected {len(selected)} location(s): "
        + ", ".join(f"{city}, {state}" for state, city, _ in selected[:12])
        + ("..." if len(selected) > 12 else "")
    )
    return selected


def interactive_select_locations_and_keywords():
    """Return (keywords, locations) from interactive pickers."""
    keywords = _prompt_keywords(KEYWORD_CATEGORIES)
    locations = _prompt_locations(_default_locations())
    return keywords, locations


def interactive_customize_config(base_config=None):
    """Edit persisted defaults from a numbered menu (no keywords/locations)."""
    cfg = base_config or config_from_saved_settings()
    while True:
        print("\n--- Settings (enter a number to change, Enter to save) ---")
        items = [
            ("1", "Leadgen type", normalize_leadgen_type(cfg.leadgen_type)),
            ("2", "Playwright max pages", cfg.playwright_max_pages),
            ("3", "Max results per search", cfg.playwright_max_results_per_search),
            (
                "4",
                "Area expansion",
                normalize_area_expansion(cfg.playwright_area_expansion),
            ),
            ("5", "Skip already searched", cfg.skip_searched),
            ("6", "Search history path", cfg.search_history_path),
            ("7", "Minimum score", cfg.min_score),
            ("8", "Minimum reviews", cfg.min_reviews),
            ("9", "Filter franchises", cfg.filter_franchises),
            ("10", "Objective", cfg.objective),
            ("11", "Require website", cfg.require_website),
            (
                "12",
                (
                    "Lead enrichment (Google/Playwright)"
                    if normalize_leadgen_type(cfg.leadgen_type) == "playwright"
                    else "Lead enrichment (Facebook)"
                ),
                cfg.lead_enrichment,
            ),
            ("13", "Output", cfg.output_mode),
            ("14", "JSON output path", cfg.json_output),
        ]
        width = max(len(label) for _num, label, _val in items)
        for num, label, value in items:
            print(f" {num:>2}) {label:<{width}}  [{value}]")
        raw = input("Change setting [Enter=save & return]: ").strip()
        if not raw:
            return cfg
        if raw == "1":
            cfg.leadgen_type = _prompt_leadgen_type(cfg.leadgen_type)
        elif raw == "2":
            cfg.playwright_max_pages = _prompt_int(
                "Playwright max pages per search",
                cfg.playwright_max_pages,
            )
        elif raw == "3":
            cfg.playwright_max_results_per_search = _prompt_int(
                "Playwright max results per search",
                cfg.playwright_max_results_per_search,
            )
        elif raw == "4":
            cfg.playwright_area_expansion = _prompt_area_expansion(
                cfg.playwright_area_expansion
            )
        elif raw == "5":
            cfg.skip_searched = _prompt_bool(
                "Skip keyword/location searches already in history",
                cfg.skip_searched,
            )
        elif raw == "6":
            cfg.search_history_path = _prompt_text(
                "Search history path",
                cfg.search_history_path,
            )
        elif raw == "7":
            cfg.min_score = _prompt_int("Minimum score", cfg.min_score)
        elif raw == "8":
            cfg.min_reviews = _prompt_int("Minimum review count", cfg.min_reviews)
        elif raw == "9":
            cfg.filter_franchises = _prompt_bool(
                "Filter out franchises/chains",
                cfg.filter_franchises,
            )
        elif raw == "10":
            cfg.objective = _prompt_objective(cfg.objective)
        elif raw == "11":
            cfg.require_website = _prompt_bool("Require website", cfg.require_website)
        elif raw == "12":
            enrich_prompt = (
                "Lead enrichment (Google search + website/SEO research)"
                if normalize_leadgen_type(cfg.leadgen_type) == "playwright"
                else "Lead enrichment (find missing emails on Facebook)"
            )
            cfg.lead_enrichment = _prompt_bool(enrich_prompt, cfg.lead_enrichment)
        elif raw == "13":
            cfg.output_mode = _prompt_output_mode(cfg.output_mode)
        elif raw == "14":
            cfg.json_output = _prompt_text("JSON output path", cfg.json_output)
        else:
            print("Enter a setting number from the list, or press Enter to save.")


def _print_volume_estimate(config):
    stats = estimate_discovery_volume(config)
    print("\n--- Volume estimate ---")
    print(
        f"  {stats['keywords']} keywords x {stats['locations']} cities"
        + (
            f" x {stats['areas_per_search']} map cells"
            if stats["leadgen_type"] == "playwright"
            else ""
        )
        + f" = {stats['searches']} searches"
    )
    print(
        f"  Typical unique businesses: {stats['unique_low']:,}-{stats['unique_high']:,}"
    )
    print(
        "  After quality filters, expect hundreds of leads from a few cities, "
        "or thousands from many keywords x many cities."
    )
    if stats["searches"] >= 200:
        print(
            "  Note: Playwright volume runs can take hours; skip-searched "
            "lets you resume later."
        )


def _print_config_summary(config, include_run_scope=True):
    print("\n--- Configuration ---")
    print(f"  Leadgen type:      {normalize_leadgen_type(config.leadgen_type)}")
    if normalize_leadgen_type(config.leadgen_type) == "playwright":
        print(f"  Playwright pages:  {config.playwright_max_pages}")
        print(
            f"  Playwright max:    {config.playwright_max_results_per_search} results/search"
        )
        print(
            f"  Area expansion:    {normalize_area_expansion(config.playwright_area_expansion)}"
        )
    print(f"  Skip searched:     {config.skip_searched}")
    print(f"  Search history:    {config.search_history_path}")
    print(f"  Min score:         {config.min_score}")
    print(f"  Min reviews:       {config.min_reviews}")
    print(f"  Filter franchises: {config.filter_franchises}")
    print(f"  Objective:         {config.objective}")
    print(f"  Require website:   {config.require_website}")
    print(f"  Lead enrichment:   {config.lead_enrichment}")
    print(f"  Output:            {config.output_mode}")
    print(f"  JSON path:         {config.json_output}")
    if include_run_scope:
        print(f"  Keywords ({len(config.keywords)}): {', '.join(config.keywords)}")
        locs = ", ".join(f"{city}, {state}" for state, city, _ in config.locations)
        print(f"  Locations ({len(config.locations)}): {locs}")
        _print_volume_estimate(config)
    print()


def interactive_run_config():
    """Load saved defaults, prompt keywords/locations, return config or None if cancelled."""
    cfg = config_from_saved_settings()
    while True:
        cfg.keywords, cfg.locations = interactive_select_locations_and_keywords()
        _print_config_summary(cfg)
        confirm = input(
            "Run with these settings? [Y/n/s=settings]: "
        ).strip().lower()
        if confirm in ("n", "no"):
            return None
        if confirm in ("s", "settings"):
            cfg = interactive_customize_config(cfg)
            save_settings(cfg)
            continue
        return cfg


def interactive_main_menu():
    """Show startup menu and return a LeadgenConfig, or None to exit."""
    while True:
        cfg_preview = config_from_saved_settings()
        leadgen_type = normalize_leadgen_type(cfg_preview.leadgen_type)
        print("\n=== Lead Generation ===")
        print(
            f"  Current: {leadgen_type} | objective={cfg_preview.objective} | "
            f"min score {cfg_preview.min_score} | output {cfg_preview.output_mode}"
        )
        if leadgen_type == "playwright":
            print(
                f"  Playwright: {cfg_preview.playwright_max_pages} pages, "
                f"{cfg_preview.playwright_max_results_per_search} max/search, "
                f"expansion={normalize_area_expansion(cfg_preview.playwright_area_expansion)}"
            )
        print()
        print("1) Run (choose keywords & locations)")
        print("2) Settings (save defaults, do not run)")
        print("3) High-volume preset (Playwright, area expansion, no Facebook enrich)")
        print("4) Exit")
        print("5) Lead Search (micro-niche intent search)")
        choice = input("Select [1]: ").strip() or "1"
        if choice == "5":
            from niche_search import interactive_niche_search
            interactive_niche_search(cfg_preview)
            continue
        if choice == "4":
            return None
        if choice == "2":
            cfg = interactive_customize_config()
            save_settings(cfg)
            _print_config_summary(cfg, include_run_scope=False)
            print(f"Defaults saved to {SETTINGS_PATH.name}. Returning to menu.")
            continue
        if choice == "3":
            cfg = apply_high_volume_preset(config_from_saved_settings())
            save_settings(cfg)
            print("\nApplied high-volume Playwright preset.")
            _print_config_summary(cfg, include_run_scope=False)
            go = input("Choose keywords & locations and run now? [Y/n]: ").strip().lower()
            if go in ("n", "no"):
                print(f"Defaults saved to {SETTINGS_PATH.name}. Returning to menu.")
                continue
            return interactive_run_config()
        if choice == "1":
            return interactive_run_config()
        print("Invalid choice. Please select 1, 2, 3, 4, or 5.")


def parse_args():
    parser = argparse.ArgumentParser(description="Local business lead generation")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Skip interactive menu and use defaults",
    )
    parser.add_argument(
        "--leadgen-type",
        choices=list(VALID_LEADGEN_TYPES),
        default=None,
        help=(
            "Business discovery provider: playwright (browser Maps search) or "
            f"api_manager (Google Places API; default {DEFAULT_LEADGEN_TYPE})"
        ),
    )
    parser.add_argument(
        "--playwright-max-pages",
        type=int,
        default=None,
        help=(
            "Max result pages to process per keyword/location in Playwright mode "
            f"(default {DEFAULT_PLAYWRIGHT_MAX_PAGES})"
        ),
    )
    parser.add_argument(
        "--playwright-max-results-per-search",
        type=int,
        default=None,
        help=(
            "Max businesses to collect per keyword/location in Playwright mode "
            f"(default {DEFAULT_PLAYWRIGHT_MAX_RESULTS_PER_SEARCH})"
        ),
    )
    parser.add_argument(
        "--playwright-area-expansion",
        choices=list(VALID_AREA_EXPANSIONS),
        default=None,
        help=(
            "Extra map cells around each city to break Maps' ~120 result cap: "
            "off, light (~5 cells), or dense (~9 cells)"
        ),
    )
    parser.add_argument(
        "--skip-searched",
        dest="skip_searched",
        action="store_true",
        default=None,
        help="Skip keyword/location combos already recorded in search history (default)",
    )
    parser.add_argument(
        "--force-research",
        dest="skip_searched",
        action="store_false",
        help="Re-run searches even if they appear in search history",
    )
    parser.add_argument(
        "--search-history-path",
        default=None,
        help=f"Path to search history JSON (default {DEFAULT_HISTORY_PATH})",
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
        help="Run post-scrape enrichment (Facebook in API mode, Google/Playwright in Playwright mode; default on)",
    )
    parser.add_argument(
        "--no-lead-enrichment",
        dest="lead_enrichment",
        action="store_false",
        help="Skip post-scrape enrichment",
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
    parser.add_argument(
        "--state",
        action="append",
        help="State code filter (repeatable); matches coords.json keys like NJ, PA",
    )
    parser.add_argument(
        "--niche",
        help="Run Niche Lead Search for this niche id or display name",
    )
    parser.add_argument(
        "--review-leads",
        action="store_true",
        help="Open the Niche Lead Search results reviewer (no new search)",
    )
    parser.add_argument(
        "--zip",
        action="append",
        dest="zips",
        help="ZIP code to include in a niche search (repeatable)",
    )
    parser.add_argument(
        "--radius",
        type=int,
        help="Niche search radius in meters (default 50000)",
    )
    parser.add_argument(
        "--max-leads",
        type=int,
        help="Cap ranked niche leads after scoring",
    )
    parser.add_argument(
        "--min-rating",
        type=float,
        help="Minimum Google rating for niche search",
    )
    parser.add_argument(
        "--exclude-strong-websites",
        action="store_true",
        default=None,
        help="Drop niche leads with a strong current website",
    )
    parser.add_argument(
        "--require-social",
        action="store_true",
        default=None,
        help="Require a Facebook or Instagram URL on niche leads",
    )
    parser.add_argument(
        "--require-no-website",
        action="store_true",
        default=None,
        help="Keep only niche leads with no usable website",
    )
    parser.add_argument(
        "--require-website-issue",
        action="store_true",
        default=None,
        help="Keep only niche leads whose website quality is poor/critical",
    )
    parser.add_argument(
        "--require-active-business",
        dest="require_active_business",
        action="store_true",
        default=None,
        help="Drop closed businesses in niche search (default on)",
    )
    parser.add_argument(
        "--allow-inactive-business",
        dest="require_active_business",
        action="store_false",
        help="Allow closed/unknown businesses in niche search",
    )
    parser.add_argument(
        "--website-requirement",
        choices=["any", "none", "weak_or_none", "issue"],
        default=None,
        help="Niche website filter: any, none, weak_or_none, or issue",
    )
    parser.add_argument(
        "--extra-keywords",
        nargs="+",
        help="Additional niche search queries",
    )
    return parser.parse_args()


def _has_cli_overrides(args):
    return any([
        args.defaults,
        args.leadgen_type is not None,
        args.playwright_max_pages is not None,
        args.playwright_max_results_per_search is not None,
        args.playwright_area_expansion is not None,
        args.skip_searched is not None,
        args.search_history_path is not None,
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
        args.state is not None,
    ])


def config_from_args(args):
    """Build LeadgenConfig from saved defaults plus argparse overrides."""
    config = config_from_saved_settings()
    if args.leadgen_type is not None:
        config.leadgen_type = normalize_leadgen_type(args.leadgen_type)
    if args.playwright_max_pages is not None:
        config.playwright_max_pages = max(1, int(args.playwright_max_pages))
    if args.playwright_max_results_per_search is not None:
        config.playwright_max_results_per_search = max(
            1, int(args.playwright_max_results_per_search)
        )
    if args.playwright_area_expansion is not None:
        config.playwright_area_expansion = normalize_area_expansion(
            args.playwright_area_expansion
        )
    if args.skip_searched is not None:
        config.skip_searched = bool(args.skip_searched)
    if args.search_history_path is not None:
        config.search_history_path = str(args.search_history_path)
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
    locations = _default_locations()
    if args.state is not None:
        state_names = set()
        for entry in args.state:
            for part in entry.split(","):
                part = part.strip().upper()
                if part:
                    state_names.add(part)
        locations = [loc for loc in locations if loc[0].upper() in state_names]
        if not locations:
            logger.warning("No states matched --state filter; using all locations")
            locations = _default_locations()
    if args.city is not None:
        city_names = set()
        for entry in args.city:
            for part in entry.split(","):
                part = part.strip()
                if part:
                    city_names.add(part.lower())
        filtered = [
            loc for loc in locations
            if loc[1].lower() in city_names
        ]
        if filtered:
            locations = filtered
        else:
            logger.warning("No cities matched --city filter; using current location set")
    if args.state is not None or args.city is not None:
        config.locations = locations
    return config


def resolve_config(args):
    """Resolve final config from CLI flags and/or interactive menu."""
    if args.defaults:
        return config_from_args(args)
    if _has_cli_overrides(args):
        return config_from_args(args)
    return interactive_main_menu()


def _print_playwright_mode_banner(config):
    max_pages = config.playwright_max_pages
    print()
    print("Lead generation mode: Playwright")
    print(
        "Playwright mode uses browser-based business discovery instead of the API Manager."
    )
    print(
        "This can significantly reduce API usage and associated costs, but individual searches"
    )
    print(
        "may take longer because the browser is loading and processing search results."
    )
    print("Multi-page search is enabled.")
    print(f"Max pages per search: {max_pages}")
    print(
        f"Max results per search: {config.playwright_max_results_per_search}"
    )
    print(
        f"Area expansion: {normalize_area_expansion(config.playwright_area_expansion)}"
    )
    print()
    logger.critical(
        "Lead generation mode: Playwright (max_pages=%s, max_results_per_search=%s, expansion=%s)",
        max_pages,
        config.playwright_max_results_per_search,
        normalize_area_expansion(config.playwright_area_expansion),
    )


def _print_run_summary(stats):
    print()
    print("Lead Generation Complete")
    print(f"Mode: {stats.get('mode', '')}")
    print(f"Searches performed: {stats.get('searches_performed', 0)}")
    print(f"Searches skipped (history): {stats.get('searches_skipped', 0)}")
    print(f"Locations searched: {stats.get('locations_searched', 0)}")
    print(f"Pages processed: {stats.get('pages_processed', 0)}")
    print(f"Businesses discovered: {stats.get('businesses_discovered', 0)}")
    print(f"Duplicates removed: {stats.get('duplicates_removed', 0)}")
    print(f"Unique businesses: {stats.get('unique_businesses', 0)}")
    print(f"Businesses with websites: {stats.get('with_website', 0)}")
    print(f"Businesses without websites: {stats.get('without_website', 0)}")
    print(f"Qualified leads: {stats.get('qualified_leads', 0)}")
    print(f"API Manager calls used: {stats.get('api_manager_calls', 0)}")
    print()
    logger.critical(
        "Summary mode=%s performed=%s skipped=%s discovered=%s unique=%s "
        "qualified=%s api_calls=%s",
        stats.get("mode"),
        stats.get("searches_performed"),
        stats.get("searches_skipped"),
        stats.get("businesses_discovered"),
        stats.get("unique_businesses"),
        stats.get("qualified_leads"),
        stats.get("api_manager_calls"),
    )


def _load_contacted_emails():
    if os.path.exists(CONTACTED_FILE):
        with open(CONTACTED_FILE, "r", encoding="utf-8") as f:
            return set(line.strip().lower() for line in f if line.strip())
    return set()


def gather_leads_api_manager(
    config,
    contacted_emails,
    existing_place_ids,
    api_call_counter,
    history=None,
):
    """Existing Google Places Nearby Search + Place Details discovery path."""
    history = history or SearchHistory(config.search_history_path)
    total_rows = []
    discovered = 0
    searches_performed = 0
    searches_skipped = 0
    locations_touched = set()

    log_stage(3, "Discovery", "API Manager (Google Places)")
    for state, city, coords in config.locations:
        try:
            pending, skipped = history.pending_keywords_for_location(
                config.keywords,
                city,
                state,
                leadgen_type="api_manager",
                search_radius=config.search_radius,
                skip_searched=config.skip_searched,
            )
            for prior in skipped:
                searches_skipped += 1
                log_step(
                    3,
                    1,
                    "Skip searched",
                    f"{prior.get('keyword')} × {city}, {state} "
                    f"(last completed {prior.get('completed_at')})",
                )
            if not pending:
                log_step(
                    3,
                    2,
                    "Location complete",
                    f"{city}, {state} — all keywords already in history",
                )
                continue

            locations_touched.add(f"{city}, {state}")
            log_step(
                3,
                3,
                "Location search",
                f"{city}, {state} coords={coords} keywords={len(pending)}",
            )
            places = get_places(
                coords,
                config.search_radius,
                pending,
                GOOGLE_API_KEY,
                api_call_counter=api_call_counter,
            )
            # Count one completed search unit per pending keyword for this location.
            for keyword in pending:
                found_for_kw = sum(1 for p in places if p.get("niche_key") == keyword)
                history.record_search(
                    leadgen_type="api_manager",
                    keyword=keyword,
                    city=city,
                    state=state,
                    search_radius=config.search_radius,
                    businesses_found=found_for_kw,
                    status="completed",
                )
                searches_performed += 1

            for place in places:
                place["location_searched"] = f"{city}, {state}"
                place["source"] = "api_manager"
            discovered += len(places)
            if not places:
                logger.critical(
                    "[STEP 3.4] No places found for %s, %s; moving on",
                    city,
                    state,
                )
                continue

            log_stage(4, "Qualify & analyze", f"{len(places)} businesses from {city}, {state}")
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
                fetch_details=True,
                source="api_manager",
                api_call_counter=api_call_counter,
            )
            total_rows.extend(rows)
        except Exception as e:
            logger.error("Error processing businesses for %s, %s: %s", city, state, e)
            continue

    history.save()
    with_website = sum(1 for row in total_rows if (row.get("website") or "").strip())
    stats = {
        "mode": "API Manager",
        "searches_performed": searches_performed,
        "searches_skipped": searches_skipped,
        "locations_searched": len(locations_touched),
        "pages_processed": api_call_counter.get("places_nearby", 0),
        "businesses_discovered": discovered,
        "duplicates_removed": max(0, discovered - len({r.get("place_id") for r in total_rows})),
        "unique_businesses": len({r.get("place_id") for r in total_rows if r.get("place_id")}),
        "with_website": with_website,
        "without_website": max(0, len(total_rows) - with_website),
        "qualified_leads": len(total_rows),
        "api_manager_calls": (
            api_call_counter.get("places_nearby", 0)
            + api_call_counter.get("places_details", 0)
        ),
    }
    return total_rows, stats


def gather_leads_playwright(
    config,
    contacted_emails,
    existing_identities,
    api_call_counter,
    history=None,
):
    """Browser-based Google Maps discovery path (no Places API calls)."""
    history = history or SearchHistory(config.search_history_path)
    stubs = []
    session = BusinessDiscoverySession()
    locations_searched = set()
    discovery_stats = {}
    duplicates_removed = 0
    unique = []
    searches_performed = 0
    searches_skipped = 0

    log_stage(3, "Discovery", "Playwright (Google Maps)")
    try:
        for state, city, _coords in config.locations:
            pending, skipped = history.pending_keywords_for_location(
                config.keywords,
                city,
                state,
                leadgen_type="playwright",
                playwright_max_pages=config.playwright_max_pages,
                playwright_area_expansion=config.playwright_area_expansion,
                skip_searched=config.skip_searched,
            )
            for prior in skipped:
                searches_skipped += 1
                log_step(
                    3,
                    1,
                    "Skip searched",
                    f"{prior.get('keyword')} × {city}, {state} "
                    f"(last completed {prior.get('completed_at')})",
                )
            if not pending:
                continue

            locations_searched.add(f"{city}, {state}")
            for keyword in pending:
                try:
                    log_step(3, 2, "Maps search", f"{keyword} × {city}, {state}")
                    listings = session.search_location(
                        keyword,
                        city,
                        state,
                        coords=_coords,
                        max_pages=config.playwright_max_pages,
                        max_results=config.playwright_max_results_per_search,
                        area_expansion=config.playwright_area_expansion,
                    )
                    if session.google_blocked and not listings:
                        logger.error(
                            "[Playwright] Search blocked for %s / %s, %s; not recording history",
                            keyword,
                            city,
                            state,
                        )
                        break
                    history.record_search(
                        leadgen_type="playwright",
                        keyword=keyword,
                        city=city,
                        state=state,
                        playwright_max_pages=config.playwright_max_pages,
                        playwright_area_expansion=config.playwright_area_expansion,
                        businesses_found=len(listings),
                        status="completed",
                    )
                    searches_performed += 1
                    for stub in listings:
                        entry = dict(stub)
                        entry["niche_key"] = keyword
                        entry["search_term"] = keyword
                        entry["location_searched"] = f"{city}, {state}"
                        entry["source"] = "playwright"
                        if not entry.get("place_id"):
                            entry["place_id"] = extract_place_id_from_url(
                                entry.get("profile_url")
                            )
                        stubs.append(entry)
                except Exception as exc:
                    logger.error(
                        "[Playwright] Search failed for %s / %s, %s: %s",
                        keyword,
                        city,
                        state,
                        exc,
                    )
                    continue
                if session.google_blocked:
                    logger.error("[Playwright] Stopping remaining searches after block page")
                    break
            if session.google_blocked:
                break

        history.save()
        unique_stubs, duplicates_removed = dedupe_businesses(stubs)
        logger.critical(
            "[STEP 3.3] After discovery dedupe: %d unique (removed %d)",
            len(unique_stubs),
            duplicates_removed,
        )

        log_step(3, 4, "Open place panels", f"{len(unique_stubs)} listings")
        discovered = []
        details_needed = 0
        for index, stub in enumerate(unique_stubs, 1):
            if session.google_blocked:
                discovered.append(stub)
                continue
            needs_detail = listing_needs_detail(stub, config)
            if not needs_detail:
                entry = dict(stub)
                entry["source"] = stub.get("source") or "playwright"
                discovered.append(entry)
                continue
            details_needed += 1
            if details_needed == 1 or index % 10 == 0 or index == len(unique_stubs):
                log_step(
                    3,
                    4,
                    "Detail progress",
                    f"{index}/{len(unique_stubs)} {stub.get('business_name')}",
                )
            try:
                entry = session.enrich_listing(stub)
            except Exception as exc:
                logger.error(
                    "[Playwright] Enrich failed for %s: %s",
                    stub.get("business_name"),
                    exc,
                )
                entry = dict(stub)
            entry["niche_key"] = stub.get("niche_key")
            entry["search_term"] = stub.get("search_term") or stub.get("niche_key")
            entry["location_searched"] = stub.get("location_searched")
            entry["source"] = "playwright"
            if not entry.get("place_id"):
                entry["place_id"] = extract_place_id_from_url(entry.get("profile_url"))
            discovered.append(entry)
        skipped_details = len(unique_stubs) - details_needed
        if skipped_details:
            logger.critical(
                "[STEP 3.4] Skipped %d detail pages (card already had required fields)",
                skipped_details,
            )

        unique, _ = dedupe_businesses(discovered)
    finally:
        discovery_stats = dict(session.stats)
        session.close()

    # Group by location so email discovery still gets city/state context.
    by_location = {}
    for entry in unique:
        loc = entry.get("location_searched") or ""
        by_location.setdefault(loc, []).append(entry)

    total_rows = []
    if unique:
        log_stage(4, "Qualify & analyze", f"{len(unique)} unique businesses")
    for loc, businesses in by_location.items():
        city = state = None
        if "," in loc:
            city_part, state_part = loc.rsplit(",", 1)
            city = city_part.strip()
            state = state_part.strip()
        try:
            log_step(4, 1, "Process location batch", f"{loc} ({len(businesses)} businesses)")
            rows = process_businesses(
                businesses,
                api_key=None,
                existing_ids=set(),
                contacted_emails=contacted_emails,
                min_score=config.min_score,
                max_workers=config.max_workers,
                filter_franchises=config.filter_franchises,
                min_reviews=config.min_reviews,
                require_website=config.require_website,
                objective=config.objective,
                city=city,
                state=state,
                fetch_details=False,
                existing_identities=existing_identities,
                source="playwright",
                api_call_counter=api_call_counter,
            )
            total_rows.extend(rows)
        except Exception as exc:
            logger.error("[Playwright] Processing failed for %s: %s", loc, exc)
            continue

    with_website = sum(1 for b in unique if (b.get("website") or "").strip())
    stats = {
        "mode": "Playwright",
        "searches_performed": searches_performed,
        "searches_skipped": searches_skipped,
        "locations_searched": len(locations_searched),
        "pages_processed": discovery_stats.get("pages_processed", 0),
        "businesses_discovered": len(stubs),
        "duplicates_removed": duplicates_removed,
        "unique_businesses": len(unique),
        "with_website": with_website,
        "without_website": max(0, len(unique) - with_website),
        "qualified_leads": len(total_rows),
        "api_manager_calls": (
            api_call_counter.get("places_nearby", 0)
            + api_call_counter.get("places_details", 0)
        ),
    }
    return total_rows, stats


def run_leadgen(config):
    """Run lead generation with the given configuration."""
    from datetime import datetime, timezone

    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    leadgen_type = normalize_leadgen_type(config.leadgen_type)
    config.leadgen_type = leadgen_type

    log_stage(
        1,
        "Initialize",
        f"mode={leadgen_type} objective={config.objective} "
        f"skip_searched={config.skip_searched}",
    )

    if leadgen_type == "api_manager":
        if not GOOGLE_API_KEY or GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY":
            logger.error("Please set GOOGLE_API_KEY in .env before running.")
            return
    elif leadgen_type == "playwright":
        _print_playwright_mode_banner(config)
    else:
        raise ValueError(f"Unsupported leadgen_type: {leadgen_type}")

    if config.output_mode in ("dashboard", "both") and not os.getenv("LEAD_INGEST_KEY"):
        logger.error("LEAD_INGEST_KEY is required for dashboard output mode.")
        return

    log_stage(2, "Load prior state")
    log_step(2, 1, "Load contacted emails", CONTACTED_FILE)
    contacted_emails = _load_contacted_emails()
    log_step(2, 2, "Contacted emails loaded", f"{len(contacted_emails)} addresses")

    log_step(2, 3, "Load existing leads", config.json_output)
    existing_place_ids = load_existing_place_ids(config.json_output)
    existing_identities = load_existing_identities(config.json_output)
    log_step(
        2,
        4,
        "Existing lead identities",
        f"{len(existing_place_ids)} place_ids / {len(existing_identities)} identity keys",
    )

    log_step(2, 5, "Load search history", config.search_history_path)
    history = SearchHistory(config.search_history_path)
    prior_searches = len(history._data.get("searches") or {})
    log_step(
        2,
        6,
        "Search history ready",
        f"{prior_searches} prior searches; skip_searched={config.skip_searched}",
    )

    api_call_counter = {"places_nearby": 0, "places_details": 0}

    if leadgen_type == "playwright":
        total_rows, stats = gather_leads_playwright(
            config,
            contacted_emails,
            existing_identities,
            api_call_counter,
            history=history,
        )
    else:
        total_rows, stats = gather_leads_api_manager(
            config,
            contacted_emails,
            existing_place_ids,
            api_call_counter,
            history=history,
        )

    if not total_rows:
        logger.critical("[STAGE] No qualifying leads found after discovery/filters.")
        log_stage(6, "Output", "skipped — nothing to save")
        log_stage(7, "Finalize")
        history.record_run({
            "started_at": started_at,
            "leadgen_type": leadgen_type,
            "stats": stats,
            "keywords": list(config.keywords),
            "locations": [f"{city}, {state}" for state, city, _ in config.locations],
        })
        history.save()
        if leadgen_type == "api_manager":
            update_usage_stats(
                nearby_calls=api_call_counter.get("places_nearby", 0),
                details_calls=api_call_counter.get("places_details", 0),
            )
        _print_run_summary(stats)
        return

    logger.critical(
        "[STAGE 4 complete] Found %d qualifying leads (min score %d)",
        len(total_rows),
        config.min_score,
    )

    if config.lead_enrichment:
        enriched = enrich_missing_emails(total_rows, leadgen_type=leadgen_type)
        if enriched and contacted_emails:
            kept = [row for row in total_rows if not _is_contacted(row, contacted_emails)]
            if len(kept) != len(total_rows):
                log_step(
                    5,
                    3,
                    "Drop contacted after enrichment",
                    f"{len(total_rows) - len(kept)} leads already in {CONTACTED_FILE}",
                )
                total_rows = kept
        stats["qualified_leads"] = len(total_rows)
    else:
        log_stage(5, "Lead enrichment", "skipped by configuration")

    log_stage(6, "Output", config.output_mode)
    if config.output_mode in ("json", "both"):
        log_step(6, 1, "Save JSON", config.json_output)
        save_results(total_rows, config.json_output)

    if config.output_mode in ("dashboard", "both"):
        log_step(6, 2, "Dashboard bulk ingest", f"{len(total_rows)} leads")
        send_to_dashboard(total_rows)

    log_stage(7, "Finalize")
    history.record_run({
        "started_at": started_at,
        "leadgen_type": leadgen_type,
        "stats": stats,
        "keywords": list(config.keywords),
        "locations": [f"{city}, {state}" for state, city, _ in config.locations],
        "qualified_leads": len(total_rows),
    })
    history.save()
    log_step(7, 1, "Search history updated", config.search_history_path)

    if leadgen_type == "api_manager":
        usage = update_usage_stats(
            nearby_calls=api_call_counter.get("places_nearby", 0),
            details_calls=api_call_counter.get("places_details", 0),
        )
        log_step(
            7,
            2,
            "API usage updated",
            f"{DEFAULT_USAGE_PATH} total_calls={usage.get('total_calls')}",
        )

    _print_run_summary(stats)


def main():
    args = parse_args()
    if getattr(args, "review_leads", False):
        from niche_results import review_leads
        review_leads(json_path=args.json_path or "niche_leads_output.json")
        return
    if getattr(args, "niche", None):
        from niche_search import (
            config_from_leadgen,
            expand_locations,
            run_niche_search,
        )
        base = config_from_args(args)
        locations = expand_locations(
            states=args.state,
            cities=args.city,
            zips=getattr(args, "zips", None),
            api_key=GOOGLE_API_KEY,
        )
        niche_config = config_from_leadgen(
            base,
            args.niche,
            extra={
                "locations": locations,
                "extra_keywords": args.extra_keywords or [],
                "search_radius": args.radius if args.radius is not None else base.search_radius,
                "max_leads": args.max_leads or 0,
                "min_reviews": args.min_reviews if args.min_reviews is not None else None,
                "min_rating": args.min_rating or 0,
                "min_score": args.min_score if args.min_score is not None else None,
                "filter_franchises": (
                    args.filter_franchises
                    if args.filter_franchises is not None
                    else base.filter_franchises
                ),
                "exclude_strong_websites": bool(args.exclude_strong_websites),
                "require_phone": bool(args.require_phone),
                "require_email": bool(args.require_email),
                "require_social": bool(args.require_social),
                "require_no_website": bool(args.require_no_website),
                "require_website_issue": bool(args.require_website_issue),
                "require_active_business": (
                    True
                    if args.require_active_business is None
                    else bool(args.require_active_business)
                ),
                "website_requirement": args.website_requirement or (
                    "weak_or_none" if args.exclude_strong_websites else "any"
                ),
                "json_output": args.json_path or "niche_leads_output.json",
                "open_reviewer": False,
            },
        )
        run_niche_search(niche_config)
        return
    config = resolve_config(args)
    if config is None:
        print("Exiting.")
        return
    run_leadgen(config)


if __name__ == "__main__":
    main()
