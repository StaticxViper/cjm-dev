#!/usr/bin/env python3
"""Load and validate niche search presets and intent-score rules."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json

_DIR = Path(__file__).resolve().parent
NICHES_PATH = _DIR / "niches.json"
RULES_PATH = _DIR / "intent_score_rules.json"

REQUIRED_NICHE_FIELDS = (
    "id",
    "display_name",
    "category",
    "search_keywords",
    "related_keywords",
    "negative_keywords",
    "high_value_service_keywords",
    "lead_signals",
    "suggested_min_reviews",
    "suggested_min_rating",
    "service_area_characteristics",
    "scoring_adjustments",
)

REQUIRED_SIGNAL_FIELDS = ("id", "keywords", "fields")


class NicheConfigError(ValueError):
    """Raised when niche or scoring config is invalid."""


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _as_niche_map(raw):
    if isinstance(raw, dict):
        if all(isinstance(v, dict) for v in raw.values()):
            return raw
        raise NicheConfigError("niches.json object values must be niche objects")
    if isinstance(raw, list):
        mapped = {}
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                raise NicheConfigError("Each niche list item needs an id")
            mapped[item["id"]] = item
        return mapped
    raise NicheConfigError("niches.json must be an object or list")


def validate_niche(niche):
    """Raise NicheConfigError if a niche preset is missing required shape."""
    if not isinstance(niche, dict):
        raise NicheConfigError("Niche must be an object")
    missing = [key for key in REQUIRED_NICHE_FIELDS if key not in niche]
    if missing:
        raise NicheConfigError(
            f"Niche {niche.get('id')!r} missing fields: {', '.join(missing)}"
        )
    if not niche.get("display_name"):
        raise NicheConfigError(f"Niche {niche.get('id')!r} needs display_name")
    if not niche.get("search_keywords"):
        raise NicheConfigError(f"Niche {niche['id']!r} needs search_keywords")
    for key in (
        "search_keywords",
        "related_keywords",
        "negative_keywords",
        "high_value_service_keywords",
        "service_area_characteristics",
    ):
        if not isinstance(niche[key], list):
            raise NicheConfigError(f"Niche {niche['id']!r} field {key} must be a list")
    if not isinstance(niche["lead_signals"], list):
        raise NicheConfigError(f"Niche {niche['id']!r} lead_signals must be a list")
    for signal in niche["lead_signals"]:
        if not isinstance(signal, dict):
            raise NicheConfigError(f"Niche {niche['id']!r} has a non-object lead signal")
        missing_signal = [key for key in REQUIRED_SIGNAL_FIELDS if key not in signal]
        if missing_signal:
            raise NicheConfigError(
                f"Niche {niche['id']!r} signal {signal.get('id')!r} missing "
                f"{', '.join(missing_signal)}"
            )
        if not isinstance(signal["keywords"], list) or not isinstance(signal["fields"], list):
            raise NicheConfigError(
                f"Niche {niche['id']!r} signal {signal.get('id')!r} keywords/fields must be lists"
            )
    if not isinstance(niche.get("scoring_adjustments"), dict):
        raise NicheConfigError(f"Niche {niche['id']!r} scoring_adjustments must be an object")
    return niche


def load_niches(path=None):
    """Return {id: niche} from niches.json, validating every preset."""
    raw = _read_json(Path(path) if path is not None else NICHES_PATH)
    mapped = _as_niche_map(raw)
    validated = {}
    for niche_id, niche in mapped.items():
        item = dict(niche)
        item.setdefault("id", niche_id)
        if item["id"] != niche_id:
            raise NicheConfigError(f"Niche id mismatch: key={niche_id!r} id={item['id']!r}")
        validate_niche(item)
        validated[niche_id] = item
    if not validated:
        raise NicheConfigError("niches.json contained no niches")
    return validated


def get_niche(niche_id, niches=None):
    """Return one niche by id or display name (case-insensitive)."""
    catalog = niches if niches is not None else load_niches()
    if niche_id in catalog:
        return catalog[niche_id]
    needle = str(niche_id or "").strip().lower()
    for item in catalog.values():
        if item["id"].lower() == needle or item["display_name"].lower() == needle:
            return item
    raise NicheConfigError(f"Unknown niche: {niche_id}")


def list_niches(niches=None):
    """Return niches in stable display order."""
    catalog = niches if niches is not None else load_niches()
    return sorted(catalog.values(), key=lambda item: (item.get("sort_order", 1000), item["display_name"]))


def _unique_keep_order(values):
    seen = set()
    out = []
    for raw in values:
        text = " ".join(str(raw or "").split()).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def build_search_queries(niche, extra_keywords=()):
    """Return unique Places/Maps queries from search + related + extras."""
    values = list(niche.get("search_keywords") or [])
    values.extend(niche.get("related_keywords") or [])
    values.extend(extra_keywords or [])
    queries = _unique_keep_order(values)
    if not queries:
        raise NicheConfigError(f"Niche {niche.get('id')!r} produced no search queries")
    return queries


def matches_negative_keywords(text, niche):
    """True if haystack contains a configured negative keyword."""
    haystack = (text or "").lower()
    if not haystack:
        return False
    for term in niche.get("negative_keywords") or []:
        needle = str(term or "").strip().lower()
        if needle and needle in haystack:
            return True
    return False


def load_score_rules(path=None):
    """Load global intent scoring / enrichment / preset rules."""
    raw = _read_json(Path(path) if path is not None else RULES_PATH)
    if not isinstance(raw, dict):
        raise NicheConfigError("intent_score_rules.json must be an object")
    for key in ("score_model", "positive", "negative", "enrichment", "result_presets"):
        if key not in raw:
            raise NicheConfigError(f"intent_score_rules.json missing {key}")
    return raw


def merge_score_rules(rules, niche):
    """Return a copy of global rules with niche scoring_adjustments overlaid."""
    merged = deepcopy(rules)
    adjustments = (niche or {}).get("scoring_adjustments") or {}
    for section in ("positive", "negative", "enrichment"):
        overlay = adjustments.get(section)
        if not overlay:
            continue
        target = merged.setdefault(section, {})
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                target[key] = {**target[key], **value}
            else:
                target[key] = value
    for key, value in adjustments.items():
        if key in ("positive", "negative", "enrichment"):
            continue
        merged[key] = value
    return merged
