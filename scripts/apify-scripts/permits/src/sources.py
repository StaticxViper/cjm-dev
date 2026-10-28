"""Verified building-permit feeds.

The catalog is ``sources.json`` next to this Actor. Shape matches
``scripts/lead_automation/new_business_sources.json``: id, adapter, status,
query, field_map, rate_limit, and terms_checked. Only enabled, verified
open-data and HTML-table rows are queried.
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .runtime import prepare_imports
except ImportError:
    from runtime import prepare_imports


VERIFIED_ADAPTERS = ("open_data", "http_table")


def catalog_path():
    prepare_imports()
    return Path(__file__).resolve().parents[1] / "sources.json"


def load_entries(path=None):
    catalog = Path(path) if path else catalog_path()
    data = json.loads(catalog.read_text(encoding="utf-8"))
    sources = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(sources, list):
        raise ValueError(f"sources.json must contain a sources list: {catalog}")
    return sources


def verified_entries(entries):
    chosen = []
    for entry in entries or []:
        if entry.get("adapter") not in VERIFIED_ADAPTERS:
            continue
        if not entry.get("enabled") or entry.get("status") != "verified":
            continue
        if entry.get("id"):
            chosen.append(entry)
    return chosen


def select_sources(wanted, entries=None):
    """Return ``(entries in request order, error)``.

    An empty request selects every verified source. An unknown id, or an id
    that is not an enabled verified feed, returns an error and no entries.
    """
    catalog = list(entries if entries is not None else load_entries())
    verified = verified_entries(catalog)
    verified_ids = [entry.get("id") for entry in verified]
    if not wanted:
        if not verified:
            return [], "No verified permit source is enabled."
        return verified, ""
    by_id = {entry.get("id"): entry for entry in catalog if entry.get("id")}
    chosen = []
    unknown = []
    seen = set()
    for item in wanted:
        source_id = str(item or "").strip()
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        entry = by_id.get(source_id)
        if entry is None or entry not in verified:
            unknown.append(source_id)
            continue
        chosen.append(entry)
    if unknown:
        return [], (
            "Unknown source id(s): "
            + ", ".join(unknown)
            + ". Verified ids: "
            + ", ".join(verified_ids)
        )
    return chosen, ""
