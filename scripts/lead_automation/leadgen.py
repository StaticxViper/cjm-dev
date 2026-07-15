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
import pandas as pd
import re
import time
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from helper_scripts.utils.logger.logger import setup_logger
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import os
from dotenv import load_dotenv
from leadfilter import load_existing_place_ids, is_new_place

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
KEYWORD_CATEGORIES = json.load(open(_LEADGEN_DIR / "keywords.json"))
COORDS_DATA = json.load(open(_LEADGEN_DIR / "coords.json"))

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

MIN_USER_RATINGS_TOTAL = 3
REVIEW_MAX_AGE_MONTHS = 18
US_PHONE_RE = re.compile(r"^(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$")
CLOSED_STATUSES = frozenset({"CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"})

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
    min_score: int = 80
    output_mode: str = "csv"
    csv_output: str = "leads_output.csv"
    search_radius: int = 50000
    max_workers: int = 12
    keywords: list = field(default_factory=_default_keywords)
    locations: list = field(default_factory=_default_locations)
    dashboard_bulk: bool = True


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


def passes_quality_filters(entry):
    """Return (passed, reason) for hard quality filters before website scraping."""
    status = entry.get("business_status")
    if status in CLOSED_STATUSES:
        return False, "closed_business"

    try:
        count = int(entry.get("user_ratings_total") or 0)
    except (TypeError, ValueError):
        count = 0
    if count < MIN_USER_RATINGS_TOTAL:
        return False, "low_review_count"

    if not is_valid_us_phone(entry.get("phone_google")):
        return False, "invalid_phone"

    reviews = entry.get("reviews") or []
    if reviews:
        latest = latest_review_timestamp(reviews)
        if latest is not None and is_review_stale(latest):
            return False, "stale_reviews"

    return True, ""


