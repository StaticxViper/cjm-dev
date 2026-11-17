"""Seen-filing state for newSinceLastRun.

Stored as one JSON record in a named key-value store:
``{"version": 1, "updatedAt": ISO, "filings": {key: firstSeenISO}}``.
Keys are ``state:filingNumber:filingType``. Only rows that were pushed and
charged are recorded, so a filing held back by maxItems or maxSpendUsd is
still new next time. A missing record is a first run. An unreadable record
fails closed when newSinceLastRun is on: nothing is fetched and nothing is billed.
"""

from __future__ import annotations


STATE_STORE = "ucc-filing-state"
STATE_KEY = "SEEN"
STATE_VERSION = 1
MAX_KEYS = 200_000


def filing_key(state, filing_number, filing_type):
    return f"{state or ''}:{filing_number or ''}:{filing_type or ''}"


def load_state(raw):
    if not isinstance(raw, dict):
        return {}
    filings = raw.get("filings")
    if not isinstance(filings, dict):
        return {}
    return {str(key): str(value or "") for key, value in filings.items() if key}


def state_is_readable(raw):
    """A missing record is readable. Anything that is not the filings map is not."""
    if raw is None:
        return True
    return isinstance(raw, dict) and isinstance(raw.get("filings"), dict)


def merge_state(seen, new, max_keys=MAX_KEYS):
    merged = dict(seen or {})
    for key, first in (new or {}).items():
        merged.setdefault(key, first)
    if len(merged) > max_keys:
        keep = sorted(merged.items(), key=lambda item: item[1], reverse=True)[:max_keys]
        merged = dict(keep)
    return merged


def dump_state(seen, updated_at):
    return {"version": STATE_VERSION, "updatedAt": updated_at, "filings": dict(seen or {})}
