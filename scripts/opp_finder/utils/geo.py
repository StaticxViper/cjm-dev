"""Geographic and remote-status filtering for multi-location targeting."""

from __future__ import annotations

import re
from typing import Any

from utils.config import configured_locations

REMOTE_PATTERNS = (
    r"\bremote\b",
    r"\bwork from home\b",
    r"\bwfh\b",
    r"\bfully remote\b",
    r"\b100%\s*remote\b",
    r"\bremote[-\s]?us\b",
    r"\banywhere in the (us|u\.s\.|united states)\b",
)
HYBRID_PATTERNS = (r"\bhybrid\b",)
ONSITE_PATTERNS = (r"\bon[-\s]?site\b", r"\bin[-\s]?office\b", r"\bin person\b")
RELOCATE_PATTERNS = (
    r"\brelocat",
    r"\bmust relocate\b",
    r"\brelocation required\b",
)

STATE_NAME_MAP = {
    "nj": "new jersey",
    "pa": "pennsylvania",
    "de": "delaware",
    "ny": "new york",
    "md": "maryland",
    "ct": "connecticut",
}


def _haystack(*parts: str | None) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def detect_remote_status(location: str | None, description: str | None = None) -> str:
    """Return remote | hybrid | on-site | unknown."""
    text = _haystack(location, description)
    # Explicit negations should not count as remote.
    if re.search(r"\b(not|no)\s+(a\s+)?remote\b|\bnon[-\s]?remote\b|\bin[-\s]?office only\b", text):
        if any(re.search(p, text) for p in HYBRID_PATTERNS):
            return "hybrid"
        if any(re.search(p, text) for p in ONSITE_PATTERNS):
            return "on-site"
        return "on-site"
    if any(re.search(p, text) for p in REMOTE_PATTERNS):
        if any(re.search(p, text) for p in HYBRID_PATTERNS):
            return "hybrid"
        return "remote"
    if any(re.search(p, text) for p in HYBRID_PATTERNS):
        return "hybrid"
    if any(re.search(p, text) for p in ONSITE_PATTERNS):
        return "on-site"
    return "unknown"


def remote_priority_rank(remote_status: str | None) -> int:
    """Lower rank = higher priority when sorting (remote first)."""
    status = (remote_status or "unknown").lower().strip()
    if status == "remote":
        return 0
    if status == "hybrid":
        return 1
    if status == "unknown":
        return 2
    return 3  # on-site last


def requires_out_of_area_relocation(
    location: str | None,
    description: str | None,
    config: dict[str, Any],
) -> bool:
    text = _haystack(location, description)
    if not any(re.search(p, text) for p in RELOCATE_PATTERNS):
        return False
    # Relocate within any configured target state is fine.
    for region in configured_locations(config):
        for state in region.get("states") or []:
            abbr = str(state).lower()
            full = STATE_NAME_MAP.get(abbr, abbr)
            if re.search(rf"\b{re.escape(abbr)}\b", text) or full in text:
                return False
    return True


def _region_matches(text: str, location: str, region: dict[str, Any]) -> bool:
    states = [str(s).lower() for s in (region.get("states") or [])]
    counties = [str(c).lower() for c in (region.get("counties") or [])]
    place_hints = [str(p).lower() for p in (region.get("place_hints") or [])]
    phrases = [str(p).lower() for p in (region.get("search_phrases") or [])]

    state_ok = False
    for state in states:
        full = STATE_NAME_MAP.get(state, state)
        if re.search(rf"\b{re.escape(state)}\b", text) or full in text:
            state_ok = True
            break

    county_ok = any(f"{c} county" in text or re.search(rf"\b{re.escape(c)}\b", text) for c in counties)
    place_ok = any(hint in text for hint in place_hints if len(hint) >= 4)
    phrase_ok = any(p in text for p in phrases if len(p) >= 4)

    # County/place/phrase hits are enough even without explicit state token.
    if county_ok or place_ok or phrase_ok:
        return True
    if state_ok and (county_ok or place_ok or phrase_ok or not counties):
        # Bare state match: allow only when location string itself looks in-state
        # (avoid matching random text that mentions a state abbreviation).
        loc = (location or "").lower()
        if any(re.search(rf"\b{re.escape(s)}\b", loc) or STATE_NAME_MAP.get(s, s) in loc for s in states):
            return True
    return False


def matched_regions(
    location: str | None,
    description: str | None,
    config: dict[str, Any],
) -> list[str]:
    """Return names of configured regions that match this listing."""
    text = _haystack(location, description)
    hits: list[str] = []
    for region in configured_locations(config):
        if _region_matches(text, location or "", region):
            hits.append(str(region.get("name") or "region"))
    return hits


def matches_target_geography(
    location: str | None,
    description: str | None,
    config: dict[str, Any],
    *,
    allow_remote: bool | None = None,
) -> bool:
    """True if listing is in any configured region or allowed remote US."""
    include_remote = config.get("include_remote", True) if allow_remote is None else allow_remote
    remote_status = detect_remote_status(location, description)
    text = _haystack(location, description)

    if requires_out_of_area_relocation(location, description, config):
        return False

    if remote_status == "remote":
        return bool(include_remote)

    regions = configured_locations(config)
    region_hit = bool(matched_regions(location, description, config))

    if remote_status == "hybrid":
        # Hybrid must be reasonably accessible within a configured region.
        return region_hit

    if region_hit:
        return True

    # Drop clearly out-of-area non-remote locations.
    configured_states = set()
    for region in regions:
        for state in region.get("states") or []:
            configured_states.add(str(state).lower())

    loc_only = (location or "").lower()
    other_state = re.search(
        r"\b(ny|pa|de|md|fl|tx|ca|il|oh|nc|ga|va|ma|ct|ri|wa|or|az|co|mi|mn|wi|tn|mo|in|sc)\b",
        loc_only,
    )
    if other_state:
        abbr = other_state.group(1)
        if abbr not in configured_states and "remote" not in loc_only:
            return False

    # If location is blank, keep for later analysis (may be remote/snippet-only).
    if not (location or "").strip():
        return True

    return False
