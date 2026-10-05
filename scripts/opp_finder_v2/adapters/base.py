"""Shared URL templates, dotted-path reads, and fixture paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from opp_finder_v2.models import Criteria, SearchQuery, SiteConfig

PACKAGE_DIR = Path(__file__).resolve().parents[1]


def fixture_dir(site_id: str) -> Path:
    return PACKAGE_DIR / "fixtures" / site_id


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def json_fixtures(site_id: str) -> list[Any]:
    folder = fixture_dir(site_id)
    pages = sorted(folder.glob("response_page_*.json"))
    if pages:
        return [load_json_file(path) for path in pages]
    single = folder / "response.json"
    if single.is_file():
        return [load_json_file(single)]
    found = sorted(folder.glob("*.json"))
    return [load_json_file(path) for path in found]


def html_fixtures(site_id: str) -> list[Path]:
    folder = fixture_dir(site_id)
    numbered = sorted(folder.glob("page_*.html"))
    if numbered:
        return numbered
    single = folder / "page.html"
    if single.is_file():
        return [single]
    return sorted(folder.glob("*.html"))


def rss_fixture(site_id: str) -> str:
    folder = fixture_dir(site_id)
    for name in ("feed.xml", "feed.rss"):
        path = folder / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    found = sorted(folder.glob("*.xml"))
    if not found:
        raise FileNotFoundError(f"no RSS fixture for {site_id}")
    return found[0].read_text(encoding="utf-8")


def template_values(
    query: SearchQuery,
    criteria: Criteria,
    site: SiteConfig,
    *,
    page: int,
    offset: int,
) -> dict[str, str]:
    mapping = {}
    if isinstance(site.param_map, dict):
        mapping = site.param_map.get("employment_type") or {}
    employment = ""
    if isinstance(mapping, dict):
        for kind in criteria.employment_types:
            if kind in mapping:
                employment = str(mapping[kind])
                break
    days = criteria.posted_within_days or 0
    text = query.text
    return {
        "keywords": quote(text),
        "keywords_plus": quote_plus(text),
        "page": str(page),
        "offset": str(offset),
        "posted_days": str(days),
        "posted_seconds": str(int(days) * 86400),
        "remote": "true" if criteria.remote_only else "false",
        "employment_type": quote(employment),
    }


def render_template(template: str, values: dict[str, str]) -> str:
    rendered = template or ""
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def dig(payload: Any, path: str | None) -> Any:
    if path is None or path == "":
        return payload
    current = payload
    for part in str(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def page_number(pagination: dict, index: int) -> int:
    start = int(pagination.get("start") or 1)
    step = int(pagination.get("step") or 1)
    return start + index * step


def offset_number(pagination: dict, index: int) -> int:
    start = int(pagination.get("start") or 0)
    step = int(pagination.get("step") or 1)
    return start + index * step
