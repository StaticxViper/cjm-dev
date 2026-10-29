"""Dataclasses for site config, criteria, listings, and run results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SiteConfig:
    id: str
    name: str
    enabled: bool
    base_url: str
    mode: str
    access: str
    search_url: str = ""
    search_flow: list[dict[str, Any]] = field(default_factory=list)
    param_map: dict[str, Any] = field(default_factory=dict)
    api: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    detail_page: dict[str, Any] = field(default_factory=dict)
    pagination: dict[str, Any] = field(default_factory=dict)
    rate_limit: dict[str, Any] = field(default_factory=dict)
    auth: dict[str, Any] = field(default_factory=dict)
    detection: dict[str, Any] = field(default_factory=dict)
    tos: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    custom: str = ""
    companies: list[str] | None = None
    listing_defaults: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: dict[str, Any] | None = None) -> "SiteConfig":
        defaults = defaults or {}
        rate = dict(defaults.get("rate_limit") or {})
        rate.update(data.get("rate_limit") or {})
        pagination = dict(defaults.get("pagination") or {})
        pagination.update(data.get("pagination") or {})
        companies = data.get("companies")
        return cls(
            id=data["id"],
            name=data.get("name") or data["id"],
            enabled=bool(data.get("enabled", False)),
            base_url=data.get("base_url") or "",
            mode=data.get("mode") or "",
            access=data.get("access") or "guest",
            search_url=data.get("search_url") or "",
            search_flow=list(data.get("search_flow") or []),
            param_map=dict(data.get("param_map") or {}),
            api=dict(data.get("api") or {}),
            results=dict(data.get("results") or {}),
            detail_page=dict(data.get("detail_page") or {}),
            pagination=pagination,
            rate_limit=rate,
            auth=dict(data.get("auth") or {}),
            detection=dict(data.get("detection") or {}),
            tos=dict(data.get("tos") or {}),
            notes=data.get("notes") or "",
            custom=data.get("custom") or "",
            companies=list(companies) if isinstance(companies, list) else None,
            listing_defaults=dict(data.get("listing_defaults") or {}),
        )


@dataclass
class SiteCatalog:
    version: int
    defaults: dict[str, Any]
    sites: list[SiteConfig]
    path: Path


@dataclass
class Criteria:
    keywords_any: list[str]
    keywords_all: list[str]
    title_boost: list[str]
    exclude_keywords: list[str]
    remote_only: bool
    employment_types: list[str]
    location_allow: list[str]
    location_deny: list[str]
    location_unknown: str
    posted_within_days: int | None
    min_rate_hourly: float | None
    min_rate_annual: float | None
    min_rate_unknown: str
    min_relevance: int
    require_title_match: bool = False
    us_only: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def resolved_dict(self) -> dict[str, Any]:
        """Criteria actually used for this run, suitable for the output file."""
        payload = {
            "keywords": {
                "any": list(self.keywords_any),
                "all": list(self.keywords_all),
                "title_boost": list(self.title_boost),
            },
            "exclude_keywords": list(self.exclude_keywords),
            "remote_only": self.remote_only,
            "employment_types": list(self.employment_types),
            "location": {
                "allow": list(self.location_allow),
                "deny": list(self.location_deny),
                "unknown": self.location_unknown,
            },
            "posted_within_days": self.posted_within_days,
            "min_rate": {
                "hourly_usd": self.min_rate_hourly,
                "annual_usd": self.min_rate_annual,
                "unknown": self.min_rate_unknown,
            },
            "min_relevance": self.min_relevance,
            "require_title_match": self.require_title_match,
            "us_only": self.us_only,
        }
        return payload


@dataclass
class SearchQuery:
    keywords: list[str]

    @property
    def text(self) -> str:
        return " ".join(k.strip() for k in self.keywords if k.strip())


@dataclass
class RawListing:
    title: str = ""
    company: str | None = None
    location: str | None = None
    remote: bool | None = None
    url: str = ""
    apply_url: str | None = None
    posted_date: str | None = None
    snippet: str | None = None
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    rate_unit: str | None = None
    currency: str | None = None
    employment_type: str | None = None
    tags: list[str] = field(default_factory=list)
    source_site: str = ""
    scraped_at: str = ""


@dataclass
class Opportunity:
    opp_id: str
    title: str
    company: str | None
    location: str | None
    remote: bool | None
    url: str
    apply_url: str | None
    source_site: str
    sources: list[dict[str, str]]
    posted_date: str | None
    snippet: str | None
    salary_text: str | None
    rate_min: float | None
    rate_max: float | None
    rate_unit: str | None
    currency: str | None
    employment_type: str | None
    tags: list[str]
    matched_keywords: list[str]
    relevance_score: int
    score_breakdown: dict[str, int]
    scraped_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "opp_id": self.opp_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "remote": self.remote,
            "url": self.url,
            "apply_url": self.apply_url,
            "source_site": self.source_site,
            "sources": list(self.sources),
            "posted_date": self.posted_date,
            "snippet": self.snippet,
            "salary_text": self.salary_text,
            "rate_min": self.rate_min,
            "rate_max": self.rate_max,
            "rate_unit": self.rate_unit,
            "currency": self.currency,
            "employment_type": self.employment_type,
            "tags": list(self.tags),
            "matched_keywords": list(self.matched_keywords),
            "relevance_score": self.relevance_score,
            "score_breakdown": dict(self.score_breakdown),
            "scraped_at": self.scraped_at,
        }


@dataclass
class FetchResult:
    listings: list[RawListing] = field(default_factory=list)
    pages: int = 0
    status: str = "ok"
    error: str | None = None
    artifacts: str | None = None


@dataclass
class SiteResult:
    id: str
    status: str
    fetched: int = 0
    matched: int = 0
    kept: int = 0
    pages: int = 0
    duration_s: float = 0.0
    error: str | None = None
    artifacts: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "fetched": self.fetched,
            "matched": self.matched,
            "kept": self.kept,
            "pages": self.pages,
            "duration_s": round(self.duration_s, 3),
            "error": self.error,
        }
        if self.artifacts:
            payload["artifacts"] = self.artifacts
        return payload


@dataclass
class RunOptions:
    config_path: Path
    criteria_path: Path
    keywords: list[str] | None = None
    sites: list[str] | None = None
    out: Path | None = None
    format: str = "json"
    dry_run: bool = False
    headful: bool = False
    max_per_site: int | None = None
    since_days: int | None = None
    allow_login: bool = False
    no_artifacts: bool = False
    verbose: bool = False
    list_sites: bool = False
    validate_only: bool = False
    run_id: str = ""
    artifacts_root: Path | None = None
    upload_crm: bool = False
    crm_venture: str = "Side Job Leads"
    batch_label: str = ""
    employment_types: list[str] | None = None
    remote_only: bool | None = None
    min_relevance: int | None = None
