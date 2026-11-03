"""Public iTunes review endpoints.

Google Play is not requested. The Play details page is a JavaScript shell
whose reviews load through a batchexecute session, and there is no stable
public unproxied document to fixture-test. A non-empty playIds list becomes
one blocked row and the run stops.
"""

from __future__ import annotations

import re
from urllib.parse import quote


MAX_PAGES = 10

_BARE_ID = re.compile(r"^\d{1,18}$")
_QUERY_ID = re.compile(r"(?:^|[?&#])id=(\d{1,18})(?!\d)", re.I)
_PATH_ID = re.compile(r"/id(\d{1,18})(?!\d)", re.I)
_PREFIX_ID = re.compile(r"^id(\d{1,18})$", re.I)


def normalize_app_id(value):
    """iTunes numeric id from a bare id, an ``id`` prefix, or a store URL."""
    text = str(value or "").strip()
    if not text:
        return ""
    if _BARE_ID.fullmatch(text):
        return text
    match = _QUERY_ID.search(text)
    if match:
        return match.group(1)
    match = _PATH_ID.search(text)
    if match:
        return match.group(1)
    match = _PREFIX_ID.fullmatch(text)
    if match:
        return match.group(1)
    return ""


def lookup_url(app_id, country):
    return (
        "https://itunes.apple.com/lookup?id="
        f"{quote(str(app_id), safe='')}&country={quote(str(country), safe='')}"
    )


def reviews_url(app_id, country, page):
    return (
        f"https://itunes.apple.com/{quote(str(country), safe='')}/rss/customerreviews/"
        f"page={int(page)}/id={quote(str(app_id), safe='')}/sortby=mostrecent/json"
    )
