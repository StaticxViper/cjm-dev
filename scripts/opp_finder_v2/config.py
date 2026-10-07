"""Load and validate sites.json and criteria.json."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from opp_finder_v2.models import Criteria, SiteCatalog, SiteConfig

PACKAGE_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = PACKAGE_DIR / "schemas"
KNOWN_HOOKS = {"", "wwr_title", "hn_hiring"}
SECRET_KEYS = {
    "cookie",
    "cookies",
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "storage_state",
    "api_key",
    "apikey",
    "set-cookie",
}
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__("\n".join(messages))


def schema_path(name: str) -> Path:
    return SCHEMA_DIR / name


def load_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError([f"{path}: {exc}"]) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError([f"{path}: {exc}"]) from exc


def _validator(schema_name: str) -> Draft202012Validator:
    schema = json.loads(schema_path(schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def format_validation_errors(error: jsonschema.ValidationError) -> str:
    parts = [str(item) for item in error.absolute_path]
    path = ".".join(parts) if parts else "(root)"
    return f"{path}: {error.message}"


def validate_instance(instance: Any, schema_name: str) -> list[str]:
    validator = _validator(schema_name)
    return [format_validation_errors(err) for err in validator.iter_errors(instance)]


def _walk_secrets(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if lowered in SECRET_KEYS:
                errors.append(
                    f"{child_path}: inline secret-looking field is not allowed; "
                    "use auth.storage_state_env for a path outside the repo"
                )
            _walk_secrets(child, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_secrets(child, f"{path}[{index}]", errors)


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def replacer(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), match.group(0))

        return _ENV_RE.sub(replacer, value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def validate_sites_document(document: Any) -> list[str]:
    if not isinstance(document, dict):
        return ["(root): site catalogue must be a JSON object"]
    errors = validate_instance(document, "sites.schema.json")
    _walk_secrets(document, "", errors)
    sites = document.get("sites") if isinstance(document.get("sites"), list) else []
    seen: dict[str, int] = {}
    for index, site in enumerate(sites):
        if not isinstance(site, dict):
            continue
        site_id = site.get("id")
        if isinstance(site_id, str):
            if site_id in seen:
                errors.append(
                    f"sites[{index}].id: duplicate site id '{site_id}' "
                    f"(also at sites[{seen[site_id]}])"
                )
            else:
                seen[site_id] = index
        custom = site.get("custom") or ""
        if custom not in KNOWN_HOOKS:
            errors.append(f"sites[{index}].custom: unknown custom hook '{custom}'")
    return errors


def validate_criteria_document(document: Any) -> list[str]:
    if not isinstance(document, dict):
        return ["(root): criteria must be a JSON object"]
    return validate_instance(document, "criteria.schema.json")


def load_sites(path: Path | None = None) -> SiteCatalog:
    path = path or (PACKAGE_DIR / "sites.json")
    document = load_json(path)
    errors = validate_sites_document(document)
    if errors:
        raise ConfigError(errors)
    document = _expand_env(document)
    defaults = document.get("defaults") or {}
    sites = [SiteConfig.from_dict(item, defaults) for item in document["sites"]]
    return SiteCatalog(
        version=int(document["version"]),
        defaults=defaults,
        sites=sites,
        path=path,
    )


def load_criteria(path: Path | None = None) -> Criteria:
    path = path or (PACKAGE_DIR / "criteria.json")
    document = load_json(path)
    errors = validate_criteria_document(document)
    if errors:
        raise ConfigError(errors)
    keywords = document["keywords"]
    location = document["location"]
    min_rate = document["min_rate"]
    return Criteria(
        keywords_any=list(keywords["any"]),
        keywords_all=list(keywords["all"]),
        title_boost=list(keywords["title_boost"]),
        exclude_keywords=list(document["exclude_keywords"]),
        remote_only=bool(document["remote_only"]),
        employment_types=list(document["employment_types"]),
        location_allow=list(location["allow"]),
        location_deny=list(location["deny"]),
        location_unknown=location["unknown"],
        posted_within_days=document["posted_within_days"],
        min_rate_hourly=min_rate["hourly_usd"],
        min_rate_annual=min_rate["annual_usd"],
        min_rate_unknown=min_rate["unknown"],
        min_relevance=int(document["min_relevance"]),
        require_title_match=bool(document.get("require_title_match", False)),
        raw=document,
    )


def select_sites(catalog: SiteCatalog, site_ids: list[str] | None) -> list[SiteConfig]:
    known = [site.id for site in catalog.sites]
    if site_ids is None:
        return [site for site in catalog.sites if site.enabled]
    missing = [site_id for site_id in site_ids if site_id not in known]
    if missing:
        raise ConfigError(
            [
                f"unknown site id: {', '.join(missing)}",
                "valid ids: " + ", ".join(known),
            ]
        )
    by_id = {site.id: site for site in catalog.sites}
    return [by_id[site_id] for site_id in site_ids]


def format_site_table(catalog: SiteCatalog) -> str:
    rows = [
        f"{'id':<20} {'name':<32} {'mode':<12} {'access':<16} {'enabled':<8} risk"
    ]
    for site in catalog.sites:
        risk = (site.tos or {}).get("risk") or ""
        rows.append(
            f"{site.id:<20} {site.name[:32]:<32} {site.mode:<12} "
            f"{site.access:<16} {str(site.enabled).lower():<8} {risk}"
        )
    return "\n".join(rows)
