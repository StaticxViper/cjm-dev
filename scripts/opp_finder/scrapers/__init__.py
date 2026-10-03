"""Scraper registry and shared search context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from utils.browser import BrowserSession
from utils.jobs import RawJob


@dataclass
class SearchContext:
    config: dict[str, Any]
    keywords: list[str]
    location_phrases: list[str]
    include_remote: bool = True
    prioritize_remote: bool = True
    south_nj_only: bool = False
    remote_only: bool = False
    region_names: list[str] = field(default_factory=list)
    max_results_per_keyword: int = 25
    max_total_jobs: int = 250
    browser: BrowserSession | None = None
    verbose: bool = False
    collected: list[RawJob] = field(default_factory=list)


class JobScraper(Protocol):
    name: str

    def search(self, ctx: SearchContext) -> list[RawJob]:
        ...


def enabled_scrapers(config: dict[str, Any]) -> list[JobScraper]:
    """Instantiate enabled scrapers in preferred discovery order."""
    from scrapers.google import GoogleScraper
    from scrapers.indeed import IndeedScraper
    from scrapers.ziprecruiter import ZipRecruiterScraper
    from scrapers.craigslist import CraigslistScraper
    from scrapers.company_sites import CompanySitesScraper
    from scrapers.staffing import StaffingScraper

    sources = config.get("sources") or {}
    candidates: list[tuple[str, type]] = [
        ("google", GoogleScraper),
        ("indeed", IndeedScraper),
        ("ziprecruiter", ZipRecruiterScraper),
        ("craigslist", CraigslistScraper),
        ("company_sites", CompanySitesScraper),
        ("staffing", StaffingScraper),
    ]
    scrapers: list[JobScraper] = []
    for key, cls in candidates:
        cfg = sources.get(key) or {}
        if cfg.get("enabled", True):
            scrapers.append(cls())
    return scrapers
