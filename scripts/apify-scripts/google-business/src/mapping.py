"""Map Actor input onto Maps listings and the #127 matcher.

Does not launch a browser and does not request Google web search.
"""

from __future__ import annotations

from urllib.parse import quote_plus

try:
    from .runtime import iso_now, prepare_imports
except ImportError:
    from runtime import iso_now, prepare_imports

GOOGLE_ROBOTS_URL = "https://www.google.com/robots.txt"
MAPS_SEARCH_PREFIX = "https://www.google.com/maps/search/"
DEFAULT_MAX_RESULTS = 5
MAX_RESULTS_CAP = 20
DEFAULT_MAX_SEARCHES = 10
MAX_SEARCHES_CAP = 50

DECISION_LABELS = {
    "write": "match",
    "low_confidence": "low_confidence",
    "no_match": "no_match",
}


def _match():
    prepare_imports()
    import crm_enrich_match as match
    return match


def _robots():
    prepare_imports()
    from crm_enrich_robots import google_maps_allowed
    return google_maps_allowed


def maps_query_url(query_text):
    """Maps search URL only. Does not build a Google web-search URL."""
    return MAPS_SEARCH_PREFIX + quote_plus(query_text or "")


def _clean_county(value):
    text = str(value or "").strip()
    if text.lower().endswith(" county"):
        text = text[: -len(" county")].strip()
    return text or None


def _state_code(value, states):
    code = str(value or "").strip().upper()
    if code not in states:
        raise ValueError("state must be a two-letter US code.")
    return code


def _optional_int(value, label, default, ceiling):
    if value is None or value == "":
        number = default
    else:
        number = int(value)
    if number < 1:
        raise ValueError(f"{label} must be >= 1.")
    if number > ceiling:
        raise ValueError(f"{label} must be <= {ceiling}.")
    return number


def _delay_pair(data, min_key, max_key, default_min, default_max):
    raw_min = data.get(min_key)
    raw_max = data.get(max_key)
    if raw_min is None and raw_max is None:
        return float(default_min), float(default_max)
    low = float(default_min if raw_min is None else raw_min)
    high = float(default_max if raw_max is None else raw_max)
    if low < 0 or high < 0 or low > high:
        raise ValueError(f"{min_key} and {max_key} must be >= 0 and min <= max.")
    return low, high


def read_run_settings(actor_input):
    """Thresholds, caps, and delay ranges. Defaults match the Maps session and #127."""
    prepare_imports()
    from playwright_discovery import (
        DETAIL_DELAY_MAX,
        DETAIL_DELAY_MIN,
        SEARCH_DELAY_MAX,
        SEARCH_DELAY_MIN,
    )

    data = dict(actor_input or {})
    minimum = 80 if data.get("minConfidence") is None else int(data.get("minConfidence"))
    floor = 60 if data.get("lowConfidenceFloor") is None else int(data.get("lowConfidenceFloor"))
    if not 0 <= minimum <= 100:
        raise ValueError("minConfidence must be between 0 and 100.")
    if not 0 <= floor <= 100:
        raise ValueError("lowConfidenceFloor must be between 0 and 100.")
    search_min, search_max = _delay_pair(
        data, "searchDelayMin", "searchDelayMax", SEARCH_DELAY_MIN, SEARCH_DELAY_MAX,
    )
    detail_min, detail_max = _delay_pair(
        data, "detailDelayMin", "detailDelayMax", DETAIL_DELAY_MIN, DETAIL_DELAY_MAX,
    )
    return {
        "min_confidence": minimum,
        "low_floor": floor,
        "max_searches": _optional_int(data.get("maxSearches"), "maxSearches", DEFAULT_MAX_SEARCHES, MAX_SEARCHES_CAP),
        "include_emails": bool(data.get("includeEmails")),
        "headless": True if data.get("headless") is None else bool(data.get("headless")),
        "search_delay_min": search_min,
        "search_delay_max": search_max,
        "detail_delay_min": detail_min,
        "detail_delay_max": detail_max,
    }


def queries_from_input(actor_input, settings):
    data = dict(actor_input or {})
    raw_queries = data.get("queries")
    if not raw_queries:
        if any(data.get(key) for key in ("name", "city", "county", "state")):
            raw_queries = [{
                "name": data.get("name"),
                "city": data.get("city"),
                "county": data.get("county"),
                "state": data.get("state"),
                "maxResults": data.get("maxResults"),
            }]
    if not raw_queries:
        raise ValueError("Provide queries, or a name and state.")
    match = _match()
    limit = settings["max_searches"]
    queries = []
    for raw in raw_queries:
        queries.append(_normalize_query(raw or {}, match.US_STATES))
        if len(queries) >= limit:
            break
    return queries


def _normalize_query(raw, states):
    if not isinstance(raw, dict):
        raise ValueError("Each query must be an object.")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("Each query needs a name.")
    return {
        "name": name,
        "city": str(raw.get("city") or "").strip() or None,
        "county": _clean_county(raw.get("county")),
        "state": _state_code(raw.get("state"), states),
        "maxResults": _optional_int(raw.get("maxResults"), "maxResults", DEFAULT_MAX_RESULTS, MAX_RESULTS_CAP),
    }


def search_place(query):
    """City, otherwise county, otherwise the state. Maps search still gets a place."""
    if query.get("city"):
        return query["city"]
    if query.get("county"):
        return f"{query['county']} County"
    return query["state"]


