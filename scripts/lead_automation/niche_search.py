#!/usr/bin/env python3
"""Niche Lead Search orchestrator.

Reuses Places/Playwright discovery and leadfilter identities. Does not run
process_businesses() or the legacy score_lead() model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time

import requests

from email_discovery import enrich_lead_with_email, parse_address_parts
from intent_scoring import apply_competitor_gap, score_intent_lead
from leadfilter import is_new_identity, load_existing_identities
from niche_config import (
    build_search_queries,
    get_niche,
    list_niches,
    load_niches,
    load_score_rules,
    matches_negative_keywords,
    merge_score_rules,
)
from outreach_angle import generate_outreach_angle
from playwright_discovery import (
    BusinessDiscoverySession,
    business_dedupe_key,
    dedupe_businesses,
)
from social_activity import apply_social_fields, classify_social_activity
from website_quality import (
    analyze_website_quality,
    apply_website_fields,
    cheap_website_check,
)

HIGH_PRI_TAG = "high-pri-lead"
DEFAULT_NICHE_OUTPUT = "niche_leads_output.json"


@dataclass
class NicheSearchConfig:
    niche_id: str
    locations: list = field(default_factory=list)
    zips: list = field(default_factory=list)
    extra_keywords: list = field(default_factory=list)
    search_radius: int = 50000
    max_leads: int = 0
    min_reviews: int = 0
    min_rating: float = 0.0
    min_score: int = 55
    filter_franchises: bool = True
    exclude_strong_websites: bool = False
    require_phone: bool = False
    require_email: bool = False
    require_social: bool = False
    require_no_website: bool = False
    require_website_issue: bool = False
    require_active_business: bool = True
    website_requirement: str = "any"
    leadgen_type: str = "api_manager"
    playwright_max_pages: int = 20
    playwright_max_results_per_search: int = 400
    playwright_area_expansion: str = "off"
    skip_searched: bool = True
    search_history_path: str = "leadgen_search_history.json"
    json_output: str = DEFAULT_NICHE_OUTPUT
    output_mode: str = "json"
    max_workers: int = 12
    open_reviewer: bool = True


def is_high_pri_niche(niche):
    """True only when the niche preset explicitly opts into high-pri-lead."""
    if not isinstance(niche, dict):
        return False
    return bool(niche.get("high_pri_lead"))


def niche_tags(source, niche=None):
    tags = ["lead_automation"]
    if is_high_pri_niche(niche):
        tags.append(HIGH_PRI_TAG)
    if source == "playwright":
        tags.append("playwright")
    else:
        tags.append("google-places-api")
    return tags


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def geocode_zip(zip_code, api_key, fetch_fn=None):
    """Return 'lat,lng' for a US ZIP using the existing Google key."""
    if not zip_code or not api_key:
        return None
    fetcher = fetch_fn or requests.get
    response = fetcher(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": str(zip_code), "key": api_key},
        timeout=10,
    )
    data = response.json()
    results = data.get("results") or []
    if not results:
        return None
    loc = ((results[0].get("geometry") or {}).get("location") or {})
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        return None
    return f"{lat},{lng}"


def expand_locations(states=None, cities=None, zips=None, coords_data=None, api_key=None):
    """Build (state, city, coords) tuples from coords.json plus optional ZIPs."""
    from leadgen import COORDS_DATA, _default_locations

    data = coords_data if coords_data is not None else COORDS_DATA
    locations = []
    if not states and not cities and not zips:
        return list(_default_locations())

    state_set = {part.strip().upper() for entry in (states or []) for part in str(entry).split(",") if part.strip()}
    city_set = {part.strip().lower() for entry in (cities or []) for part in str(entry).split(",") if part.strip()}

    for state, city_map in data.items():
        if state_set and state.upper() not in state_set:
            continue
        for city, coords in city_map.items():
            if city_set and city.lower() not in city_set:
                continue
            locations.append((state, city, coords))

    for zip_code in zips or []:
        zip_code = str(zip_code).strip()
        if not zip_code:
            continue
        coords = geocode_zip(zip_code, api_key) if api_key else None
        locations.append(("", zip_code, coords or ""))
    return locations


def _maps_url(place_id, profile_url=None):
    if profile_url:
        return profile_url
    if place_id:
        return f"https://www.google.com/maps/place/?q=place_id:{place_id}"
    return None


def _hydrate_address(lead, city=None, state=None):
    parts = parse_address_parts(lead.get("address"), city=city, state=state)
    lead["city"] = lead.get("city") or parts.get("city")
    lead["state"] = lead.get("state") or parts.get("state")
    lead["zip"] = lead.get("zip") or parts.get("zip")
    return lead


def _base_row(entry, niche, location_label, source, search_term):
    city = state = None
    if location_label and "," in location_label:
        city, state = [part.strip() for part in location_label.split(",", 1)]
    elif location_label:
        city = location_label
    row = {
        "business_name": entry.get("business_name"),
        "place_id": entry.get("place_id"),
        "address": entry.get("address") or "",
        "phone_google": entry.get("phone_google"),
        "phone_website": entry.get("phone_website"),
        "email": entry.get("email") or "",
        "has_email": bool(entry.get("email")),
        "website": entry.get("website") or "",
        "rating": entry.get("rating"),
        "user_ratings_total": entry.get("user_ratings_total") or 0,
        "business_status": entry.get("business_status"),
        "niche": niche["display_name"],
        "niche_key": niche["id"],
        "category": niche.get("category") or niche["id"],
        "profile_url": _maps_url(entry.get("place_id"), entry.get("profile_url")),
        "source": source,
        "search_term": search_term or entry.get("search_term") or entry.get("niche_key"),
        "location_searched": location_label or entry.get("location_searched"),
        "tags": niche_tags(source, niche),
        "score_model": "intent_v1",
        "outreach_status": "new",
        "notes": None,
        "date_discovered": _now_iso(),
        "facebook_url": entry.get("facebook_url"),
        "instagram_url": entry.get("instagram_url"),
        "reviews": entry.get("reviews") or [],
    }
    return _hydrate_address(row, city=city, state=state)


def _iter_business_dicts(entries):
    """Yield business dicts, flattening accidental nested lists/tuples."""
    for entry in entries or []:
        if isinstance(entry, dict):
            yield entry
        elif isinstance(entry, (list, tuple)):
            yield from _iter_business_dicts(entry)


def dedupe_discovered(entries):
    """Dedupe across queries using the existing identity key order."""
    unique = []
    seen = set()
    for entry in _iter_business_dicts(entries):
        key = business_dedupe_key(entry)
        if key is None:
            unique.append(entry)
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _is_franchise(lead):
    from leadgen import FRANCHISE_DATA, is_franchise
    return is_franchise(lead.get("business_name"), lead.get("website"), FRANCHISE_DATA)


def _review_count(lead):
    try:
        return int(lead.get("user_ratings_total") or 0)
    except (TypeError, ValueError):
        return 0


def _rating(lead):
    try:
        return float(lead.get("rating"))
    except (TypeError, ValueError):
        return None


def _passes_stage2(lead, rules):
    min_reviews = int((rules.get("enrichment") or {}).get("stage2_min_reviews") or 0)
    return _review_count(lead) >= min_reviews


def _passes_stage3(lead, rules):
    enrich = rules.get("enrichment") or {}
    if enrich.get("stage3_exclude_franchise") and lead.get("is_franchise"):
        return False
    if _review_count(lead) < int(enrich.get("stage3_min_reviews") or 0):
        return False
    min_rating = float(enrich.get("stage3_min_rating") or 0)
    rating = _rating(lead)
    if min_rating and (rating is None or rating < min_rating):
        return False
    return True


def _passes_user_filters(lead, config, rules):
    if config.filter_franchises and lead.get("is_franchise"):
        return False
    if _review_count(lead) < int(config.min_reviews or 0):
        return False
    min_rating = float(config.min_rating or 0)
    rating = _rating(lead)
    if min_rating and (rating is None or rating < min_rating):
        return False
    if int(lead.get("lead_score") or 0) < int(config.min_score or 0):
        return False
    signals = lead.get("lead_signals") or {}
    quality = lead.get("website_quality_score")
    try:
        quality_n = int(quality) if quality is not None else None
    except (TypeError, ValueError):
        quality_n = None
    if config.require_active_business:
        status = lead.get("business_status")
        if status in ("CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"):
            return False
    if config.require_phone and not signals.get("has_phone"):
        return False
    if config.require_email and not signals.get("has_email"):
        return False
    if config.require_social and not (lead.get("facebook_url") or lead.get("instagram_url")):
        return False
    if config.require_no_website and not signals.get("no_website"):
        return False
    if config.require_website_issue:
        if signals.get("no_website"):
            return False
        if quality_n is None or quality_n < int(rules.get("website_issue_min_quality") or 60):
            return False
    requirement = (config.website_requirement or "any").lower()
    strong_max = int(rules.get("exclude_strong_website_max_quality") or 40)
    issue_min = int(rules.get("website_issue_min_quality") or 60)
    if requirement == "none" and not signals.get("no_website"):
        return False
    if requirement == "issue":
        if signals.get("no_website") or quality_n is None or quality_n < issue_min:
            return False
    if requirement == "weak_or_none":
        if not signals.get("no_website") and (quality_n is None or quality_n < issue_min):
            return False
    if config.exclude_strong_websites and not signals.get("no_website") and quality_n is not None and quality_n <= strong_max:
        return False
    return True


def _negative_text(lead):
    return " ".join(
        str(part)
        for part in (
            lead.get("business_name"),
            lead.get("website"),
            lead.get("search_term"),
        )
        if part
    )


def discover_api_manager_location(queries, state, city, coords, config, api_key, api_call_counter, history):
    from leadgen import get_place_details, get_places, log_step, PLACES_SLEEP

    discovered = []
    raw_count = 0
    location_label = f"{city}, {state}" if state else str(city)
    if not coords:
        return discovered, raw_count
    pending, skipped = history.pending_keywords_for_location(
        queries,
        city,
        state or "",
        leadgen_type="api_manager",
        search_radius=config.search_radius,
        skip_searched=config.skip_searched,
    )
    if skipped:
        log_step(3, 1, "Skip searched", f"{len(skipped)} query×location units")
    if not pending:
        return discovered, raw_count
    places = get_places(
        coords,
        config.search_radius,
        pending,
        api_key,
        api_call_counter=api_call_counter,
    )
    raw_count += len(places)
    for keyword in pending:
        found_for_kw = sum(1 for item in places if item.get("niche_key") == keyword)
        history.record_search(
            leadgen_type="api_manager",
            keyword=keyword,
            city=city,
            state=state or "",
            search_radius=config.search_radius,
            businesses_found=found_for_kw,
            status="completed",
        )
    for place in places:
        details = {}
        if place.get("place_id"):
            details = get_place_details(place["place_id"], api_key)
            if api_call_counter is not None:
                api_call_counter["places_details"] = api_call_counter.get("places_details", 0) + 1
            time.sleep(PLACES_SLEEP)
        place.update({k: v for k, v in details.items() if v not in (None, [], "")})
        place["location_searched"] = location_label
        place["source"] = "api_manager"
        discovered.append(place)
    return discovered, raw_count


def discover_api_manager(queries, locations, config, api_key, api_call_counter, history):
    discovered = []
    raw_count = 0
    for state, city, coords in locations:
        batch, count = discover_api_manager_location(
            queries, state, city, coords, config, api_key, api_call_counter, history
        )
        discovered.extend(batch)
        raw_count += count
    return discovered, raw_count


def discover_playwright_location(session, queries, state, city, coords, config, history):
    """Search one city/state with an existing Playwright session."""
    from leadgen import log_step

    discovered = []
    raw_count = 0
    pending, skipped = history.pending_keywords_for_location(
        queries,
        city,
        state or "",
        leadgen_type="playwright",
        playwright_max_pages=config.playwright_max_pages,
        playwright_area_expansion=config.playwright_area_expansion,
        skip_searched=config.skip_searched,
    )
    if skipped:
        log_step(3, 1, "Skip searched", f"{len(skipped)} query×location units")
    location_label = f"{city}, {state}" if state else str(city)
    for keyword in pending:
        if session.google_blocked:
            break
        if coords:
            listings = session.search_location(
                keyword,
                city,
                state or "",
                coords=coords,
                max_pages=config.playwright_max_pages,
                max_results=config.playwright_max_results_per_search,
                area_expansion=config.playwright_area_expansion,
            )
        else:
            listings = session.search_listings(
                keyword,
                city,
                state or "",
                max_pages=config.playwright_max_pages,
                max_results=config.playwright_max_results_per_search,
                query=f"{keyword} near {city}",
            )
        raw_count += len(listings)
        history.record_search(
            leadgen_type="playwright",
            keyword=keyword,
            city=city,
            state=state or "",
            playwright_max_pages=config.playwright_max_pages,
            playwright_area_expansion=config.playwright_area_expansion,
            businesses_found=len(listings),
            status="blocked" if session.google_blocked and not listings else "completed",
        )
        for item in listings:
            item["location_searched"] = location_label
            item["source"] = "playwright"
            item["niche_key"] = keyword
            item["search_term"] = keyword
            discovered.append(item)
    discovered, _duplicates = dedupe_businesses(discovered)
    return discovered, raw_count


def discover_playwright(queries, locations, config, history):
    session = BusinessDiscoverySession()
    discovered = []
    raw_count = 0
    try:
        for state, city, coords in locations:
            batch, count = discover_playwright_location(
                session, queries, state, city, coords, config, history
            )
            discovered.extend(batch)
            raw_count += count
            if session.google_blocked:
                break
    finally:
        session.close()
    return discovered, raw_count


def staged_enrich(leads, niche, rules, config):
    from leadgen import log_stage, log_step

    enrich = rules.get("enrichment") or {}
    websites_analyzed = 0
    social_found = 0

    log_stage(4, "Stage 2 website check", f"{len(leads)} unique businesses")
    for lead in leads:
        if not _passes_stage2(lead, rules):
            lead["website_status"] = lead.get("website_status") or "skipped_stage2"
            continue
        try:
            cheap = cheap_website_check(lead.get("website"))
            apply_website_fields(lead, cheap)
            if cheap.get("_html") and _passes_stage3(lead, rules):
                deep = analyze_website_quality(
                    lead.get("website"),
                    html=cheap.get("_html"),
                    headers=cheap.get("_headers"),
                    final_url=cheap.get("_final_url"),
                    cheap=cheap,
                )
                apply_website_fields(lead, cheap, deep)
                websites_analyzed += 1
        except Exception:
            lead["website_status"] = lead.get("website_status") or "analysis_error"
            if not lead.get("website_issues"):
                lead["website_issues"] = ["analysis_error"]
        lead["last_enriched"] = _now_iso()

    apply_competitor_gap(leads, rules)
    for lead in leads:
        score_intent_lead(lead, niche, rules=rules)

    log_stage(5, "Stage 4 social / Stage 5 email")
    stage4_floor = int(enrich.get("stage4_min_provisional_score") or 40)
    stage5_floor = int(enrich.get("stage5_min_intent_score") or 55)
    for lead in leads:
        promising = int(lead.get("lead_score") or 0) >= stage4_floor
        if promising or niche.get("social_priority"):
            classification = classify_social_activity(lead, posts=lead.get("social_posts"), rules=rules)
            apply_social_fields(lead, classification)
            if classification.get("facebook_url") or classification.get("instagram_url"):
                social_found += 1
            score_intent_lead(lead, niche, rules=rules)
        if int(lead.get("lead_score") or 0) >= stage5_floor and not lead.get("email"):
            try:
                enrich_lead_with_email(
                    lead,
                    city=lead.get("city"),
                    state=lead.get("state"),
                )
            except Exception:
                pass
            score_intent_lead(lead, niche, rules=rules)
        lead["outreach_angle"] = generate_outreach_angle(lead, niche)
        lead["last_enriched"] = _now_iso()

    log_step(5, 1, "Websites analyzed", str(websites_analyzed))
    log_step(5, 2, "Social profiles found", str(social_found))
    return {
        "websites_analyzed": websites_analyzed,
        "social_profiles_found": social_found,
    }


def _location_label(state, city):
    return f"{city}, {state}" if state else str(city)


def _empty_run_stats(niche, locations):
    return {
        "niche": niche["display_name"],
        "locations": [_location_label(state, city) for state, city, _ in locations],
        "google_results": 0,
        "unique_businesses": 0,
        "websites_analyzed": 0,
        "social_profiles_found": 0,
        "high_intent_leads": 0,
        "score_55_plus": 0,
        "qualified_leads": 0,
        "with_website": 0,
        "without_website": 0,
        "with_email": 0,
        "high_pri": 0,
        "saved": 0,
        "uploaded": 0,
        "locations_processed": 0,
    }


def _add_stats(total, batch):
    for key in (
        "google_results",
        "unique_businesses",
        "websites_analyzed",
        "social_profiles_found",
        "high_intent_leads",
        "score_55_plus",
        "qualified_leads",
        "with_website",
        "without_website",
        "with_email",
        "high_pri",
        "saved",
        "uploaded",
        "locations_processed",
    ):
        total[key] = int(total.get(key) or 0) + int(batch.get(key) or 0)
    return total


def persist_niche_results(rows, config, location_label=None):
    """Write JSON and/or upload this location batch."""
    from leadgen import persist_lead_batch

    return persist_lead_batch(
        rows,
        config,
        location_label=location_label,
        json_path=config.json_output,
    )


def _group_discovered(raw, locations):
    """Yield (label, entries, raw_count) in configured location order."""
    labels = [_location_label(state, city) for state, city, _ in locations]
    buckets = {label: [] for label in labels}
    leftovers = []
    for entry in _iter_business_dicts(raw):
        label = entry.get("location_searched")
        if label in buckets:
            buckets[label].append(entry)
        else:
            leftovers.append(entry)
    for label in labels:
        yield label, buckets[label], len(buckets[label])
    if leftovers:
        yield leftovers[0].get("location_searched") or "other", leftovers, len(leftovers)


def _process_location_batch(raw, raw_count, niche, source, config, rules, existing, remaining=None):
    """Dedupe, enrich, qualify, and score one location batch."""
    from leadgen import log_stage

    unique = dedupe_discovered(raw)
    rows = []
    for entry in unique:
        row = _base_row(
            entry,
            niche,
            entry.get("location_searched"),
            entry.get("source") or source,
            entry.get("search_term"),
        )
        if matches_negative_keywords(_negative_text(row), niche):
            continue
        row["is_franchise"] = _is_franchise(row)
        if not is_new_identity(row, existing):
            continue
        rows.append(row)

    log_stage(3, "Deduped businesses", f"{len(rows)} unique after filters")
    if rows:
        enrich_stats = staged_enrich(rows, niche, rules, config)
        apply_competitor_gap(rows, rules)
        for lead in rows:
            score_intent_lead(lead, niche, rules=rules)
            lead["outreach_angle"] = generate_outreach_angle(lead, niche)
            lead["tags"] = niche_tags(lead.get("source") or source, niche)
    else:
        enrich_stats = {"websites_analyzed": 0, "social_profiles_found": 0}

    qualified = [lead for lead in rows if _passes_user_filters(lead, config, rules)]
    qualified.sort(key=lambda item: (-int(item.get("lead_score") or 0), item.get("business_name") or ""))
    if remaining is not None:
        qualified = qualified[:remaining]

    from leadgen import _lead_field_counts

    counts = _lead_field_counts(qualified)
    with_website = sum(
        1
        for lead in rows
        if (lead.get("website") or "").strip()
        and not (lead.get("lead_signals") or {}).get("no_website")
    )
    stats = {
        "google_results": raw_count,
        "unique_businesses": len(rows),
        "websites_analyzed": enrich_stats["websites_analyzed"],
        "social_profiles_found": enrich_stats["social_profiles_found"],
        "qualified_leads": len(qualified),
        "with_website": with_website,
        "without_website": max(0, len(rows) - with_website),
        "saved": 0,
        "uploaded": 0,
        "locations_processed": 1,
        **counts,
    }
    return qualified, stats


def _flush_location_batch(qualified, batch_stats, config, location_label, totals):
    from leadgen import log_stage, print_lead_stats

    log_stage(6, "Output", f"{location_label}: {len(qualified)} qualified leads")
    saved, uploaded = persist_niche_results(qualified, config, location_label=location_label)
    batch_stats["saved"] = saved
    batch_stats["uploaded"] = uploaded
    _add_stats(totals, batch_stats)
    print_lead_stats(batch_stats, location_label=location_label)
    print_lead_stats(totals, cumulative=True)
    return saved, uploaded


def run_niche_search(config, niches=None, rules=None, discover_fn=None):
    """Run a niche search job and return (rows, stats).

    Playwright and API Manager process one city/state at a time: discover,
    enrich, qualify, then save/upload before the next location. `discover_fn`
    (tests) still discovers all at once, then flushes per location_searched.
    """
    from leadgen import (
        GOOGLE_API_KEY,
        log_stage,
        log_step,
        update_usage_stats,
    )
    from search_history import SearchHistory

    niche = get_niche(config.niche_id, niches)
    rules = merge_score_rules(rules or load_score_rules(), niche)
    queries = build_search_queries(niche, config.extra_keywords)
    locations = list(config.locations or [])
    history = SearchHistory(config.search_history_path)
    existing = load_existing_identities(config.json_output)
    api_call_counter = {"places_nearby": 0, "places_details": 0}

    log_stage(1, "Niche search", niche["display_name"])
    log_step(1, 1, "Queries", f"{len(queries)}: {', '.join(queries[:8])}")
    log_step(1, 2, "Locations", str(len(locations)))

    source = "playwright" if config.leadgen_type == "playwright" else "api_manager"
    remaining = int(config.max_leads) if config.max_leads else None
    qualified_all = []
    totals = _empty_run_stats(niche, locations)

    def _handle_raw(raw, raw_count, location_label):
        nonlocal remaining
        if remaining is not None and remaining <= 0:
            return
        batch, batch_stats = _process_location_batch(
            raw,
            raw_count,
            niche,
            source,
            config,
            rules,
            existing,
            remaining=remaining,
        )
        if remaining is not None:
            remaining -= len(batch)
        qualified_all.extend(batch)
        _flush_location_batch(batch, batch_stats, config, location_label, totals)
        history.save()

    if discover_fn is not None:
        raw, _raw_count = discover_fn(queries, locations, config)
        for label, entries, raw_count in _group_discovered(raw, locations):
            if not entries:
                continue
            _handle_raw(entries, raw_count, label)
    elif source == "playwright":
        session = BusinessDiscoverySession()
        try:
            for state, city, coords in locations:
                if remaining is not None and remaining <= 0:
                    break
                label = _location_label(state, city)
                log_step(3, 2, "Location", label)
                raw, raw_count = discover_playwright_location(
                    session, queries, state, city, coords, config, history
                )
                _handle_raw(raw, raw_count, label)
                if session.google_blocked:
                    break
        finally:
            session.close()
    else:
        if not GOOGLE_API_KEY or GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY":
            raise RuntimeError("Please set GOOGLE_API_KEY in .env before running API Manager niche search.")
        for state, city, coords in locations:
            if remaining is not None and remaining <= 0:
                break
            label = _location_label(state, city)
            log_step(3, 2, "Location", label)
            raw, raw_count = discover_api_manager_location(
                queries, state, city, coords, config, GOOGLE_API_KEY, api_call_counter, history
            )
            _handle_raw(raw, raw_count, label)

    qualified_all.sort(key=lambda item: (-int(item.get("lead_score") or 0), item.get("business_name") or ""))
    history.record_run({
        "started_at": _now_iso(),
        "leadgen_type": source,
        "niche": niche["id"],
        "stats": totals,
        "keywords": queries,
        "locations": totals["locations"],
        "qualified_leads": len(qualified_all),
    })
    history.save()
    if source == "api_manager":
        update_usage_stats(
            nearby_calls=api_call_counter.get("places_nearby", 0),
            details_calls=api_call_counter.get("places_details", 0),
        )
    _print_niche_summary(totals)
    return qualified_all, totals


def _print_niche_summary(stats):
    print()
    print("Searching:")
    print(stats.get("niche") or "")
    print("Locations:")
    print(", ".join(stats.get("locations") or []) or "(none)")
    print("Progress:")
    print(f"Google results: {stats.get('google_results', 0)}")
    print(f"Unique businesses: {stats.get('unique_businesses', 0)}")
    print(f"Websites analyzed: {stats.get('websites_analyzed', 0)}")
    print(f"Social profiles found: {stats.get('social_profiles_found', 0)}")
    print(f"High-intent leads: {stats.get('high_intent_leads', 0)}")
    print(f"Score 55+: {stats.get('score_55_plus', 0)}")
    print(f"With website: {stats.get('with_website', 0)}")
    print(f"Without website: {stats.get('without_website', 0)}")
    print(f"With email: {stats.get('with_email', 0)}")
    print(f"High-pri leads: {stats.get('high_pri', 0)}")
    print(f"Saved: {stats.get('saved', 0)}")
    print(f"Uploaded: {stats.get('uploaded', 0)}")
    print(f"{stats.get('qualified_leads', 0)} qualified leads found")
    print()


def config_from_leadgen(base, niche_id, extra=None):
    extra = extra or {}
    return NicheSearchConfig(
        niche_id=niche_id,
        locations=list(extra.get("locations") or getattr(base, "locations", []) or []),
        extra_keywords=list(extra.get("extra_keywords") or []),
        search_radius=int(extra.get("search_radius") or getattr(base, "search_radius", 50000)),
        max_leads=int(extra.get("max_leads") or 0),
        min_reviews=int(extra.get("min_reviews") if extra.get("min_reviews") is not None else getattr(base, "min_reviews", 0)),
        min_rating=float(extra.get("min_rating") or 0),
        min_score=int(extra.get("min_score") if extra.get("min_score") is not None else getattr(base, "min_score", 55)),
        filter_franchises=bool(
            extra.get("filter_franchises")
            if extra.get("filter_franchises") is not None
            else getattr(base, "filter_franchises", True)
        ),
        exclude_strong_websites=bool(extra.get("exclude_strong_websites", False)),
        require_phone=bool(extra.get("require_phone", False)),
        require_email=bool(extra.get("require_email", False)),
        require_social=bool(extra.get("require_social", False)),
        require_no_website=bool(extra.get("require_no_website", False)),
        require_website_issue=bool(extra.get("require_website_issue", False)),
        require_active_business=bool(extra.get("require_active_business", True)),
        website_requirement=extra.get("website_requirement") or "any",
        leadgen_type=getattr(base, "leadgen_type", "api_manager"),
        playwright_max_pages=getattr(base, "playwright_max_pages", 20),
        playwright_max_results_per_search=getattr(base, "playwright_max_results_per_search", 400),
        playwright_area_expansion=getattr(base, "playwright_area_expansion", "off"),
        skip_searched=getattr(base, "skip_searched", True),
        search_history_path=getattr(base, "search_history_path", "leadgen_search_history.json"),
        json_output=extra.get("json_output") or DEFAULT_NICHE_OUTPUT,
        output_mode=getattr(base, "output_mode", "json"),
        max_workers=getattr(base, "max_workers", 12),
        open_reviewer=bool(extra.get("open_reviewer", True)),
    )


def interactive_niche_search(base_config=None):
    """Prompt for niche search settings, run the job, then open the reviewer."""
    from leadgen import _prompt_int, _prompt_locations, _default_locations, config_from_saved_settings

    base = base_config or config_from_saved_settings()
    niches = list_niches()
    print("\n=== Lead Search ===")
    for index, niche in enumerate(niches, start=1):
        print(f" {index:>2}) {niche['display_name']}")
    raw = input("Niche number: ").strip()
    try:
        niche = niches[int(raw) - 1]
    except (ValueError, IndexError):
        print("Invalid niche.")
        return None
    print(f"Niche: {niche['display_name']}")
    locations = _prompt_locations(_default_locations())
    min_reviews = _prompt_int("Minimum reviews", niche.get("suggested_min_reviews") or base.min_reviews)
    min_rating_raw = input(
        f"Minimum rating [{niche.get('suggested_min_rating') or 4.5}]: "
    ).strip()
    min_rating = float(min_rating_raw) if min_rating_raw else float(niche.get("suggested_min_rating") or 4.5)
    min_score = _prompt_int("Minimum score", base.min_score)
    radius = _prompt_int("Radius (meters)", getattr(base, "search_radius", 50000))
    max_leads = _prompt_int("Number of leads (0 = all)", 0)
    exclude_franchises = (input("Exclude franchises? [Y/n]: ").strip().lower() or "y") != "n"
    weak_site = (input("Prioritize no/weak website? [Y/n]: ").strip().lower() or "y") != "n"
    require_active = (input("Require active business? [Y/n]: ").strip().lower() or "y") != "n"
    extra_raw = input("Extra keywords (comma-separated) []: ").strip()
    extra = [part.strip() for part in extra_raw.split(",") if part.strip()]
    config = config_from_leadgen(
        base,
        niche["id"],
        extra={
            "locations": locations,
            "extra_keywords": extra,
            "search_radius": radius,
            "max_leads": max_leads,
            "min_reviews": min_reviews,
            "min_rating": min_rating,
            "min_score": min_score,
            "filter_franchises": exclude_franchises,
            "exclude_strong_websites": weak_site,
            "website_requirement": "weak_or_none" if weak_site else "any",
            "require_active_business": require_active,
            "json_output": DEFAULT_NICHE_OUTPUT,
        },
    )
    print("\n[ SEARCH FOR LEADS ]\n")
    rows, _stats = run_niche_search(config, niches=load_niches())
    if config.open_reviewer:
        from niche_results import review_leads
        review_leads(rows, json_path=config.json_output)
    return rows
