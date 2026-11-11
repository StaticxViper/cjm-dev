"""Verified open-data feeds from new_business_sources.json.

Only enabled, verified open-data rows are queried. Secretary of State and
state entity categories are the entity_formation trigger. Other feeds name
their trigger in the catalog entry. Local HTML lists and map searches stay
on the CLI.
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

ENTITY_TRIGGER = "entity_formation"
TRIGGERS = (ENTITY_TRIGGER, "liquor_license", "restaurant_inspection")
TRIGGER_LABELS = {
    ENTITY_TRIGGER: "Secretary of State",
    "liquor_license": "liquor-license",
    "restaurant_inspection": "restaurant-inspection",
}


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


def trigger_of(entry):
    if entry.get("trigger"):
        return entry["trigger"]
    if entry.get("category") in ENTITY_CATEGORIES:
        return ENTITY_TRIGGER
    return ""


def _wanted(values, upper=False):
    wanted = []
    for value in values or []:
        text = str(value or "").strip()
        if upper:
            text = text.upper()
        if text and text not in wanted:
            wanted.append(text)
    return wanted


def feed_sources(states, triggers=(ENTITY_TRIGGER,), entries=None):
    """Return ([(trigger, entry)] in state then trigger order, [(state, trigger)] with no feed)."""
    catalog = entries if entries is not None else load_entries()
    chosen = []
    missing = []
    for state in _wanted(states, upper=True):
        for trigger in _wanted(triggers):
            covered = False
            for entry in catalog:
                if entry.get("adapter") != "open_data":
                    continue
                if not entry.get("enabled") or entry.get("status") != "verified":
                    continue
                if trigger_of(entry) != trigger:
                    continue
                if state not in _states_of(entry):
                    continue
                covered = True
                if not any(item is entry for _trigger, item in chosen):
                    chosen.append((trigger, entry))
            if not covered:
                missing.append((state, trigger))
    return chosen, missing


def entity_sources(states, entries=None):
    """Return (entries in state order, state codes with no verified feed)."""
    chosen, missing = feed_sources(states, (ENTITY_TRIGGER,), entries)
    return [entry for _trigger, entry in chosen], [state for state, _trigger in missing]
