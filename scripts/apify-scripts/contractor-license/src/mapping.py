"""Actor input, dataset rows, and the pay-per-event decision."""

from __future__ import annotations

import re

try:
    from .adapters.base import LicenseQuery
    from .lookup import run_lookup
    from .runtime import iso_now
except ImportError:
    from adapters.base import LicenseQuery
    from lookup import run_lookup
    from runtime import iso_now


LICENSE_EVENT = "license"

STATE_NAMES = {
    "california": "CA",
    "arizona": "AZ",
    "new jersey": "NJ",
    "pennsylvania": "PA",
}


def _bounded_int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < low:
        return low
    if number > high:
        return high
    return number


def _bounded_float(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < low:
        return low
    if number > high:
        return high
    return number


def normalize_state(value):
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return ""
    named = STATE_NAMES.get(text.lower())
    if named:
        return named
    if re.fullmatch(r"[A-Za-z]{2}", text):
        return text.upper()
    return ""


def actor_input_to_config(actor_input):
    raw = actor_input or {}
    provided = re.sub(r"\s+", " ", str(raw.get("state") or "").strip())
    state = normalize_state(provided)
    license_no = str(raw.get("licenseNo") if raw.get("licenseNo") is not None else raw.get("license_no") or "").strip()
    name = str(raw.get("name") or "").strip()
    trade = str(raw.get("trade") or "").strip()
    max_results = _bounded_int(raw.get("maxResults"), 25, 1, 50)
    query = LicenseQuery(state, license_no, name, trade, max_results)
    error = ""
    if not provided:
        error = "State is required."
    elif not state:
        error = "Use a two-letter state code. Adapters exist for CA, AZ, NJ, and PA."
    elif not license_no and not name and not trade:
        error = "Provide a license number, business name, or trade."
    return {
        "query": query,
        "error": error,
        "max_requests": _bounded_int(raw.get("maxRequests"), 4, 1, 8),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 2.0, 1.0, 10.0),
        "headless": True if raw.get("headless") is None else bool(raw.get("headless")),
    }


def billable_row(row):
    """Charge only a found license. not_found and failures are free."""
    row = row or {}
    return row.get("sourceStatus") == "found" and bool(row.get("license_no"))


def summarize(rows, truncated=False):
    counts = {}
    for row in rows or []:
        key = row.get("sourceStatus") or "error"
        counts[key] = counts.get(key, 0) + 1
    found = counts.get("found", 0)
    if found:
        status = "ok"
    elif rows:
        status = rows[0].get("sourceStatus") or "error"
    else:
        status = "error"
    return {
        "status": status,
        "pushed": len(rows or []),
        "found": found,
        "notFound": counts.get("not_found", 0),
        "unsupported": counts.get("unsupported", 0),
        "captcha": counts.get("captcha", 0),
        "robots": counts.get("robots_disallowed", 0),
        "errors": counts.get("error", 0),
        "truncated": bool(truncated),
        "billed": found,
    }


def scrape(config, fetch):
    rows, truncated = run_lookup(config, fetch)
    stamped = iso_now()
    for row in rows:
        row["scrapedAt"] = stamped
    return rows, summarize(rows, truncated)
