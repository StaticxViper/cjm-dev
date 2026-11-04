"""Official SAM.gov and USAspending request builders.

SAM.gov Get Opportunities v2 is a GET. ``offset`` is a page index starting at
0, not a record offset. USAspending spending-by-award is a POST. Contract
awards only (award type codes A, B, C, and D). No browser, proxy, or solver.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode


SAM_SEARCH = "https://api.sam.gov/opportunities/v2/search"
AWARD_SEARCH = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

PAGE_SIZE = 100
MAX_PAGES = 5
MAX_NAICS = 10
MAX_ITEMS = 200
DEFAULT_ITEMS = 50
DATE_WINDOW_DAYS = 90

CONTRACT_AWARD_TYPES = ("A", "B", "C", "D")
AWARD_FIELDS = (
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "NAICS Code",
    "Description",
    "Start Date",
    "End Date",
)

SET_ASIDES = (
    "SBA",
    "SBP",
    "8A",
    "8AN",
    "HZC",
    "HZS",
    "SDVOSBC",
    "SDVOSBS",
    "WOSB",
    "WOSBSS",
    "EDWOSB",
    "EDWOSBSS",
    "LAS",
    "IEE",
    "ISBEE",
    "BICiv",
    "VSA",
    "VSS",
)

STATES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY", "PR", "GU", "VI", "AS", "MP",
)

SOURCES = ("opportunities", "awards")

_NAICS = re.compile(r"^\d{2,6}$")
_NOTICE = re.compile(r"^[A-Za-z0-9]+$")
_AWARD_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_KEY_QUERY = re.compile(r"[?&]?api_key=[^&\s\"']+", re.I)


def redact(text, secret=""):
    """Drop a SAM API key from a URL or an error string."""
    cleaned = _KEY_QUERY.sub("", str(text or ""))
    secret = str(secret or "")
    if len(secret) >= 8 and secret in cleaned:
        cleaned = cleaned.replace(secret, "REDACTED")
    return cleaned


def mdy(iso_day):
    """YYYY-MM-DD to the MM/dd/yyyy form SAM.gov requires."""
    year, month, day = iso_day.split("-")
    return f"{month}/{day}/{year}"


def sam_request(config, naics, offset, limit):
    params = {
        "api_key": config["sam_api_key"],
        "postedFrom": mdy(config["posted_from"]),
        "postedTo": mdy(config["posted_to"]),
        "limit": str(int(limit)),
        "offset": str(int(offset)),
    }
    if naics:
        params["ncode"] = naics
    if config.get("state"):
        params["state"] = config["state"]
    if config.get("set_aside"):
        params["typeOfSetAside"] = config["set_aside"]
    return {
        "method": "GET",
        "url": SAM_SEARCH + "?" + urlencode(params),
        "json": None,
    }


def award_request(config, page, limit):
    filters = {
        "award_type_codes": list(CONTRACT_AWARD_TYPES),
        "time_period": [{
            "start_date": config["posted_from"],
            "end_date": config["posted_to"],
        }],
    }
    if config.get("naics"):
        filters["naics_codes"] = {"require": list(config["naics"])}
    if config.get("state"):
        filters["place_of_performance_locations"] = [{
            "country": "USA",
            "state": config["state"],
        }]
    if config.get("set_aside"):
        filters["set_aside_type_codes"] = [config["set_aside"]]
    return {
        "method": "POST",
        "url": AWARD_SEARCH,
        "json": {
            "filters": filters,
            "fields": list(AWARD_FIELDS),
            "limit": int(limit),
            "page": int(page),
            "sort": "Award Amount",
            "order": "desc",
        },
    }


def opportunity_url(notice_id):
    notice = str(notice_id or "").strip()
    if not _NOTICE.fullmatch(notice):
        return ""
    return f"https://sam.gov/opp/{notice}/view"


def award_url(generated_id):
    key = str(generated_id or "").strip()
    if not _AWARD_KEY.fullmatch(key):
        return ""
    return f"https://www.usaspending.gov/award/{key}"
