"""Niche and area input, #127 match rows, and website enrichment.

Maps discovery goes through the google-business matcher and the existing
Playwright session. This module does not call the Places API and does not
request Google web search. lead_scoring.py is the legacy leadgen model and
is not an import target; lead scores use intent_scoring.score_intent_lead.
"""

from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import logging
import os
import sys

try:
    from .runtime import fetch_text, find_repo_root, iso_now, prepare_imports
except ImportError:
    from runtime import fetch_text, find_repo_root, iso_now, prepare_imports


PLACE_EVENT = "place"
EMAIL_EVENT = "email-found"
SCORE_EVENT = "score"

DEFAULT_MAX_ITEMS = 10
MAX_ITEMS_CAP = 25
DEFAULT_MAX_SEARCHES = 5
MAX_SEARCHES_CAP = 20
DEFAULT_MAX_RESULTS = 5
MAX_RESULTS_CAP = 10
DEFAULT_MIN_CONFIDENCE = 80
DEFAULT_LOW_FLOOR = 60

# Signals that claim something about the site itself. They stay off unless
# website quality actually fetched the page.
_UNOBSERVED_SITE_KEYS = frozenset({
    "no_conversion_path",
    "website_broken",
    "website_mobile_problem",
    "strong_website",
    "recently_updated_website",
    "ads_to_weak_landing",
})


