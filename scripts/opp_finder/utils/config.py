"""Config loading helpers for opp_finder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.yaml"


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