def analyze_website(url):
    """Fetch a website and extract emails, phones, https status, viewport, and basic quality signals."""
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

    if url.startswith("//"):
        url = "https:" + url
    if not urlparse(url).scheme:
        url = "http://" + url

    result["https"] = url.lower().startswith("https://")

    try:
        r = requests.get(url, timeout=10)
        html = r.text or ""
    except Exception as e:
        result["error"] = str(e)
        return result

    result["html_length"] = len(html)
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        result["has_title"] = True

    mv = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "viewport"})
    if mv:
        result["has_viewport"] = True

    emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html))
    filtered = []
    for e in emails:
        low = e.lower()
        if any(low.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg")):
            continue
        if "mailto:" in low:
            low = low.replace("mailto:", "")
        filtered.append(low)
    result["emails"] = sorted(set(filtered))

    phone_matches = re.findall(r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", html)
    cleaned_phones = set()
    for p in phone_matches:
        digits = re.sub(r"[^0-9]", "", p)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            cleaned_phones.add("(+1) {}-{}-{}".format(digits[0:3], digits[3:6], digits[6:10]))
    result["phones_website"] = sorted(cleaned_phones)

    text = soup.get_text(separator=" ").lower()
    cta_keywords = ["call", "contact", "quote", "estimate"]
    result["has_cta"] = any(kw in text for kw in cta_keywords)

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
):
    """Given list of basic business entries, enrich with place details and analyze websites concurrently."""
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
        ok, reason = passes_quality_filters(entry)
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
    for b in businesses_unique:
        place_id = b.get("place_id")
        if not place_id:
            continue

        if not is_new_place(place_id, existing_ids):
            continue

        a = analyses.get(place_id, {})
        emails = a.get("emails") or []
        emails_clean = [e.strip().lower() for e in emails if e and e.strip()]

        if any(email in contacted_emails for email in emails_clean):
            continue

        has_website = bool(b.get("website"))
        has_email = bool(emails_clean)
        lead_score = score_lead(
            has_website,
            a.get("https", False),
            a.get("has_viewport", False),
            a.get("html_length", 0),
            has_email,
            a.get("has_cta", False),
            b.get("rating"),
            b.get("user_ratings_total"),
            b.get("business_status"),
        )

        if lead_score < min_score:
            filtered_below_min += 1
            continue

        row = {
            "business_name": b.get("business_name"),
            "address": b.get("address"),
            "phone_google": b.get("phone_google"),
            "phone_website": ";".join(a.get("phones_website", [])) if a.get("phones_website") else None,
            "email": ";".join(emails_clean),
            "has_email": has_email,
            "website": b.get("website"),
            "rating": b.get("rating"),
            "user_ratings_total": b.get("user_ratings_total"),
            "business_status": b.get("business_status"),
            "https": a.get("https", False),
            "has_viewport": a.get("has_viewport", False),
            "html_length": a.get("html_length", 0),
            "lead_score": lead_score,
            "niche_key": b.get("niche_key"),
        }
        rows.append(row)

    if filtered_below_min:
        logger.info(
            "Filtered %d leads below minimum score %d",
            filtered_below_min,
            min_score,
        )
    return rows


def save_results(rows, csv_path):
    df_new = pd.DataFrame(rows)
    if os.path.exists(csv_path):
        try:
            df_old = pd.read_csv(csv_path)
        except Exception:
            df_old = pd.DataFrame()
        if not df_old.empty:
            combined = pd.concat([df_old, df_new], ignore_index=True)
            if "website" in combined.columns:
                combined = combined.drop_duplicates(subset=["website", "business_name"], keep="first")
            else:
                combined = combined.drop_duplicates(subset=["business_name"], keep="first")
            combined = combined.sort_values(by="lead_score", ascending=False)
            combined.to_csv(csv_path, index=False)
            logger.info("Appended and saved %d total leads to %s", len(combined), csv_path)
            return
    df_new = df_new.sort_values(by="lead_score", ascending=False)
    df_new.to_csv(csv_path, index=False)
    logger.critical("Saved %d leads to %s", len(df_new), csv_path)


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


def _prompt_int(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid number, using default {default}.")
        return default


def _prompt_output_mode(default="csv"):
    labels = {"1": "csv", "2": "dashboard", "3": "both"}
    default_num = {"csv": "1", "dashboard": "2", "both": "3"}[default]
    raw = input(f"Output: 1=CSV  2=Dashboard  3=Both [{default_num}]: ").strip()
    if not raw:
        return default
    return labels.get(raw, default)


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


def _prompt_keywords(keyword_map):
    """Prompt user to select keywords from keywords.json."""
    keys = list(keyword_map.keys())
    print("\n--- Keywords (keywords.json) ---")
    for i, kw in enumerate(keys, 1):
        label = keyword_map[kw]
        print(f"  {i}) {kw}  ->  {label}")
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
    idx = 1
    index_map = []
    for state, cities in by_state.items():
        print(f"\n{state}:")
        for city, coords in cities:
            print(f"  {idx}) {city}")
            index_map.append((state, city, coords))
            idx += 1
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


def interactive_select_config():
    """Build LeadgenConfig with default settings but user-selected locations/keywords."""
    cfg = LeadgenConfig()
    cfg.keywords, cfg.locations = interactive_select_locations_and_keywords()
    return cfg


def interactive_customize_config(base_config=None):
    """Walk through customization prompts and return a LeadgenConfig."""
    cfg = base_config or LeadgenConfig()
    print("\n--- Customize Lead Generation ---")
    cfg.min_score = _prompt_int("Minimum score", cfg.min_score)
    cfg.output_mode = _prompt_output_mode(cfg.output_mode)
    cfg.keywords = _prompt_keywords(KEYWORD_CATEGORIES)
    cfg.locations = _prompt_locations(_default_locations())
    return cfg


def _print_config_summary(config):
    print("\n--- Configuration ---")
    print(f"  Min score:    {config.min_score}")
    print(f"  Output:       {config.output_mode}")
    print(f"  CSV path:     {config.csv_output}")
    print(f"  Keywords:     {', '.join(config.keywords)}")
    locs = ", ".join(f"{city}, {state}" for state, city, _ in config.locations)
    print(f"  Locations:    {locs}")
    print()


def interactive_main_menu():
    """Show startup menu and return a LeadgenConfig, or None to exit."""
    print("\n=== Lead Generation ===")
    print("1) Run with defaults (min score 80, save to CSV, all locations & keywords)")
    print("2) Customize settings")
    print("3) Select locations & keywords")
    print("4) Exit")
    choice = input("Select [1]: ").strip() or "1"
    if choice == "4":
        return None
    if choice == "2":
        cfg = interactive_customize_config()
        _print_config_summary(cfg)
        confirm = input("Run with these settings? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            return None
        return cfg
    if choice == "3":
        cfg = interactive_select_config()
        _print_config_summary(cfg)
        confirm = input("Run with these settings? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            return None
        return cfg
    return LeadgenConfig()


def parse_args():
    parser = argparse.ArgumentParser(description="Local business lead generation")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Skip interactive menu and use defaults",
    )
    parser.add_argument("--min-score", type=int, help="Minimum lead_score to keep (default 80)")
    parser.add_argument(
        "--output",
        choices=["csv", "dashboard", "both"],
        help="Output destination",
    )
    parser.add_argument("--csv-path", help="CSV output path (default leads_output.csv)")
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
        args.output is not None,
        args.csv_path is not None,
        args.keywords is not None,
        args.city is not None,
    ])


def config_from_args(args):
    """Build LeadgenConfig from argparse namespace."""
    config = LeadgenConfig()
    if args.min_score is not None:
        config.min_score = args.min_score
    if args.output is not None:
        config.output_mode = args.output
    if args.csv_path is not None:
        config.csv_output = args.csv_path
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

    existing_place_ids = load_existing_place_ids(config.csv_output)
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
            )
            total_rows.extend(rows)
        except Exception as e:
            logger.error("Error processing businesses for %s, %s: %s", city, state, e)
            continue

    if not total_rows:
        logger.critical("No qualifying leads found.")
        return

    logger.critical("Found %d qualifying leads (min score %d)", len(total_rows), config.min_score)

    if config.output_mode in ("csv", "both"):
        save_results(total_rows, config.csv_output)

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
