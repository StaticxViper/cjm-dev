"""Seen-bid state for newSinceLastRun.

Stored as one JSON record in a named key-value store:
``{"version": 1, "updatedAt": ISO, "bids": {key: firstSeenISO}}``.
Keys are ``source:solicitationId``. Only rows that were pushed and charged
are recorded, so a bid held back by maxItems or maxSpendUsd is still new
next time. A missing record is a first run. An unreadable record fails
closed when newSinceLastRun is on: nothing is fetched and nothing is billed.
"""

from __future__ import annotations


STATE_STORE = "local-government-bids-state"
STATE_KEY = "SEEN"
STATE_VERSION = 1
MAX_KEYS = 200_000


def opportunity_key(source, solicitation_id):
    return f"{source or ''}:{solicitation_id or ''}"


def load_state(raw):
    if not isinstance(raw, dict):
        return {}
    bids = raw.get("bids")
    if not isinstance(bids, dict):
        return {}
    return {str(key): str(value or "") for key, value in bids.items() if key}


def state_is_readable(raw):
    """A missing record is readable. Anything that is not the bids map is not."""
    if raw is None:
        return True
    return isinstance(raw, dict) and isinstance(raw.get("bids"), dict)


def merge_state(seen, new, max_keys=MAX_KEYS):
    merged = dict(seen or {})
    for key, first in (new or {}).items():
        merged.setdefault(key, first)
    if len(merged) > max_keys:
        keep = sorted(merged.items(), key=lambda item: item[1], reverse=True)[:max_keys]
        merged = dict(keep)
    return merged


def dump_state(seen, updated_at):
    return {"version": STATE_VERSION, "updatedAt": updated_at, "bids": dict(seen or {})}