def lead_from_query(query):
    """Lead dict plus an explicit location so select_match does not invent a street."""
    bits = [f"state={query['state']}"]
    if query.get("county"):
        bits.append(f"county={query['county']}")
    if query.get("city"):
        bits.append(f"city={query['city']}")
    lead = {
        "business_name": query["name"],
        "business_description": "; ".join(bits) + ";",
        "tags": [query["state"].lower()],
    }
    location = {
        "state": query["state"],
        "county": query.get("county"),
        "city": query.get("city"),
        "zip": None,
        "street": None,
    }
    return lead, location


def listing_to_candidate(listing):
    listing = listing or {}
    return {
        "business_name": listing.get("business_name") or listing.get("name"),
        "phone": listing.get("phone") or listing.get("phone_google"),
        "website": listing.get("website"),
        "address": listing.get("address"),
        "category": listing.get("category"),
        "place_id": listing.get("place_id"),
        "profile_url": listing.get("profile_url"),
        "rating": listing.get("rating"),
        "user_ratings_total": listing.get("user_ratings_total"),
        "business_status": listing.get("business_status"),
    }


def reference_tables():
    """ZIP and area-code tables when the #127 data files are on disk."""
    match = _match()
    try:
        return match.load_zip_county(), match.load_npa_state()
    except OSError:
        return {}, {}


def score_candidates(lead, listings, *, min_confidence=80, low_floor=60, location=None, zip_county=None, npa_state=None):
    """Score every listing. select_match never falls back to the first result."""
    match = _match()
    zips = {} if zip_county is None else zip_county
    npas = {} if npa_state is None else npa_state
    candidates = [listing_to_candidate(item) for item in (listings or [])]
    return match.select_match(
        candidates,
        lead,
        zips,
        npas,
        min_confidence=min_confidence,
        low_floor=low_floor,
        location=location,
    )


def candidate_view(best):
    if not best:
        return None
    return {
        "business_name": best.get("name"),
        "phone": best.get("phone"),
        "website": best.get("website"),
        "address": best.get("address"),
        "rating": best.get("rating"),
        "user_ratings_total": best.get("user_ratings_total"),
        "category": best.get("category"),
        "mapsUrl": best.get("profile_url"),
        "placeId": best.get("place_id"),
    }


def dataset_from_selection(query, selection, source_status="ok"):
    best = (selection or {}).get("best")
    raw_decision = (selection or {}).get("decision") or "no_match"
    decision = DECISION_LABELS.get(raw_decision, raw_decision)
    row = {
        "query": query,
        "decision": decision,
        "score": None if not best else best.get("score"),
        "breakdown": None if not best else best.get("breakdown"),
        "hardRejects": [] if not best else list(best.get("hard_rejects") or []),
        "candidate": candidate_view(best),
        "sourceStatus": source_status,
        "scrapedAt": iso_now(),
    }
    return row


def status_row(query, decision, source_status, error=None):
    row = {
        "query": query,
        "decision": decision,
        "score": None,
        "breakdown": None,
        "hardRejects": [],
        "candidate": None,
        "sourceStatus": source_status,
        "scrapedAt": iso_now(),
    }
    if error:
        row["error"] = error
    return row


def collect_emails(lead, website):
    """Validated addresses from the business website. No guessed emails."""
    prepare_imports()
    from email_discovery import inspect_website, score_email_confidence, validate_email

    if not website:
        return []
    inspected = inspect_website(website)
    page_text = inspected.get("page_text") or ""
    page_url = inspected.get("page_url")
    found = []
    seen = set()
    for raw in inspected.get("emails") or []:
        email = validate_email(raw)
        if not email or email in seen:
            continue
        seen.add(email)
        found.append({
            "email": email,
            "confidence": score_email_confidence(
                email,
                lead,
                page_url=page_url,
                page_text=page_text,
                website=website,
            ),
        })
    return found


def maps_allowed(robots_txt):
    return bool(_robots()(robots_txt))


def collect_listings(session, query):
    """Maps search + place enrichment. Returns (listings, blocked)."""
    match = _match()
    keyword = match.display_name(query["name"]) or query["name"]
    listings = session.search_location(
        keyword,
        search_place(query),
        query["state"],
        max_pages=1,
        max_results=query["maxResults"],
    )
    if getattr(session, "google_blocked", False):
        return list(listings or []), True
    enriched = []
    for listing in listings or []:
        if getattr(session, "google_blocked", False):
            return enriched, True
        enriched.append(session.enrich_listing(listing))
        if getattr(session, "google_blocked", False):
            return enriched, True
    return enriched, False


def score_query(query, listings, settings, zip_county, npa_state):
    lead, location = lead_from_query(query)
    selection = score_candidates(
        lead,
        listings,
        min_confidence=settings["min_confidence"],
        low_floor=settings["low_floor"],
        location=location,
        zip_county=zip_county,
        npa_state=npa_state,
    )
    row = dataset_from_selection(query, selection, source_status="ok")
    if settings.get("include_emails") and selection.get("winner") and row["decision"] == "match":
        website = (selection["winner"] or {}).get("website")
        row["emails"] = collect_emails(lead, website)
    return row


def summarize(rows):
    blocked = sum(1 for row in rows if row.get("decision") == "blocked" or row.get("sourceStatus") == "blocked")
    errors = sum(1 for row in rows if row.get("sourceStatus") in {"error", "robots_disallowed"})
    return {
        "status": "blocked" if blocked else ("ok" if errors == 0 else "completed_with_errors"),
        "pushed": len(rows),
        "blocked": blocked,
        "errors": errors,
    }
