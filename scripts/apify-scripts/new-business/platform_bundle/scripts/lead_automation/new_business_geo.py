"""Geography filter for new-business records. Uses coords selections already built by leadgen."""
from __future__ import annotations

import json
import math
from pathlib import Path

from new_business_dedupe import zip5

_DIR = Path(__file__).resolve().parent


def load_regions(path=None):
    regions_path = Path(path) if path else _DIR / "geo_regions.json"
    if not regions_path.exists():
        return {}
    try:
        with open(regions_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    regions = data.get("regions") if isinstance(data, dict) else {}
    return regions if isinstance(regions, dict) else {}


def build_selection(
    locations=None,
    counties=None,
    zips=None,
    radius_m=50000,
    region_names=None,
    regions_file=None,
    city_constrained=True,
):
    """Describe the selected geography.

    locations are (state, city, coords) tuples from coords.json / expand_locations.
    A region whose cities list is empty selects the whole state.
    """
    city_pairs = set()
    state_only = set()
    postal_codes = set()
    county_names = set()
    points = []
    for state, city, coords in locations or []:
        state_code = str(state or "").strip().upper()
        city_name = str(city or "").strip().lower()
        if city_constrained and state_code and city_name and not city_name.isdigit():
            city_pairs.add((state_code, city_name))
        elif state_code:
            state_only.add(state_code)
        if city_name.isdigit() and len(city_name) == 5:
            postal_codes.add(city_name)
        parsed = _parse_coords(coords)
        if parsed:
            points.append(parsed)
    for county in counties or []:
        name = str(county or "").strip().lower()
        if name:
            county_names.add(name)
    for postal in zips or []:
        code = zip5(postal) or str(postal or "").strip()
        if code:
            postal_codes.add(code[:5])
    regions = load_regions(regions_file)
    for name in region_names or []:
        region = regions.get(name)
        if not isinstance(region, dict):
            continue
        state_code = str(region.get("state") or "").strip().upper()
        region_cities = [str(city).strip().lower() for city in region.get("cities") or [] if str(city).strip()]
        if state_code and not region_cities:
            state_only.add(state_code)
        for city in region_cities:
            if state_code:
                city_pairs.add((state_code, city))
        for county in region.get("counties") or []:
            if str(county).strip():
                county_names.add(str(county).strip().lower())
        for postal in region.get("zips") or []:
            code = zip5(postal)
            if code:
                postal_codes.add(code)
    states = set(state_only)
    states.update(state for state, _city in city_pairs)
    return {
        "city_pairs": city_pairs,
        "state_only": state_only,
        "states": states,
        "counties": county_names,
        "zips": postal_codes,
        "points": points,
        "radius_m": int(radius_m or 0),
        "active": bool(city_pairs or state_only or county_names or postal_codes),
    }


def filter_geography(records, selection):
    kept = []
    dropped = 0
    for record in records or []:
        row = record.as_dict() if hasattr(record, "as_dict") else dict(record)
        keep, unverified = _decide(row, selection or {})
        if not keep:
            dropped += 1
            continue
        row["geo_unverified"] = unverified
        kept.append(row)
    return kept, dropped


def _decide(row, selection):
    if not selection or not selection.get("active"):
        missing = not any([
            row.get("state"), row.get("city"), row.get("zip"), row.get("county"), row.get("address"),
        ])
        return True, missing

    state = str(row.get("state") or "").strip().upper()
    city = str(row.get("city") or "").strip().lower()
    county = str(row.get("county") or "").strip().lower()
    postal = zip5(row.get("zip") or row.get("address"))
    unknown = False
    city_pairs = selection.get("city_pairs") or set()
    state_only = selection.get("state_only") or set()
    states = selection.get("states") or set()

    if states:
        if not state:
            unknown = True
        elif state not in states:
            return False, False

    needs_city = bool(city_pairs) and state not in state_only
    if needs_city:
        if not city:
            unknown = True
        elif (state, city) not in city_pairs and not (not state and any(item[1] == city for item in city_pairs)):
            return False, False

    if selection.get("counties"):
        if not county:
            unknown = True
        elif county not in selection["counties"]:
            return False, False

    if selection.get("zips"):
        if not postal:
            unknown = True
        elif postal not in selection["zips"]:
            return False, False

    if selection.get("radius_m") and selection.get("points") and row.get("latitude") is not None and row.get("longitude") is not None:
        try:
            lat = float(row.get("latitude"))
            lng = float(row.get("longitude"))
        except (TypeError, ValueError):
            unknown = True
        else:
            if not any(_meters(lat, lng, plat, plng) <= selection["radius_m"] for plat, plng in selection["points"]):
                return False, False

    return True, unknown


def _parse_coords(coords):
    if coords is None:
        return None
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            return float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            return None
    parts = str(coords).split(",")
    if len(parts) < 2 or not parts[0].strip():
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _meters(lat1, lng1, lat2, lng2):
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))
