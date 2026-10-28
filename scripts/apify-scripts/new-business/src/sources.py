"""Verified state entity feeds from new_business_sources.json.

Only enabled, verified open-data rows in the Secretary of State and state
entity categories are queried. Local license lists and map searches stay on
the CLI.
"""

from __future__ import annotations

import json

try:
    from .runtime import prepare_imports
except ImportError:
    from runtime import prepare_imports


ENTITY_CATEGORIES = frozenset({
    "Secretary of State / entity databases",
    "State business / entity search databases",
})


def load_entries():
    root = prepare_imports()
    path = root / "scripts" / "lead_automation" / "new_business_sources.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(sources, list):
        raise ValueError(f"new_business_sources.json must contain a sources list: {path}")
    return sources


def _states_of(entry):
    coverage = entry.get("coverage") or {}
    return [str(state or "").strip().upper() for state in coverage.get("states") or [] if str(state or "").strip()]


def entity_sources(states, entries=None):
    """Return (entries in state order, state codes with no verified feed)."""
    catalog = entries if entries is not None else load_entries()
    wanted = []
    for state in states or []:
        code = str(state or "").strip().upper()
        if code and code not in wanted:
            wanted.append(code)
    chosen = []
    covered = set()
    for state in wanted:
        for entry in catalog:
            if entry.get("adapter") != "open_data":
                continue
            if not entry.get("enabled") or entry.get("status") != "verified":
                continue
            if entry.get("category") not in ENTITY_CATEGORIES:
                continue
            if state not in _states_of(entry):
                continue
            if entry not in chosen:
                chosen.append(entry)
            covered.add(state)
    missing = [state for state in wanted if state not in covered]
    return chosen, missing
