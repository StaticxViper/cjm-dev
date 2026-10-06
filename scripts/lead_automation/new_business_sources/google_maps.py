"""Maps verification. A low review count is not newness evidence.

robots.txt allows /maps/search/ and /maps/place/. This adapter enriches
records with phone, website, category, and place URL. It does not add
newness evidence.
"""
from __future__ import annotations

from new_business_sources.base import (
    SourceAdapter,
    load_fixture_json,
    utc_now,
)
from new_business_dedupe import normalize_business_name


class GoogleMapsAdapter(SourceAdapter):
    def fetch(self, geo, since_date, limit, dry_run=False):
        """Maps is a verification source, not a newness source."""
        return []

    def verify(self, rows, *, limit=20, dry_run=False, headless=True):
        overlays = []
        checked = False
        if dry_run:
            payload = load_fixture_json(self.id) or []
            if isinstance(payload, dict):
                overlays = payload.get("overlays") or []
            elif isinstance(payload, list):
                overlays = payload
            checked = True
            return _apply_overlays(rows, overlays), {"checked": checked, "blocked": False}
        from playwright_discovery import BusinessDiscoverySession

        session = BusinessDiscoverySession(headless=headless)
        blocked = False
        used = 0
        try:
            for row in rows:
                if used >= int(limit):
                    break
                if session.google_blocked:
                    blocked = True
                    break
                if row.get("phone") and row.get("website"):
                    row["maps_checked"] = True
                    continue
                city = row.get("city") or ""
                state = row.get("state") or ""
                name = row.get("business_name") or ""
                if not name:
                    continue
                try:
                    listings = session.search_location(
                        name,
                        city or " ",
                        state or " ",
                        max_pages=1,
                        max_results=3,
                    )
                except Exception:
                    continue
                used += 1
                checked = True
                if session.google_blocked:
                    blocked = True
                    row["maps_checked"] = False
                    row["maps_blocked"] = True
                    break
                match = _best_listing(name, listings)
                if match:
                    _copy_listing(row, match)
                row["maps_checked"] = True
        finally:
            session.close()
        return rows, {"checked": checked, "blocked": blocked}


def _best_listing(name, listings):
    target = normalize_business_name(name)
    for listing in listings or []:
        if normalize_business_name(listing.get("business_name")) == target:
            return listing
    return (listings or [None])[0]


def _copy_listing(row, listing):
    if listing.get("phone_google") and not row.get("phone"):
        row["phone"] = listing.get("phone_google")
        row["phone_google"] = listing.get("phone_google")
        row["phone_origin"] = "maps"
    if listing.get("website") and not row.get("website"):
        row["website"] = listing.get("website")
    if listing.get("place_id") and not row.get("place_id"):
        row["place_id"] = listing.get("place_id")
    if listing.get("profile_url") and not row.get("maps_url"):
        row["maps_url"] = listing.get("profile_url")
        row["profile_url"] = listing.get("profile_url")
    if listing.get("category") and not row.get("category"):
        row["category"] = listing.get("category")
    if listing.get("user_ratings_total") is not None and row.get("user_ratings_total") is None:
        row["user_ratings_total"] = listing.get("user_ratings_total")
    if listing.get("business_status") and not row.get("business_status"):
        row["business_status"] = listing.get("business_status")
    sources = row.setdefault("sources", [])
    sources.append({
        "source_name": "google_maps",
        "source_url": "https://www.google.com/maps/search/",
        "source_record_url": row.get("maps_url") or "",
        "retrieved_at": utc_now(),
        "fields_provided": [
            key for key in ("phone", "website", "category", "maps_url", "place_id")
            if row.get(key)
        ],
    })


def _apply_overlays(rows, overlays):
    by_name = {}
    for overlay in overlays:
        key = normalize_business_name(overlay.get("match_name") or overlay.get("business_name"))
        if key:
            by_name[key] = overlay
    for row in rows:
        row["maps_checked"] = True
        overlay = by_name.get(normalize_business_name(row.get("business_name")))
        if overlay:
            _copy_listing(row, overlay)
    return rows
