"""Hard filters and a deterministic relevance score.

Unknown date, rate, location, remote, and employment type never add points
and never reject a record, unless that field's configured unknown policy is
"drop". Missing data is not treated as a positive signal.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from opp_finder_v2.models import Criteria, Opportunity
from opp_finder_v2.parsing import HOURS_PER_YEAR, html_to_text, collapse_ws

TITLE_KEYWORD_POINTS = 15
TITLE_KEYWORD_CAP = 45
TITLE_BOOST_POINTS = 10
TITLE_BOOST_CAP = 10
BODY_KEYWORD_POINTS = 5
BODY_KEYWORD_CAP = 20
REMOTE_ALLOW_POINTS = 10
EMPLOYMENT_PREFERRED_POINTS = 10
EMPLOYMENT_OTHER_POINTS = 5
RECENCY_3_DAY_POINTS = 10
RECENCY_7_DAY_POINTS = 5
RATE_POINTS = 5

BREAKDOWN_KEYS = (
    "title_keywords",
    "title_boost",
    "body_keywords",
    "remote",
    "employment_type",
    "recency",
    "rate",
)


def normalize_match_text(value: str | None) -> str:
    text = html_to_text(value).lower()
    return collapse_ws(text)


def contains_keyword(text: str, keyword: str) -> bool:
    needle = normalize_match_text(keyword)
    if not needle:
        return False
    pattern = rf"\b{re.escape(needle)}\b"
    return re.search(pattern, text) is not None


def location_matches(location: str | None, phrases: list[str]) -> bool:
    text = normalize_match_text(location)
    if not text:
        return False
    return any(contains_keyword(text, phrase) for phrase in phrases if phrase.strip())


def _hourly_and_annual(opp: Opportunity) -> tuple[float | None, float | None]:
    if opp.currency and opp.currency.upper() not in {"USD", "$", "US$"}:
        return None, None
    amount = opp.rate_max if opp.rate_max is not None else opp.rate_min
    if amount is None or not opp.rate_unit:
        return None, None
    if opp.rate_unit == "hour":
        return amount, amount * HOURS_PER_YEAR
    if opp.rate_unit == "year":
        return amount / HOURS_PER_YEAR, amount
    if opp.rate_unit == "month":
        annual = amount * 12
        return annual / HOURS_PER_YEAR, annual
    return None, None


def rate_status(opp: Opportunity, criteria: Criteria) -> str:
    """Return 'meet', 'below', or 'unknown'."""
    hourly, annual = _hourly_and_annual(opp)
    if hourly is None and annual is None:
        return "unknown"
    if opp.rate_unit == "hour" and criteria.min_rate_hourly is not None:
        return "meet" if hourly >= criteria.min_rate_hourly else "below"
    if opp.rate_unit == "year" and criteria.min_rate_annual is not None:
        return "meet" if annual >= criteria.min_rate_annual else "below"
    if opp.rate_unit == "month" and criteria.min_rate_annual is not None:
        return "meet" if annual >= criteria.min_rate_annual else "below"
    if criteria.min_rate_hourly is not None and hourly is not None:
        return "meet" if hourly >= criteria.min_rate_hourly else "below"
    return "unknown"


def _age_days(posted_date: str, scraped_at: datetime) -> int | None:
    try:
        posted = datetime.strptime(posted_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    if scraped_at.tzinfo is None:
        scraped = scraped_at.date()
    else:
        scraped = scraped_at.astimezone(timezone.utc).date()
    return (scraped - posted).days


def score_opportunity(
    opp: Opportunity,
    criteria: Criteria,
    scraped_at: datetime,
) -> tuple[int, dict[str, int], list[str]]:
    title = normalize_match_text(opp.title)
    body = normalize_match_text(opp.snippet)
    matched: list[str] = []
    title_points = 0
    body_points = 0
    seen: set[str] = set()
    for keyword in criteria.keywords_any:
        key = keyword.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        in_title = contains_keyword(title, keyword)
        in_body = contains_keyword(body, keyword)
        if in_title or in_body:
            matched.append(keyword.strip())
        if in_title:
            title_points += TITLE_KEYWORD_POINTS
        elif in_body:
            body_points += BODY_KEYWORD_POINTS
    title_points = min(title_points, TITLE_KEYWORD_CAP)
    body_points = min(body_points, BODY_KEYWORD_CAP)

    boost = 0
    for keyword in criteria.title_boost:
        if contains_keyword(title, keyword):
            boost = TITLE_BOOST_POINTS
            break
    boost = min(boost, TITLE_BOOST_CAP)

    remote_points = 0
    if opp.remote is True and location_matches(opp.location, criteria.location_allow):
        remote_points = REMOTE_ALLOW_POINTS

    employment_points = 0
    if opp.employment_type and opp.employment_type in criteria.employment_types:
        preferred = set(criteria.employment_types[:2])
        if opp.employment_type in preferred:
            employment_points = EMPLOYMENT_PREFERRED_POINTS
        else:
            employment_points = EMPLOYMENT_OTHER_POINTS

    recency = 0
    if opp.posted_date:
        age = _age_days(opp.posted_date, scraped_at)
        if age is not None and age >= 0:
            if age <= 3:
                recency = RECENCY_3_DAY_POINTS
            elif age <= 7:
                recency = RECENCY_7_DAY_POINTS

    rate_points = RATE_POINTS if rate_status(opp, criteria) == "meet" else 0
    breakdown = {
        "title_keywords": title_points,
        "title_boost": boost,
        "body_keywords": body_points,
        "remote": remote_points,
        "employment_type": employment_points,
        "recency": recency,
        "rate": rate_points,
    }
    total = min(100, sum(breakdown.values()))
    return total, breakdown, sorted(set(matched))


def hard_filter_reason(
    opp: Opportunity,
    criteria: Criteria,
    scraped_at: datetime,
) -> str | None:
    if not (opp.title or "").strip():
        return "empty_title"
    title = normalize_match_text(opp.title)
    body = normalize_match_text(opp.snippet)
    combined = collapse_ws(f"{title} {body}")
    for keyword in criteria.exclude_keywords:
        if contains_keyword(title, keyword) or contains_keyword(body, keyword):
            return "exclude_keyword"
    if criteria.keywords_all:
        if not all(contains_keyword(combined, keyword) for keyword in criteria.keywords_all):
            return "missing_all"
    if criteria.keywords_any:
        in_title = any(contains_keyword(title, keyword) for keyword in criteria.keywords_any)
        in_text = any(contains_keyword(combined, keyword) for keyword in criteria.keywords_any)
        if criteria.require_title_match:
            if not in_title:
                return "no_keyword"
        elif not in_text:
            return "no_keyword"
    if criteria.remote_only and opp.remote is False:
        return "not_remote"
    if opp.location:
        if location_matches(opp.location, criteria.location_deny):
            return "location_deny"
    elif criteria.location_unknown == "drop":
        return "unknown_location"
    if opp.posted_date and criteria.posted_within_days is not None:
        age = _age_days(opp.posted_date, scraped_at)
        if age is not None and age > criteria.posted_within_days:
            return "stale"
    status = rate_status(opp, criteria)
    if status == "below":
        return "below_rate"
    if status == "unknown" and criteria.min_rate_unknown == "drop":
        return "unknown_rate"
    if opp.employment_type:
        if opp.employment_type not in criteria.employment_types:
            return "employment_type"
    return None


def apply_relevance(
    opp: Opportunity,
    criteria: Criteria,
    scraped_at: datetime,
) -> str | None:
    """Score opp in place. Return a drop reason, or None if it is kept."""
    reason = hard_filter_reason(opp, criteria, scraped_at)
    if reason:
        return reason
    score, breakdown, matched = score_opportunity(opp, criteria, scraped_at)
    opp.relevance_score = score
    opp.score_breakdown = breakdown
    opp.matched_keywords = matched
    if score < criteria.min_relevance:
        return "low_relevance"
    return None
