"""Verified state and local bid feeds. Official JSON only.

Checked 2026-11-16:

* Los Angeles ``hf3r-utnq`` on data.lacity.org. "RAMP Open Bid Opportunities."
  City of Los Angeles. License Creative Commons 1.0 Universal (public domain).
  ``robots.txt`` allows ``/resource/*.json``, sets Crawl-delay 1, and disallows
  ``/api/odata/``. The dataset is open and amended bids. The row's ``url`` is
  stored and is not requested. rampla.org is not scraped.
* Montgomery County ``eeq6-nnwe`` on data.montgomerycountymd.gov. "Solicitations."
  Active and closed solicitations issued in the past 7 years, updated daily.
  The dataset record has no ``licenseId``. The portal Terms of Use allow
  download and derivative use with a required attribution disclaimer, which
  the Actor README carries. Same robots rules. A ``bidtab`` URL is stored
  and the county ASPX page is not requested.

Neither feed needs an app token. A feed flagged ``requires_token`` is skipped
when ``appToken`` is empty, and the other feeds still run. SAM.gov, Bonfire,
BidNet, PlanetBids, and DemandStar are not requested.

Every SODA request sends ``$limit`` at or below the page size. CSV exports
are refused.
"""

from __future__ import annotations

from urllib.parse import urlencode


PAGE_SIZE = 100
MAX_PAGES = 8
DATE_WINDOW_DAYS = 14
MAX_SPAN_DAYS = 92
MAX_SOURCES = 10
DEFAULT_SOURCE = "montgomery_solicitations"
TERMS_CHECKED = "2026-11-16"

POSTAL = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
)

VERIFIED = {
    "los_angeles_ramp": {
        "id": "los_angeles_ramp",
        "name": "Los Angeles open bids",
        "state": "CA",
        "city": "Los Angeles",
        "source": "data.lacity.org",
        "endpoint": "https://data.lacity.org/resource/hf3r-utnq.json",
        "page": "https://data.lacity.org/City-Infrastructure-Service-Requests/RAMP-Open-Bid-Opportunities/hf3r-utnq",
        "order": "bidpost DESC, rampid",
        "date_column": "bidpost",
        "text_columns": ("title", "department", "category", "type", "rampid"),
        "kind": "la",
        "attribution": "City of Los Angeles",
        "license": "CC0 1.0 Universal",
        "requires_token": False,
    },
    "montgomery_solicitations": {
        "id": "montgomery_solicitations",
        "name": "Montgomery County solicitations",
        "state": "MD",
        "city": "",
        "source": "data.montgomerycountymd.gov",
        "endpoint": "https://data.montgomerycountymd.gov/resource/eeq6-nnwe.json",
        "page": "https://data.montgomerycountymd.gov/Government/Solicitations/eeq6-nnwe",
        "order": "issuancedate DESC, number",
        "date_column": "issuancedate",
        "text_columns": ("description", "department", "type", "number", "deptcontact"),
        "kind": "montgomery",
        "attribution": "Montgomery County, Maryland",
        "license": "Portal terms of use (no licenseId on the dataset)",
        "requires_token": False,
    },
}


def unsupported_reason(source_id):
    label = source_id or "This source"
    return (
        f"{label} is not a verified official bid feed in this version. "
        "SAM.gov, Bonfire, BidNet, PlanetBids, DemandStar, and other login portals are not requested."
    )


def guard_url(url):
    """Refuse a full-file export and any SODA URL that forgot ``$limit``."""
    lowered = (url or "").lower()
    if "export.csv" in lowered or "rows.csv" in lowered or "accesstype=download" in lowered:
        return "statewide_export"
    if "limit=" not in lowered:
        return "missing_limit"
    return ""


def soda_url(endpoint, where, limit, offset, order):
    """One bounded SODA page. ``limit`` cannot exceed the page size."""
    size = int(limit)
    if size < 1 or size > PAGE_SIZE:
        raise ValueError("SODA limit is outside the page size")
    if guard_url(endpoint or "") == "statewide_export" or (endpoint or "").lower().endswith(".csv"):
        raise ValueError("statewide export is not requested")
    params = {
        "$where": where,
        "$order": order,
        "$limit": str(size),
        "$offset": str(max(0, int(offset))),
    }
    url = endpoint + "?" + urlencode(params)
    blocked = guard_url(url)
    if blocked:
        raise ValueError(blocked)
    return url


def keyword_clause(columns, keywords):
    """AND of OR-likes. ``keywords`` are already sanitized. Columns are ours."""
    parts = []
    for word in keywords or []:
        likes = " OR ".join(f"upper({column}) like '%{word}%'" for column in columns)
        parts.append(f"({likes})")
    if not parts:
        return ""
    return " AND " + " AND ".join(parts)


def where_clause(feed, start, end, keywords):
    window = (
        f"{feed['date_column']} between '{start}T00:00:00' and '{end}T23:59:59'"
    )
    return window + keyword_clause(feed["text_columns"], keywords)
