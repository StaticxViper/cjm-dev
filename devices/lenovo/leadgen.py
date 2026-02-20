#!/usr/bin/env python3
"""
leadgen.py

Local Business Lead Generation System

Run: python leadgen.py

Fill in GOOGLE_API_KEY before running.
"""
import requests
import pandas as pd
import re
import time
import logging
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import os
from dotenv import load_dotenv
from lead_filter import load_existing_place_ids, is_new_place

load_dotenv()

# -----------------------------
# Configurable constants
# -----------------------------
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_RADIUS = 50000  # meters
KEYWORDS = ["landscaping", "house cleaning"]
LOCATION = '39.9526,-75.1652' # "39.8027,-74.9838"  # placeholder (lat,lng)
MAX_WORKERS = 12
PLACES_SLEEP = 2  # seconds between place detail / next_page_token attempts
CSV_OUTPUT = "leads_output.csv"
existing_place_ids = load_existing_place_ids(CSV_OUTPUT)

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("leadgen")


def get_places(location, radius, keywords, api_key):
    """Use Nearby Search to gather place_ids for given keywords and location.

    Returns list of dicts with 'business_name', 'place_id', 'rating', 'user_ratings_total', 'address'
    """
    base = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    places = {}
    for kw in keywords:
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

                # DEBUG LOGS
                logger.warning("HTTP Status Code: %s", r.status_code)
                logger.warning("Places Status: %s", data.get("status"))
                logger.warning("Error Message: %s", data.get("error_message"))
                logger.warning("Results Count: %d", len(data.get("results", [])))

            except Exception as e:
                logger.warning("Nearby search failed for keyword %s: %s", kw, e)
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
                }
            # handle pagination
            next_token = data.get("next_page_token")
            if next_token:
                # next_page_token is not immediately valid; wait before using it
                time.sleep(PLACES_SLEEP)
                params = {"pagetoken": next_token, "key": api_key}
                # continue loop
                continue
            break
    logger.info("Collected %d unique places", len(places))
    return list(places.values())


