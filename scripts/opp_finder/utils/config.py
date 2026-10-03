"""Configuration helpers for multi-location targeting and remote priority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.yaml"

# Used when config has no remote search phrases.
DEFAULT_REMOTE_PHRASES = [
    "Remote United States",
    "Remote US",
    "Work from home United States",
    "Fully remote US",
    "United States remote",
]


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load YAML config; return a deep-enough mutable dict."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(config_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")
    return data


def flatten_keywords(config: dict[str, Any]) -> list[str]:
    """Return unique keyword strings from all configured groups."""
    keywords_cfg = config.get("keywords") or {}
    seen: set[str] = set()
    ordered: list[str] = []
    if isinstance(keywords_cfg, dict):
        groups = keywords_cfg.values()
    elif isinstance(keywords_cfg, list):
        groups = [keywords_cfg]
    else:
        groups = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            text = str(item or "").strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            ordered.append(text)
    return ordered


def resolve_path(config: dict[str, Any], key: str) -> Path:
    """Resolve an output path relative to the opp_finder script directory."""
    output_cfg = config.get("output") or {}
    rel = output_cfg.get(key)
    if not rel:
        raise KeyError(f"Missing output.{key} in config")
    path = Path(rel)
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path


def configured_locations(config: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return normalized location region dicts.

    Prefers config['locations'] (multi-region). Falls back to legacy config['location'].
    """
    regions = config.get("locations")
    if isinstance(regions, list) and regions:
        normalized: list[dict[str, Any]] = []
        for raw in regions:
            if not isinstance(raw, dict):
                continue
            states = raw.get("states") or raw.get("state") or []
            if isinstance(states, str):
                states = [states]
            counties = raw.get("counties") or []
            place_hints = raw.get("place_hints") or []
            phrases = raw.get("search_phrases") or raw.get("location_phrases") or []
            normalized.append(
                {
                    "name": str(raw.get("name") or "region"),
                    "states": [str(s).strip() for s in states if str(s).strip()],
                    "counties": [str(c).strip() for c in counties if str(c).strip()],
                    "place_hints": [str(p).strip() for p in place_hints if str(p).strip()],
                    "search_phrases": [str(p).strip() for p in phrases if str(p).strip()],
                    "enabled": bool(raw.get("enabled", True)),
                }
            )
        return [r for r in normalized if r.get("enabled", True)]

    legacy = config.get("location") or {}
    if not legacy:
        return []
    state = legacy.get("state")
    states = [state] if state else []
    phrases = (config.get("search") or {}).get("location_phrases") or []
    return [
        {
            "name": "default",
            "states": [str(s) for s in states if s],
            "counties": list(legacy.get("counties") or []),
            "place_hints": list(legacy.get("place_hints") or []),
            "search_phrases": list(phrases),
            "enabled": True,
        }
    ]


def remote_search_phrases(config: dict[str, Any]) -> list[str]:
    search_cfg = config.get("search") or {}
    phrases = search_cfg.get("remote_phrases") or DEFAULT_REMOTE_PHRASES
    ordered: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        text = str(phrase or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        ordered.append(text)
    return ordered


def build_location_phrases(
    config: dict[str, Any],
    *,
    prioritize_remote: bool = True,
    include_remote: bool = True,
    region_names: list[str] | None = None,
) -> list[str]:
    """
    Build ordered search location phrases.

    When prioritize_remote is True, remote phrases come first so discovery
    spends early budget on remote roles across the U.S.
    """
    regions = configured_locations(config)
    if region_names:
        wanted = {n.lower() for n in region_names}
        regions = [r for r in regions if r["name"].lower() in wanted]

    local_phrases: list[str] = []
    seen: set[str] = set()

    def _add(phrase: str) -> None:
        text = str(phrase or "").strip()
        key = text.lower()
        if not text or key in seen:
            return
        seen.add(key)
        local_phrases.append(text)

    # Explicit search.location_phrases still honored (after remotes when prioritized).
    for phrase in (config.get("search") or {}).get("location_phrases") or []:
        # Skip pure-remote phrases here; they are handled via remote_phrases.
        low = str(phrase).lower()
        if "remote" in low or "work from home" in low:
            continue
        _add(str(phrase))

    for region in regions:
        for phrase in region.get("search_phrases") or []:
            _add(phrase)
        # Synthesize useful phrases from region metadata when search_phrases sparse.
        for state in region.get("states") or []:
            _add(f"{state}")
            if len(state) == 2:
                # Avoid bare "NJ" only; prefer named regions from search_phrases.
                pass
        for county in (region.get("counties") or [])[:6]:
            states = region.get("states") or []
            suffix = f" {states[0]}" if states else ""
            _add(f"{county} County{suffix}")

    remote_phrases = remote_search_phrases(config) if include_remote else []
    if prioritize_remote and include_remote:
        return remote_phrases + local_phrases
    if include_remote:
        return local_phrases + remote_phrases
    return local_phrases


def prioritize_remote_enabled(config: dict[str, Any], options: dict[str, Any] | None = None) -> bool:
    opts = options or {}
    if opts.get("prioritize_remote") is not None:
        return bool(opts.get("prioritize_remote"))
    if opts.get("no_prioritize_remote"):
        return False
    return bool(config.get("prioritize_remote", True))