def _gb():
    key = "cjm_google_business_mapping"
    loaded = sys.modules.get(key)
    if loaded is not None:
        return loaded
    candidates = []
    root = os.environ.get("CJM_REPO_ROOT")
    if root:
        candidates.append(
            Path(root) / "scripts" / "apify-scripts" / "google-business" / "src" / "mapping.py"
        )
    candidates.append(Path(__file__).resolve().parents[2] / "google-business" / "src" / "mapping.py")
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        prepare_imports()
        path = find_repo_root() / "scripts" / "apify-scripts" / "google-business" / "src" / "mapping.py"
    if not path.is_file():
        raise ImportError("google-business mapping.py was not found")
    src = str(path.parent)
    inserted = src not in sys.path
    if inserted:
        sys.path.insert(0, src)
    try:
        spec = importlib.util.spec_from_file_location(key, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted and src in sys.path:
            sys.path.remove(src)


def _states():
    prepare_imports()
    import crm_enrich_match as match
    return match.US_STATES


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


def _confidence(value, label, default):
    number = default if value is None or value == "" else int(value)
    if not 0 <= number <= 100:
        raise ValueError(f"{label} must be between 0 and 100.")
    return number


def _flag(data, key, default):
    if key not in data or data.get(key) is None:
        return default
    return bool(data.get(key))


def _clean_county(value):
    text = str(value or "").strip()
    if text.lower().endswith(" county"):
        text = text[: -len(" county")].strip()
    return text or None


def load_regions(path=None):
    """Region map from geo_regions.json. Missing or empty files yield {}."""
    if path is None:
        prepare_imports()
        regions_path = find_repo_root() / "scripts" / "lead_automation" / "geo_regions.json"
    else:
        regions_path = Path(path)
    if not regions_path.is_file():
        return {}
    try:
        data = json.loads(regions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    regions = data.get("regions") if isinstance(data, dict) else {}
    return regions if isinstance(regions, dict) else {}


def _lookup_region(name, regions):
    if name in regions and isinstance(regions.get(name), dict):
        return name, regions[name]
    needle = str(name or "").strip().lower()
    for key, value in (regions or {}).items():
        if str(key).strip().lower() == needle and isinstance(value, dict):
            return key, value
    return None, None


def _blank_area():
    return {
        "region": None,
        "state": None,
        "city": None,
        "cities": [],
        "county": None,
        "counties": [],
    }


def _area_from_region(name, region):
    state = str(region.get("state") or "").strip().upper() or None
    cities = [str(city).strip() for city in region.get("cities") or [] if str(city).strip()]
    counties = []
    for county in region.get("counties") or []:
        cleaned = _clean_county(county)
        if cleaned:
            counties.append(cleaned)
    return {
        "region": name,
        "state": state,
        "city": cities[0] if len(cities) == 1 else None,
        "cities": cities,
        "county": counties[0] if len(counties) == 1 else None,
        "counties": counties,
    }


def _parse_city_state(text, states):
    raw = str(text or "").strip()
    if "," not in raw:
        return None
    place, state = raw.rsplit(",", 1)
    place = place.strip()
    state = state.strip().upper()
    if not place or state not in states:
        return None
    county = _clean_county(place) if place.lower().endswith(" county") else None
    if county:
        return {
            "region": None,
            "state": state,
            "city": None,
            "cities": [],
            "county": county,
            "counties": [county],
        }
    return {
        "region": None,
        "state": state,
        "city": place,
        "cities": [place],
        "county": None,
        "counties": [],
    }


def _overlay_place(area, data, states):
    if data.get("state"):
        area["state"] = str(data.get("state")).strip().upper()
        if area["state"] not in states:
            raise ValueError("state must be a two-letter US code.")
    if data.get("city"):
        city = str(data.get("city")).strip()
        area["city"] = city
        area["cities"] = [city]
    if data.get("county"):
        county = _clean_county(data.get("county"))
        area["county"] = county
        area["counties"] = [county] if county else []
    return area


def _resolve_area(data, states):
    raw = data.get("area")
    area = _blank_area()
    if isinstance(raw, dict):
        nested = dict(raw)
        if nested.get("region"):
            key, region = _lookup_region(str(nested.get("region")), load_regions())
            if region is None:
                raise ValueError(f"Unknown area region: {nested.get('region')}")
            area = _area_from_region(key, region)
        else:
            area = _overlay_place(area, nested, states)
    elif isinstance(raw, str) and raw.strip():
        key, region = _lookup_region(raw.strip(), load_regions())
        if region is not None:
            area = _area_from_region(key, region)
        else:
            parsed = _parse_city_state(raw, states)
            if parsed is None:
                raise ValueError("area must be a geo_regions.json name or City, ST.")
            area = parsed
    return _overlay_place(area, data, states)


def _area_view(area):
    if not area or not any(area.get(key) for key in ("region", "state", "city", "county")):
        return None
    view = {
        "region": area.get("region"),
        "city": area.get("city"),
        "county": area.get("county"),
        "state": area.get("state"),
    }
    cities = area.get("cities") or []
    if len(cities) > 1:
        view["cities"] = list(cities)
    return view


def normalize_listing(raw):
    if not isinstance(raw, dict):
        raise ValueError("Each mapsDataset item must be an object.")
    name = raw.get("business") or raw.get("business_name") or raw.get("name") or raw.get("title")
    phone = raw.get("phone") or raw.get("phone_google")
    reviews = raw.get("review_count")
    if reviews is None:
        reviews = raw.get("user_ratings_total")
    return {
        "business_name": str(name or "").strip(),
        "phone": phone or None,
        "phone_google": phone or None,
        "website": (str(raw.get("website")).strip() if raw.get("website") else None) or None,
        "address": raw.get("address") or None,
        "category": raw.get("category") or None,
        "place_id": raw.get("placeId") or raw.get("place_id"),
        "profile_url": raw.get("mapsUrl") or raw.get("profile_url") or raw.get("url"),
        "rating": raw.get("rating"),
        "user_ratings_total": reviews,
        "business_status": raw.get("business_status") or raw.get("businessStatus"),
    }


def build_searches(niche, area, max_searches, max_results):
    prepare_imports()
    from niche_config import build_search_queries

    if not area.get("state"):
        raise ValueError("Maps search needs a state. Set area or pass state.")
    keywords = build_search_queries(niche)
    places = _search_places(area)
    searches = []
    for keyword in keywords:
        for place in places:
            searches.append({
                "name": keyword,
                "city": place.get("city"),
                "county": place.get("county"),
                "state": place["state"],
                "maxResults": max_results,
            })
            if len(searches) >= max_searches:
                return searches
    return searches


def _search_places(area):
    state = area["state"]
    cities = [city for city in (area.get("cities") or []) if city]
    if not cities and area.get("city"):
        cities = [area["city"]]
    if cities:
        return [{"city": city, "county": area.get("county"), "state": state} for city in cities]
    counties = [county for county in (area.get("counties") or []) if county]
    if not counties and area.get("county"):
        counties = [area["county"]]
    if counties:
        return [{"city": None, "county": county, "state": state} for county in counties]
    return [{"city": None, "county": None, "state": state}]


def read_settings(actor_input):
    data = dict(actor_input or {})
    niche_id = str(data.get("niche") or "").strip()
    if not niche_id:
        raise ValueError("Provide a niche id from niches.json.")
    prepare_imports()
    from niche_config import NicheConfigError, get_niche

    try:
        niche = get_niche(niche_id)
    except NicheConfigError as exc:
        raise ValueError(str(exc)) from exc
    states = _states()
    area = _resolve_area(data, states)
    dataset = data.get("mapsDataset")
    if dataset is not None and not isinstance(dataset, list):
        raise ValueError("mapsDataset must be an array.")
    listings = None if dataset is None else [normalize_listing(item) for item in dataset]
    if listings is None and not area.get("state"):
        raise ValueError("Provide an area with a state, or a mapsDataset.")
    max_items = _optional_int(data.get("maxItems"), "maxItems", DEFAULT_MAX_ITEMS, MAX_ITEMS_CAP)
    max_searches = _optional_int(data.get("maxSearches"), "maxSearches", DEFAULT_MAX_SEARCHES, MAX_SEARCHES_CAP)
    max_results = _optional_int(data.get("maxResults"), "maxResults", DEFAULT_MAX_RESULTS, MAX_RESULTS_CAP)
    minimum = _confidence(data.get("minConfidence"), "minConfidence", DEFAULT_MIN_CONFIDENCE)
    floor = _confidence(data.get("lowConfidenceFloor"), "lowConfidenceFloor", DEFAULT_LOW_FLOOR)
    searches = [] if listings is not None else build_searches(niche, area, max_searches, max_results)
    return {
        "niche": niche,
        "area": area,
        "listings": listings,
        "searches": searches,
        "max_items": max_items,
        "headless": True if data.get("headless") is None else bool(data.get("headless")),
        "flags": {
            "email": _flag(data, "includeEmail", True),
            "quality": _flag(data, "includeWebsiteQuality", True),
            "score": _flag(data, "includeScore", True),
        },
        "match": {
            "min_confidence": minimum,
            "low_floor": floor,
            "include_emails": False,
        },
    }


def billable_events(row):
    """place on an accepted #127 match. Add-ons only when that row produced them."""
    if (row or {}).get("decision") != "accepted":
        return []
    events = [PLACE_EVENT]
    if (row or {}).get("email"):
        events.append(EMAIL_EVENT)
    if (row or {}).get("lead_score") is not None:
        events.append(SCORE_EVENT)
    return events


def _count(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rating(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _shell(settings, decision, source_status, error=None):
    niche = (settings or {}).get("niche") or {}
    row = {
        "business": None,
        "phone": None,
        "website": None,
        "rating": None,
        "review_count": None,
        "email": None,
        "website_quality": None,
        "website_label": None,
        "website_status": None,
        "lead_score": None,
        "intent_signals": [],
        "decision": decision,
        "match_score": None,
        "hardRejects": [],
        "niche": niche.get("id"),
        "area": _area_view((settings or {}).get("area") or {}),
        "search_term": None,
        "sourceStatus": source_status,
        "scrapedAt": iso_now(),
    }
    if error:
        row["error"] = error
    return row


def blocked_row(settings):
    return _shell(settings, "blocked", "blocked", error="google_blocked")


def error_bundle(exc):
    row = _shell({}, "error", "error", error=str(exc))
    return [row], summarize([row])


def _area_constrained(area):
    return bool(
        area.get("state")
        or area.get("city")
        or area.get("cities")
        or area.get("county")
        or area.get("counties")
        or area.get("region")
    )


def _location_for(listing, area):
    """Requested area wins. A dataset with no area uses the listing address.

    A state-only area does not copy the card city. Name plus state stays at
    60, under the default accept threshold of 80.
    """
    prepare_imports()
    from email_discovery import parse_address_parts

    parsed = parse_address_parts(listing.get("address") or "")
    if not _area_constrained(area):
        return {"city": parsed.get("city"), "county": None, "state": parsed.get("state")}
    state = area.get("state") or parsed.get("state")
    cities = [city for city in (area.get("cities") or []) if city]
    if area.get("city") and area["city"] not in cities:
        cities = [area["city"], *cities]
    if cities:
        found = parsed.get("city") or ""
        city = next((item for item in cities if item.lower() == found.lower()), None)
        if city is None:
            city = cities[0]
    else:
        city = None
    return {"city": city, "county": area.get("county"), "state": state}


def _negative_hit(listing, niche):
    prepare_imports()
    from niche_config import matches_negative_keywords

    blob = " ".join(
        str(part)
        for part in (listing.get("business_name"), listing.get("category"), listing.get("address"))
        if part
    )
    return matches_negative_keywords(blob, niche)


def _fill_business(row, listing, keyword=None):
    row["business"] = listing.get("business_name") or None
    row["phone"] = listing.get("phone") or listing.get("phone_google")
    row["website"] = listing.get("website")
    row["rating"] = _rating(listing.get("rating"))
    row["review_count"] = _count(listing.get("user_ratings_total"))
    row["search_term"] = keyword
    return row


def _intent_signals(breakdown):
    signals = []
    for item in breakdown or []:
        if not item.get("applied"):
            continue
        signals.append({
            "key": item.get("key"),
            "label": item.get("label"),
            "points": item.get("points"),
        })
    return signals


def _without_unobserved_site_signals(lead, breakdown):
    cleaned = []
    for item in breakdown or []:
        row = dict(item)
        if row.get("key") in _UNOBSERVED_SITE_KEYS:
            row["applied"] = False
        cleaned.append(row)
    score = sum(item["points"] for item in cleaned if item["applied"])
    lead["lead_score"] = score
    lead["lead_score_breakdown"] = cleaned
    return score, cleaned


def website_allowed(url, fetch_text_fn):
    """True when the business site robots.txt allows this URL."""
    prepare_imports()
    from urllib.parse import urlparse

    from crm_enrich_robots import robots_allowed
    from website_quality import normalize_website_url

    normalized = normalize_website_url(url)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        text = fetch_text_fn(robots_url)
    except Exception:
        return False
    return bool(robots_allowed(text or "", normalized))


def default_email(lead, website):
    return _gb().collect_emails(lead, website)


def default_quality(url):
    prepare_imports()
    from website_quality import (
        analyze_website_quality,
        apply_website_fields,
        cheap_website_check,
        website_label,
    )

    holder = {"website": url or ""}
    cheap = cheap_website_check(url)
    deep = None
    if cheap.get("_html"):
        deep = analyze_website_quality(
            url,
            html=cheap.get("_html"),
            headers=cheap.get("_headers"),
            final_url=cheap.get("_final_url"),
            cheap=cheap,
        )
    apply_website_fields(holder, cheap, deep)
    score = holder.get("website_quality_score")
    return {
        "website_status": holder.get("website_status"),
        "website_quality_score": score,
        "website_issues": holder.get("website_issues") or [],
        "website_analysis": holder.get("website_analysis"),
        "website_label": website_label(score, has_website=not cheap.get("no_website")),
        "service_area": holder.get("service_area"),
    }


def _first_email(found):
    prepare_imports()
    from email_discovery import validate_email

    for item in found or []:
        raw = item.get("email") if isinstance(item, dict) else item
        email = validate_email(raw)
        if email:
            return email
    return None


def _enrich(listing, niche, keyword, flags, fetch_text_fn, email_fn, quality_fn):
    website = (listing.get("website") or "").strip() or None
    lead = {
        "business_name": listing.get("business_name") or "",
        "phone": listing.get("phone") or listing.get("phone_google"),
        "phone_google": listing.get("phone") or listing.get("phone_google"),
        "website": website or "",
        "rating": listing.get("rating"),
        "user_ratings_total": _count(listing.get("user_ratings_total")) or 0,
        "address": listing.get("address") or "",
        "business_status": listing.get("business_status"),
        "search_term": " ".join(part for part in (keyword, listing.get("category")) if part),
        "category": listing.get("category"),
    }
    email = None
    quality_score = None
    quality_label = None
    website_status = None
    site_observed = False
    log = logging.getLogger("apify")
    fetch = fetch_text_fn or fetch_text
    if not website:
        website_status = "none"
        if flags.get("quality"):
            quality_score = 100
            quality_label = "None"
            lead["website_status"] = "none"
            lead["website_issues"] = ["no_website"]
            lead["website_quality_score"] = 100
            site_observed = True
    elif flags.get("email") or flags.get("quality"):
        if not website_allowed(website, fetch):
            website_status = "robots_disallowed"
            lead["website_status"] = "robots_disallowed"
        else:
            site_observed = bool(flags.get("quality"))
            if flags.get("quality"):
                try:
                    quality = (quality_fn or default_quality)(website) or {}
                except Exception as exc:
                    log.critical("Website quality failed for %s: %s", lead["business_name"], exc)
                    quality = {}
                    website_status = "error"
                    site_observed = False
                else:
                    website_status = quality.get("website_status") or "ok"
                    quality_score = quality.get("website_quality_score")
                    quality_label = quality.get("website_label")
                    if quality_score is not None:
                        lead["website_quality_score"] = quality_score
                    if quality.get("website_issues") is not None:
                        lead["website_issues"] = quality.get("website_issues")
                    if quality.get("website_analysis"):
                        lead["website_analysis"] = quality.get("website_analysis")
                    if quality.get("website_status"):
                        lead["website_status"] = quality.get("website_status")
                    if quality.get("service_area"):
                        lead["service_area"] = quality.get("service_area")
            if flags.get("email"):
                try:
                    found = (email_fn or default_email)(lead, website)
                except Exception as exc:
                    log.critical("Website email failed for %s: %s", lead["business_name"], exc)
                    found = []
                email = _first_email(found)
                if email:
                    lead["email"] = email
    lead_score = None
    signals = []
    if flags.get("score"):
        try:
            prepare_imports()
            from intent_scoring import score_intent_lead

            score, breakdown = score_intent_lead(lead, niche)
            if website and not site_observed:
                score, breakdown = _without_unobserved_site_signals(lead, breakdown)
            lead_score = score
            signals = _intent_signals(breakdown)
        except Exception as exc:
            log.critical("Lead score failed for %s: %s", lead["business_name"], exc)
            lead_score = None
            signals = []
    return {
        "email": email,
        "website_quality": quality_score,
        "website_label": quality_label,
        "website_status": website_status,
        "lead_score": lead_score,
        "intent_signals": signals,
    }


def evaluate_listing(listing, settings, keyword=None, fetch_text_fn=None, email_fn=None, quality_fn=None):
    """Score one listing with the #127 matcher. Enrich only an accepted match.

    The query name is the listing name. The niche keyword is not compared as
    a brand. select_match still refuses a hard reject and never substitutes
    another card.
    """
    niche = settings["niche"]
    area = settings["area"]
    row = _fill_business(_shell(settings, "rejected", "ok"), listing, keyword=keyword)
    if not listing.get("business_name"):
        row["hardRejects"] = ["missing_name"]
        return row
    if _negative_hit(listing, niche):
        row["hardRejects"] = ["negative_keyword"]
        return row
    location = _location_for(listing, area)
    if not location.get("state"):
        row["hardRejects"] = ["missing_state"]
        return row
    query = {
        "name": listing["business_name"],
        "city": location.get("city"),
        "county": location.get("county"),
        "state": location.get("state"),
        "maxResults": 1,
    }
    # One listing per call, so a rejected card cannot be replaced by another.
    scored = _gb().score_query(query, [listing], settings["match"], *_reference_tables())
    row["match_score"] = scored.get("score")
    row["hardRejects"] = list(scored.get("hardRejects") or [])
    if scored.get("decision") != "match":
        return row
    row["decision"] = "accepted"
    candidate = scored.get("candidate") or {}
    if candidate.get("business_name"):
        row["business"] = candidate.get("business_name")
    if candidate.get("phone"):
        row["phone"] = candidate.get("phone")
    if candidate.get("website"):
        row["website"] = candidate.get("website")
    if candidate.get("rating") is not None:
        row["rating"] = _rating(candidate.get("rating"))
    if candidate.get("user_ratings_total") is not None:
        row["review_count"] = _count(candidate.get("user_ratings_total"))
    enriched = _enrich(
        listing,
        niche,
        keyword,
        settings["flags"],
        fetch_text_fn,
        email_fn,
        quality_fn,
    )
    row.update(enriched)
    return row


def _reference_tables():
    tables = getattr(_reference_tables, "_cache", None)
    if tables is None:
        tables = _gb().reference_tables()
        _reference_tables._cache = tables
    return tables


def _dedupe_key(listing):
    prepare_imports()
    from playwright_discovery import business_dedupe_key

    return business_dedupe_key(listing)


def _consume(listings, settings, keyword, rows, seen, fetch_text_fn, email_fn, quality_fn):
    accepted = sum(1 for row in rows if row.get("decision") == "accepted")
    for listing in listings or []:
        if accepted >= settings["max_items"]:
            break
        key = _dedupe_key(listing)
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        row = evaluate_listing(
            listing,
            settings,
            keyword=keyword,
            fetch_text_fn=fetch_text_fn,
            email_fn=email_fn,
            quality_fn=quality_fn,
        )
        rows.append(row)
        _log_row(row)
        if row.get("decision") == "accepted":
            accepted += 1
    return accepted


def _log_row(row):
    logging.getLogger("apify").critical(
        "Home services: %s -> %s",
        (row or {}).get("business") or "",
        (row or {}).get("decision"),
    )


def _default_session(settings):
    prepare_imports()
    from playwright_discovery import BusinessDiscoverySession

    # TODO: wire scripts/apify-scripts/access.py so a Maps block can escalate
    # through Apify Proxy under maxSpendUsd, maxProxyCostUsd, and allowCaptcha.
    return BusinessDiscoverySession(headless=settings["headless"])


def run_sync(actor_input, session_factory=None, fetch_text_fn=None, email_fn=None, quality_fn=None):
    settings = read_settings(actor_input)
    fetch = fetch_text_fn or fetch_text
    if settings["listings"] is not None:
        rows = []
        _consume(
            settings["listings"],
            settings,
            keyword=None,
            rows=rows,
            seen=set(),
            fetch_text_fn=fetch,
            email_fn=email_fn,
            quality_fn=quality_fn,
        )
        return rows, summarize(rows)

    robots_txt = fetch(_gb().GOOGLE_ROBOTS_URL)
    if not _gb().maps_allowed(robots_txt):
        row = _shell(settings, "error", "robots_disallowed", error="robots_disallowed")
        _log_row(row)
        return [row], summarize([row])

    factory = session_factory or _default_session
    session = factory(settings)
    rows = []
    seen = set()
    try:
        for query in settings["searches"]:
            if sum(1 for row in rows if row.get("decision") == "accepted") >= settings["max_items"]:
                break
            if getattr(session, "google_blocked", False):
                row = blocked_row(settings)
                rows.append(row)
                _log_row(row)
                break
            listings, blocked = _gb().collect_listings(session, query)
            if blocked or getattr(session, "google_blocked", False):
                row = blocked_row(settings)
                rows.append(row)
                _log_row(row)
                break
            _consume(
                listings,
                settings,
                keyword=query.get("name"),
                rows=rows,
                seen=seen,
                fetch_text_fn=fetch,
                email_fn=email_fn,
                quality_fn=quality_fn,
            )
    finally:
        close = getattr(session, "close", None)
        if close:
            close()
    return rows, summarize(rows)


def summarize(rows):
    accepted = sum(1 for row in rows if row.get("decision") == "accepted")
    rejected = sum(1 for row in rows if row.get("decision") == "rejected")
    blocked = sum(1 for row in rows if row.get("decision") == "blocked" or row.get("sourceStatus") == "blocked")
    errors = sum(
        1 for row in rows
        if row.get("decision") == "error" or row.get("sourceStatus") in {"error", "robots_disallowed"}
    )
    if blocked:
        status = "blocked"
    elif errors and not accepted and not rejected:
        status = "error"
    elif errors:
        status = "completed_with_errors"
    else:
        status = "ok"
    return {
        "status": status,
        "accepted": accepted,
        "rejected": rejected,
        "blocked": blocked,
        "errors": errors,
        "pushed": len(rows),
        "emailsFound": sum(1 for row in rows if row.get("email")),
        "scoresProduced": sum(1 for row in rows if row.get("lead_score") is not None),
    }
