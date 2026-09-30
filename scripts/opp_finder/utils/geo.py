"""Geographic and remote-status filtering for South/Central NJ targeting."""

from __future__ import annotations

import re
from typing import Any

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

NJ_STATE_PATTERNS = (
    r"\bnj\b",
    r"\bnew jersey\b",
    r"\bsouth jersey\b",
    r"\bsouthern new jersey\b",
)


def _haystack(*parts: str | None) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def detect_remote_status(location: str | None, description: str | None = None) -> str:
    """Return remote | hybrid | on-site | unknown."""
    text = _haystack(location, description)
    # Explicit negations should not count as remote.
    if re.search(r"\b(not|no)\s+(a\s+)?remote\b|\bnon[-\s]?remote\b|\bin[-\s]?office only\b", text):
        if any(re.search(p, text) for p in HYBRID_PATTERNS):
            return "hybrid"
        if any(re.search(p, text) for p in ONSITE_PATTERNS) or re.search(r"\bnj\b|new jersey", text):
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


def requires_out_of_area_relocation(location: str | None, description: str | None = None) -> bool:
    text = _haystack(location, description)
    if not any(re.search(p, text) for p in RELOCATE_PATTERNS):
        return False
    # Relocate mentions within NJ are fine; elsewhere is not.
    if any(re.search(p, text) for p in NJ_STATE_PATTERNS):
        return False
    return True


def matches_target_geography(
    location: str | None,
    description: str | None,
    config: dict[str, Any],
    *,
    allow_remote: bool | None = None,
) -> bool:
    """True if listing is in-target NJ geography or allowed remote US."""
    include_remote = config.get("include_remote", True) if allow_remote is None else allow_remote
    remote_status = detect_remote_status(location, description)
    text = _haystack(location, description)

    if requires_out_of_area_relocation(location, description):
        return False

    if remote_status == "remote":
        return bool(include_remote)

    loc_cfg = config.get("location") or {}
    state = str(loc_cfg.get("state") or "NJ").lower()
    counties = [str(c).lower() for c in (loc_cfg.get("counties") or [])]
    place_hints = [str(p).lower() for p in (loc_cfg.get("place_hints") or [])]

    state_ok = state in text or "new jersey" in text or "south jersey" in text
    county_ok = any(f"{c} county" in text or c in text for c in counties)
    place_ok = any(hint in text for hint in place_hints if len(hint) >= 4)

    if remote_status == "hybrid":
        # Hybrid must be reasonably accessible within the configured NJ region.
        return state_ok or county_ok or place_ok

    if state_ok or county_ok or place_ok:
        return True

    # Unknown remote status but explicit US remote phrasing elsewhere already handled.
    # Drop clearly out-of-state non-remote locations.
    other_state = re.search(
        r"\b(ny|pa|de|md|fl|tx|ca|il|oh|nc|ga|va|ma|ct|ri)\b",
        (location or "").lower(),
    )
    if other_state and "nj" not in (location or "").lower() and "new jersey" not in text:
        return False

    # If location is blank, keep for later analysis (may be remote/snippet-only).
    if not (location or "").strip():
        return True

    return False
