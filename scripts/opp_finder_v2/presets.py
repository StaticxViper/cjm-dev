"""Saved search presets. The shipped file is the starting set; the menu edits it."""

from __future__ import annotations

import json
import re
from pathlib import Path

from opp_finder_v2.config import PACKAGE_DIR, ConfigError
from opp_finder_v2.search_setup import KEYWORD_MODES, EMPLOYMENT_TYPES, SearchSetup

PRESETS_PATH = PACKAGE_DIR / "presets.json"


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "preset"


def load_presets(path: Path | None = None) -> list[dict]:
    path = path or PRESETS_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError([f"{path}: {exc}"]) from exc
    presets = document.get("presets") if isinstance(document, dict) else None
    if not isinstance(presets, list):
        raise ConfigError([f"{path}: expected a presets list"])
    return presets


def save_presets(presets: list[dict], path: Path | None = None) -> None:
    path = path or PRESETS_PATH
    payload = {"version": 1, "presets": presets}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def find_preset(presets: list[dict], query: str) -> dict:
    target = _normalize(query)
    for preset in presets:
        names = [_normalize(str(preset.get("id") or "")), _normalize(str(preset.get("name") or ""))]
        if target and target in names:
            return preset
    known = ", ".join(str(preset.get("name") or preset.get("id")) for preset in presets)
    raise ConfigError([f"unknown preset: {query}", f"presets: {known}"])


def setup_from_preset(preset: dict) -> SearchSetup:
    employment = preset.get("employment") or "any"
    keyword_mode = preset.get("keyword_mode") or "custom"
    if employment not in EMPLOYMENT_TYPES:
        raise ConfigError([f"{preset.get('name')}: unknown employment {employment}"])
    if keyword_mode not in KEYWORD_MODES:
        raise ConfigError([f"{preset.get('name')}: unknown keyword_mode {keyword_mode}"])
    skill_ids = preset.get("skill_ids")
    return SearchSetup(
        name=str(preset.get("name") or preset.get("id") or "Preset"),
        employment=employment,
        remote_only=bool(preset.get("remote_only", True)),
        keyword_mode=keyword_mode,
        keywords=[str(item) for item in (preset.get("keywords") or [])],
        skill_ids=[str(item) for item in skill_ids] if isinstance(skill_ids, list) else None,
        min_relevance=preset.get("min_relevance"),
        clear_rates=bool(preset.get("clear_rates")),
        upload_crm=True,
    )


def upsert_preset(presets: list[dict], setup: SearchSetup) -> dict:
    """Insert or replace a preset by name. Returns the stored record."""
    record = {"id": slugify(setup.name), **setup.to_dict()}
    target = _normalize(setup.name)
    for index, preset in enumerate(presets):
        if _normalize(str(preset.get("name") or "")) == target or preset.get("id") == record["id"]:
            record["id"] = str(preset.get("id") or record["id"])
            presets[index] = record
            return record
    presets.append(record)
    return record


def delete_preset(presets: list[dict], query: str) -> dict:
    preset = find_preset(presets, query)
    presets.remove(preset)
    return preset
