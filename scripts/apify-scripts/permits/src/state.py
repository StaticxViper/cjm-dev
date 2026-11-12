"""Seen-permit state for newSinceLastRun.

Stored as one JSON record in a named key-value store so it survives across
runs: ``{"version": 1, "updatedAt": ISO, "permits": {key: firstSeenISO}}``.
Keys are ``source:permit_id``. Source ids never contain a colon, so the
first colon splits the key. Only rows that were pushed and charged are
recorded, so a permit held back by maxItems or maxSpendUsd is still new
next time.
"""

from __future__ import annotations

STATE_STORE = "permits-state"
STATE_KEY = "SEEN"
STATE_VERSION = 1
MAX_KEYS = 200_000


def permit_key(source, permit_id):
    return f"{source or ''}:{permit_id or ''}"


def load_state(raw):
    if not isinstance(raw, dict):
        return {}
    permits = raw.get("permits")
    if not isinstance(permits, dict):
        return {}
    return {str(key): str(value or "") for key, value in permits.items() if key}


def merge_state(seen, new, max_keys=MAX_KEYS):
    merged = dict(seen or {})
    for key, first in (new or {}).items():
        merged.setdefault(key, first)
    if len(merged) > max_keys:
        keep = sorted(merged.items(), key=lambda item: item[1], reverse=True)[:max_keys]
        merged = dict(keep)
    return merged


def dump_state(seen, updated_at):
    return {"version": STATE_VERSION, "updatedAt": updated_at, "permits": dict(seen or {})}
