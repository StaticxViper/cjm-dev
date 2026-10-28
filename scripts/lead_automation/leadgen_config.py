#!/usr/bin/env python3
"""
leadgen configuration, constants, and objective helpers.

Executed into leadgen.py. Run the tool with: python leadgen.py
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
from helper_scripts.http.client import html_headers, requests_get
from helper_scripts.text.phones import is_valid_us_phone
from helper_scripts.utils.logger.logger import setup_logger
from helper_scripts.web.html_signals import has_title_tag, has_viewport, text_has_keywords
from helper_scripts.web.urls import ensure_http_url
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

_LEADGEN_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = _LEADGEN_DIR / "leadgen_settings.json"


def _load_optional_json(path, fallback):
    """Load a JSON object. Missing keyword presets must not block a search."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return fallback
    if not isinstance(data, type(fallback)):
        return fallback
    return data


KEYWORD_CATEGORIES = _load_optional_json(_LEADGEN_DIR / "keywords.json", {})
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
FETCH_HEADERS = html_headers()
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
    "discovery_mode",
    "nb_max_age_days",
    "nb_very_new_days",
    "nb_min_score",
    "nb_website_check",
    "nb_csv_output",
    "nb_max_records_per_source",
    "nb_score_rules_path",
    "nb_regions_file",
    "nb_sources",
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
    discovery_mode: str = "standard"
    nb_max_age_days: int = 365
    nb_very_new_days: int = 90
    nb_min_score: int = 50
    nb_website_check: str = "deep"
    nb_csv_output: str = "new_business_leads.csv"
    nb_max_records_per_source: int = 200
    nb_score_rules_path: str = "new_business_score_rules.json"
    nb_regions_file: str = "geo_regions.json"
    nb_sources: str = ""
    nb_counties: list = field(default_factory=list)
    nb_region: str = ""
    nb_zips: list = field(default_factory=list)
    nb_dry_run: bool = False
    nb_refresh_enrichment: bool = False
    nb_include_seen: bool = False
    nb_headful: bool = False
    nb_artifacts: bool = True
    nb_seen_path: str = "new_business_seen.json"
    nb_enrichment_cache_path: str = "new_business_enrichment_cache.json"
    nb_enrichment_ttl_days: int = 30
    niches: list = field(default_factory=list)
    exact_queries: bool = False
    csv_output: str = ""


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
    if (
        data.get("output_mode") == "csv"
        and data.get("discovery_mode", "standard") != "new-business"
    ):
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
        "discovery_mode": config.discovery_mode if config.discovery_mode in ("standard", "new-business") else "standard",
        "nb_max_age_days": int(config.nb_max_age_days),
        "nb_very_new_days": int(config.nb_very_new_days),
        "nb_min_score": int(config.nb_min_score),
        "nb_website_check": config.nb_website_check if config.nb_website_check in ("none", "cheap", "deep") else "deep",
        "nb_csv_output": config.nb_csv_output,
        "nb_max_records_per_source": int(config.nb_max_records_per_source),
        "nb_score_rules_path": config.nb_score_rules_path,
        "nb_regions_file": config.nb_regions_file,
        "nb_sources": config.nb_sources or "",
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
    if "output_mode" in saved and saved["output_mode"] in ("json", "dashboard", "both", "csv"):
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
    if saved.get("discovery_mode") in ("standard", "new-business"):
        config.discovery_mode = saved["discovery_mode"]
    for key in ("nb_max_age_days", "nb_very_new_days", "nb_min_score", "nb_max_records_per_source"):
        if key in saved:
            try:
                setattr(config, key, int(saved[key]))
            except (TypeError, ValueError):
                pass
    if saved.get("nb_website_check") in ("none", "cheap", "deep"):
        config.nb_website_check = saved["nb_website_check"]
    for key in ("nb_csv_output", "nb_score_rules_path", "nb_regions_file", "nb_sources"):
        if saved.get(key):
            setattr(config, key, str(saved[key]))
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
    exact = bool(getattr(config, "exact_queries", False))
    pairs = n_kw if exact else n_kw * n_loc
    searches = pairs * areas
    # Maps typically returns 40–120 unique listings per query; area overlap is high.
    per_query_low = 40 if leadgen_type == "playwright" else 20
    per_query_high = 120 if leadgen_type == "playwright" else 60
    discovered_low = searches * per_query_low
    discovered_high = searches * per_query_high
    # Unique after cross-city overlap, then quality filters (~20–50% keep).
    unique_low = max(pairs * 15, int(discovered_low * 0.15))
    unique_high = max(unique_low, int(discovered_high * 0.45))
    return {
        "keywords": n_kw,
        "locations": n_loc,
        "areas_per_search": areas,
        "searches": searches,
        "exact_queries": exact,
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


