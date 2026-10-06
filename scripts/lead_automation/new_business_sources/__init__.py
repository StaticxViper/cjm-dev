"""Registry of new-business source adapters."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from new_business_sources.google_maps import GoogleMapsAdapter
from new_business_sources.google_search import GoogleSearchAdapter
from new_business_sources.http_table import HttpTableAdapter
from new_business_sources.open_data import OpenDataAdapter

_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = _DIR / "new_business_sources.json"

ADAPTERS = {
    "http_table": HttpTableAdapter,
    "open_data": OpenDataAdapter,
    "google_search": GoogleSearchAdapter,
    "google_maps": GoogleMapsAdapter,
}


def load_source_config(path=None):
    config_path = Path(path) if path else DEFAULT_CONFIG
    with open(config_path, encoding="utf-8") as handle:
        data = json.load(handle)
    sources = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(sources, list):
        raise ValueError(f"new_business_sources.json must contain a sources list: {config_path}")
    return sources


def build_adapter(entry):
    kind = (entry.get("adapter") or "").strip()
    if kind in ADAPTERS:
        return ADAPTERS[kind](entry)
    if kind.startswith("custom."):
        module_name = kind.split(".", 1)[1]
        module = importlib.import_module(f"new_business_sources.custom.{module_name}")
        adapter_cls = getattr(module, "Adapter")
        return adapter_cls(entry)
    raise ValueError(f"Unknown adapter {kind!r} for source {entry.get('id')}")


def load_adapters(path=None):
    return [build_adapter(entry) for entry in load_source_config(path)]


def valid_source_ids(path=None):
    return [entry.get("id") for entry in load_source_config(path) if entry.get("id")]


def select_adapters(selected=None, path=None):
    """Return adapters to run. Unknown ids raise ValueError listing valid ids."""
    adapters = load_adapters(path)
    known = [adapter.id for adapter in adapters]
    if not selected:
        return [adapter for adapter in adapters if adapter.runnable()]
    wanted = []
    for item in selected:
        for part in str(item).split(","):
            part = part.strip()
            if part:
                wanted.append(part)
    unknown = [item for item in wanted if item not in known]
    if unknown:
        raise ValueError(
            "Unknown source id(s): "
            + ", ".join(unknown)
            + ". Valid ids: "
            + ", ".join(known)
        )
    by_id = {adapter.id: adapter for adapter in adapters}
    return [by_id[item] for item in wanted]


def format_source_line(adapter, access_result):
    coverage = adapter.coverage or {}
    states = ",".join(coverage.get("states") or []) or "-"
    cities = ",".join(coverage.get("cities") or [])
    counties = ",".join(coverage.get("counties") or [])
    parts = [states]
    if counties:
        parts.append("counties=" + counties)
    if cities:
        parts.append("cities=" + cities)
    return (
        f"{adapter.id}\t{adapter.category}\t{' '.join(parts)}\t"
        f"{adapter.status}\t{str(adapter.enabled).lower()}\t{access_result}"
    )


def list_sources(path=None, check=True):
    lines = ["id\tcategory\tcoverage\tstatus\tenabled\taccess"]
    for adapter in load_adapters(path):
        if check:
            try:
                access = adapter.check_access()
            except Exception as exc:
                access = f"error:{exc.__class__.__name__}"
        else:
            access = "not_checked"
        lines.append(format_source_line(adapter, access))
    return lines
