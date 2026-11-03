"""Seen-job state for newSinceLastRun.

Stored as one JSON record in a named key-value store so it survives across
runs: ``{"version": 1, "updatedAt": ISO, "jobs": {key: firstSeenISO}}``.
Keys are ``ats:companySlug:jobId`` with the slug lowercased. Only rows that
were pushed are recorded, so a job held back by maxItems or a filter is
still new next time.
"""

from __future__ import annotations

STATE_STORE = "ats-jobs-state"
STATE_KEY = "SEEN"
STATE_VERSION = 1
MAX_KEYS = 200_000


def load_state(raw):
    if not isinstance(raw, dict):
        return {}
    jobs = raw.get("jobs")
    if not isinstance(jobs, dict):
        return {}
    return {str(key): str(value or "") for key, value in jobs.items() if key}


def merge_state(seen, new, max_keys=MAX_KEYS):
    merged = dict(seen or {})
    for key, first in (new or {}).items():
        merged.setdefault(key, first)
    if len(merged) > max_keys:
        keep = sorted(merged.items(), key=lambda item: item[1], reverse=True)[:max_keys]
        merged = dict(keep)
    return merged


def dump_state(seen, updated_at):
    return {"version": STATE_VERSION, "updatedAt": updated_at, "jobs": dict(seen or {})}
