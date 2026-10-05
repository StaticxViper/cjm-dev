"""Map adapter field dicts into scored Opportunity records."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

from opp_finder_v2.dedupe import assign_identity
from opp_finder_v2.models import Criteria, Opportunity, RawListing, SiteConfig
from opp_finder_v2.parsing import (
    as_string_list,
    collapse_ws,
    html_to_text,
    infer_remote,
    join_location,
    normalize_employment,
    normalize_unit,
    parse_posted_date,
    parse_salary_text,
    positive_number,
    snippet_text,
)
from opp_finder_v2.relevance import apply_relevance

_STRING_FIELDS = {
    "title": "title",
    "company": "company",
    "url": "url",
    "apply_url": "apply_url",
    "posted_date": "posted_date",
    "salary": "salary_text",
    "salary_text": "salary_text",
    "snippet": "snippet",
    "description": "snippet",
    "currency": "currency",
    "rate_unit": "rate_unit",
    "employment_type": "employment_type",
}


def mapped_to_raw(mapped: dict, site: SiteConfig, scraped_at: str) -> RawListing:
    raw = RawListing(source_site=site.id, scraped_at=scraped_at)
    for key, value in mapped.items():
        if value is None:
            continue
        if key in {"salary_min", "rate_min"}:
            raw.salary_min = positive_number(value)
            continue
        if key in {"salary_max", "rate_max"}:
            raw.salary_max = positive_number(value)
            continue
        if key == "location":
            raw.location = join_location(value)
            continue
        if key == "tags":
            raw.tags = as_string_list(value)
            continue
        if key == "remote":
            if isinstance(value, bool):
                raw.remote = value
            continue
        attr = _STRING_FIELDS.get(key)
        if attr and not isinstance(value, (dict, list)):
            setattr(raw, attr, collapse_ws(str(value)) or None)
        elif key == "employment_type":
            raw.employment_type = value if isinstance(value, str) else value
    if raw.title:
        raw.title = collapse_ws(html_to_text(raw.title))
    return raw


def _absolute(url: str | None, base_url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    return urljoin(base_url.rstrip("/") + "/", text)


def build_opportunity(
    raw: RawListing,
    site: SiteConfig,
    criteria: Criteria,
    scraped_at: datetime,
) -> tuple[Opportunity | None, str | None]:
    title = collapse_ws(html_to_text(raw.title))
    if not title:
        return None, "empty_title"
    url = _absolute(raw.url, site.base_url)
    if not url:
        return None, "empty_url"
    snippet = snippet_text(raw.snippet)
    parsed = parse_salary_text(raw.salary_text) or parse_salary_text(snippet)
    rate_min = raw.salary_min
    rate_max = raw.salary_max
    rate_unit = normalize_unit(raw.rate_unit)
    currency = (raw.currency or "").strip() or None
    salary_text = raw.salary_text
    if parsed:
        salary_text = salary_text or parsed["salary_text"]
        if rate_min is None:
            rate_min = parsed["rate_min"]  # type: ignore[assignment]
        if rate_max is None:
            rate_max = parsed["rate_max"]  # type: ignore[assignment]
        rate_unit = rate_unit or parsed["rate_unit"]  # type: ignore[assignment]
        currency = currency or parsed["currency"]  # type: ignore[assignment]
    if rate_max is None:
        rate_max = rate_min
    if currency:
        currency = currency.upper()
        if currency in {"$"}:
            currency = "USD"

    if raw.remote is not None:
        remote = raw.remote
    else:
        remote = infer_remote(raw.location, raw.tags, snippet)
        if remote is None and "remote" in (site.listing_defaults or {}):
            remote = bool(site.listing_defaults["remote"])

    employment = normalize_employment(raw.employment_type)
    if employment is None:
        employment = normalize_employment(f"{title} {snippet or ''}")

    posted = parse_posted_date(raw.posted_date, scraped_at)
    scraped_text = raw.scraped_at
    opp = Opportunity(
        opp_id="",
        title=title,
        company=collapse_ws(raw.company) or None,
        location=raw.location,
        remote=remote,
        url=url,
        apply_url=_absolute(raw.apply_url, site.base_url) or None,
        source_site=site.id,
        sources=[{"site": site.id, "url": url, "scraped_at": scraped_text}],
        posted_date=posted,
        snippet=snippet,
        salary_text=collapse_ws(salary_text) or None,
        rate_min=rate_min,
        rate_max=rate_max,
        rate_unit=rate_unit,
        currency=currency,
        employment_type=employment,
        tags=list(raw.tags),
        matched_keywords=[],
        relevance_score=0,
        score_breakdown={},
        scraped_at=scraped_text,
    )
    assign_identity(opp)
    reason = apply_relevance(opp, criteria, scraped_at)
    return opp, reason
