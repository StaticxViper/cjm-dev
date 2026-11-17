"""Verified UCC open-data feeds.

Checked 2026-11-16:

* Connecticut ``xfev-8smz`` on data.ct.gov. Connecticut Office of the
  Secretary of the State. ``licenseId`` PUBLIC_DOMAIN. ``robots.txt`` allows
  ``/resource/*.json`` and sets Crawl-delay 1. ``/api/odata/`` is disallowed
  and is not requested. Commercial UCC-1 rows are ``ORIG FIN STMT`` plus
  ``OFS``. IRS, municipal, labor, vessel, and aircraft liens are left out.
* Oregon ``snfi-f79b`` on data.oregon.gov. "UCC List of Filings Entered Last
  Month." ``licenseId`` PUBLIC_DOMAIN. Same robots rules. The file is the
  previous calendar month, not a rolling 7-day feed.
* Colorado ``wffy-3uut`` is public but has no debtor or secured-party names.
* Florida Sunbiz and New Jersey are HTML search portals. Kentucky bulk UCC
  is a paid subscriber file. Those states are unsupported and are not fetched.

Every SODA request sends ``$limit`` at or below the page size. CSV exports
are refused.
"""

from __future__ import annotations

from urllib.parse import urlencode


PAGE_SIZE = 100
MAX_PAGES = 8
DATE_WINDOW_DAYS = 7
MAX_SPAN_DAYS = 92
DEFAULT_STATE = "CT"
TERMS_CHECKED = "2026-11-16"
MAX_STATES = 10

# Connecticut amendment-family codes on an original financing statement.
# Tax, municipal, vessel, and aircraft liens are not in this list.
CT_UCC3 = (
    "AMENDMENT",
    "CONTINUATION",
    "ASSIGNMENT",
    "TERMINATION",
    "CORRECTION",
    "PARTIAL RELEASE",
    "OFFICE CORRECT",
)

POSTAL = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
)

NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

VERIFIED = {
    "CT": {
        "state": "CT",
        "kind": "ct",
        "source": "data.ct.gov",
        "endpoint": "https://data.ct.gov/resource/xfev-8smz.json",
        "page": "https://data.ct.gov/Business/Uniform-Commercial-Code-UCC-Lien-Filings/xfev-8smz",
        "order": "dt_accept DESC, id_ucc_flng_nbr",
        "attribution": "Connecticut Office of the Secretary of the State",
        "license": "PUBLIC_DOMAIN",
    },
    "OR": {
        "state": "OR",
        "kind": "or",
        "source": "data.oregon.gov",
        "endpoint": "https://data.oregon.gov/resource/snfi-f79b.json",
        "page": "https://data.oregon.gov/business/UCC-List-of-Filings-Entered-Last-Month/snfi-f79b",
        "order": "filing_date DESC, file_number",
        "attribution": "Oregon Secretary of State",
        "license": "PUBLIC_DOMAIN",
    },
}

UNSUPPORTED = {
    "CO": (
        "Colorado publishes UCC filing dates and types at data.colorado.gov "
        "(wffy-3uut) but that open file has no debtor or secured-party names."
    ),
    "FL": "Florida Sunbiz UCC search is an HTML portal, not an official JSON or bulk file.",
    "NJ": "New Jersey UCC search is a portal, not an official JSON or bulk file.",
    "KY": "Kentucky UCC bulk files are a paid subscriber service, not open data.",
}


def unsupported_reason(state):
    specific = UNSUPPORTED.get(state)
    if specific:
        return specific
    name = NAMES.get(state) or state or "This state"
    return (
        f"{name} has no verified Secretary of State UCC open-data file in this version. "
        "Portal search, CAPTCHA, and paid bulk feeds are not requested."
    )


def guard_url(url):
    """Refuse a statewide export and any SODA URL that forgot ``$limit``."""
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


def _window(field, start, end):
    return f"{field} between '{start}T00:00:00' and '{end}T23:59:59'"


def where_clause(feed, filing_types, start, end):
    """SoQL for the requested filing types. Values are codes we chose, not free text."""
    kind = feed["kind"]
    if kind == "ct":
        parts = []
        if "UCC-1" in filing_types:
            parts.append("(cd_flng_type = 'ORIG FIN STMT' AND tx_lien_descript = 'OFS')")
        if "UCC-3" in filing_types:
            codes = ", ".join(f"'{code}'" for code in CT_UCC3)
            parts.append(f"(tx_lien_descript = 'OFS' AND cd_flng_type in ({codes}))")
        if not parts:
            raise ValueError("no filing type")
        return f"({' OR '.join(parts)}) AND {_window('dt_accept', start, end)}"
    if kind == "or":
        forms = []
        if "UCC-1" in filing_types:
            forms.append("INITIAL")
        if "UCC-3" in filing_types:
            forms.append("AMENDMENT")
        if not forms:
            raise ValueError("no filing type")
        listed = ", ".join(f"'{item}'" for item in forms)
        return f"lien_type = 'UCC' AND file_type in ({listed}) AND {_window('filing_date', start, end)}"
    raise ValueError(f"unknown feed {kind}")