def get_place_details(place_id, api_key):
    """Fetch Place Details for a single place_id.

    Returns dict with website and phone (if available).
    """
    base = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "website,formatted_phone_number,formatted_address,name,place_id",
        "key": api_key,
    }
    try:
        r = requests.get(base, params=params, timeout=10)
        data = r.json()
        result = data.get("result", {})
        return {
            "website": result.get("website"),
            "phone_google": result.get("formatted_phone_number"),
            "address": result.get("formatted_address"),
        }
    except Exception as e:
        logger.warning("Place details failed for %s: %s", place_id, e)
        return {"website": None, "phone_google": None, "address": None}


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

    original_url = url
    # Normalize scheme
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
    # title
    if soup.title and soup.title.string:
        result["has_title"] = True

    # viewport
    mv = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "viewport"})
    if mv:
        result["has_viewport"] = True

    # emails
    emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html))
    # filter out obvious junk
    filtered = []
    for e in emails:
        low = e.lower()
        if any(low.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg")):
            continue
        if "mailto:" in low:
            low = low.replace("mailto:", "")
        filtered.append(low)
    result["emails"] = sorted(set(filtered))

    # phones (US-style)
    phone_matches = re.findall(r"(\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", html)
    # re.findall with groups returns tuples; re-run without capturing groups
    phone_matches = re.findall(r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", html)
    cleaned_phones = set()
    for p in phone_matches:
        digits = re.sub(r"[^0-9]", "", p)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            cleaned_phones.add("(+1) {}-{}-{}".format(digits[0:3], digits[3:6], digits[6:10]))
    result["phones_website"] = sorted(cleaned_phones)

    # CTA keywords
    text = soup.get_text(separator=" ").lower()
    cta_keywords = ["call", "contact", "quote", "estimate"]
    result["has_cta"] = any(kw in text for kw in cta_keywords)

    return result


def score_lead(has_website, https, has_viewport, html_length, emails, has_cta, rating, user_ratings_total):
    """Return integer lead_score (higher = worse digital presence)."""
    score = 0
    if not has_website:
        score += 10
        # If no website, many other checks are irrelevant
        return score
    if not https:
        score += 5
    if not has_viewport:
        score += 3
    try:
        if html_length < 5000:
            score += 3
    except Exception:
        score += 3
    if not emails:
        score += 2
    if not has_cta:
        score += 2
    try:
        if rating is None or float(rating) < 4.5:
            score += 1
    except Exception:
        score += 1
    try:
        if user_ratings_total is None or int(user_ratings_total) < 15:
            score += 1
    except Exception:
        score += 1
    return score


def process_businesses(businesses, api_key, existing_ids):
    """Given list of basic business entries, enrich with place details and analyze websites concurrently."""
    enriched = []
    logger.info("Fetching place details for %d businesses", len(businesses))
    for b in businesses:
        place_id = b.get("place_id")
        details = get_place_details(place_id, api_key)
        # Respect rate limits
        time.sleep(PLACES_SLEEP)
        entry = {
            "business_name": b.get("business_name"),
            "place_id": place_id,
            "address": details.get("address") or b.get("address"),
            "phone_google": details.get("phone_google"),
            "website": details.get("website"),
            "rating": b.get("rating"),
            "user_ratings_total": b.get("user_ratings_total"),
        }
        enriched.append(entry)

    # Deduplicate by website or business_name (bonus)
    unique = {}
    for e in enriched:
        key = e.get("website") or e.get("business_name")
        if key in unique:
            continue
        unique[key] = e
    businesses_unique = list(unique.values())
    logger.info("After deduplication: %d businesses", len(businesses_unique))

    # Analyze websites concurrently
    analyses = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_map = {}
        for b in businesses_unique:
            url = b.get("website")
            if url:
                future = ex.submit(analyze_website, url)
            else:
                # Submit a trivial result for consistency
                future = ex.submit(lambda: {"emails": [], "phones_website": [], "https": False, "has_viewport": False, "html_length": 0, "has_title": False, "has_cta": False, "error": None})
            future_map[future] = b
        for fut in as_completed(future_map):
            b = future_map[fut]
            try:
                analyses[b.get("place_id")] = fut.result()
            except Exception as e:
                logger.warning("Website analysis failed for %s: %s", b.get("website"), e)
                analyses[b.get("place_id")] = {"emails": [], "phones_website": [], "https": False, "has_viewport": False, "html_length": 0, "has_title": False, "has_cta": False, "error": str(e)}

    # Build final rows
    rows = []
    for b in businesses_unique:
        place_id = b.get("place_id")
        if not place_id:
            continue
        if not is_new_place(place_id, existing_ids):
            continue  # skip duplicates across runs and within-run
        a = analyses.get(place_id, {})
        has_website = bool(b.get("website"))
        lead_score = score_lead(has_website, a.get("https", False), a.get("has_viewport", False), a.get("html_length", 0), a.get("emails", []), a.get("has_cta", False), b.get("rating"), b.get("user_ratings_total"))
        row = {
            "business_name": b.get("business_name"),
            "address": b.get("address"),
            "phone_google": b.get("phone_google"),
            "phone_website": ";".join(a.get("phones_website", [])) if a.get("phones_website") else None,
            "email": ";".join(a.get("emails", [])) if a.get("emails") else None,
            "website": b.get("website"),
            "rating": b.get("rating"),
            "user_ratings_total": b.get("user_ratings_total"),
            "https": a.get("https", False),
            "has_viewport": a.get("has_viewport", False),
            "html_length": a.get("html_length", 0),
            "lead_score": lead_score,
        }
        rows.append(row)

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
            # dedupe by website if available else by business_name
            if "website" in combined.columns:
                combined = combined.drop_duplicates(subset=["website", "business_name"], keep="first")
            else:
                combined = combined.drop_duplicates(subset=["business_name"], keep="first")
            combined = combined.sort_values(by="lead_score", ascending=False)
            combined.to_csv(csv_path, index=False)
            logger.info("Appended and saved %d total leads to %s", len(combined), csv_path)
            return
    # otherwise save new
    df_new = df_new.sort_values(by="lead_score", ascending=False)
    df_new.to_csv(csv_path, index=False)
    logger.info("Saved %d leads to %s", len(df_new), csv_path)


def main():
    if GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY":
        logger.error("Please set GOOGLE_API_KEY in the script before running.")
        return

    logger.info("Starting lead generation for location=%s radius=%s keywords=%s", LOCATION, SEARCH_RADIUS, KEYWORDS)
    places = get_places(LOCATION, SEARCH_RADIUS, KEYWORDS, GOOGLE_API_KEY)
    if not places:
        logger.info("No places found; exiting")
        return
    rows = process_businesses(places, GOOGLE_API_KEY, existing_place_ids)
    save_results(rows, CSV_OUTPUT)


if __name__ == "__main__":
    main()
