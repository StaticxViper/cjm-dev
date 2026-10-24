"""Arizona Registrar of Contractors posting list.

Verified 2026-10-24: roc.az.gov/posting-list links a dated
"All Current Contractors" CSV. A plain HTTP client from this network received
a Cloudflare challenge for both the page and the file. This adapter parses the
public HTML and CSV when they are served, and returns captcha when the body is
a challenge. It does not open a browser to get past Cloudflare, and it does
not use the Salesforce contractor search.

The current-contractor file has no bond or insurance columns. Those fields
are left blank. Qualifying-party names are not copied into the dataset.
"""

from __future__ import annotations

try:
    from .base import (
        csv_dicts,
        found_row,
        html_links,
        join_address,
        outcome,
        record_matches,
        status_row,
        take_match,
        transport_row,
    )
except ImportError:
    from adapters.base import (
        csv_dicts,
        found_row,
        html_links,
        join_address,
        outcome,
        record_matches,
        status_row,
        take_match,
        transport_row,
    )


POSTING_URL = "https://roc.az.gov/posting-list"

_MESSAGES = {
    "captcha": "Arizona ROC returned a Cloudflare challenge. This adapter does not bypass it.",
}


def _csv_url(html):
    for href, text in html_links(html, POSTING_URL):
        if text.lower() == "all current contractors" and href.lower().split("?", 1)[0].endswith(".csv"):
            return href
    return ""


def _class_text(row):
    code = row.get("Class") or ""
    detail = row.get("Class Detail") or ""
    if code and detail:
        return f"{code} {detail}"
    return code or detail


def lookup(query, fetch):
    page = fetch(POSTING_URL)
    failed = transport_row(query, page, _MESSAGES, POSTING_URL)
    if failed is not None:
        return outcome([failed])
    csv_url = _csv_url(page.get("text") or "")
    if not csv_url:
        return outcome([
            status_row(
                query,
                "error",
                "The posting list did not include an All Current Contractors CSV.",
                POSTING_URL,
            ),
        ])
    filed = fetch(csv_url)
    failed = transport_row(query, filed, _MESSAGES, POSTING_URL)
    if failed is not None:
        return outcome([failed])
    found = []
    seen = set()
    truncated = False
    saw_header = "license no" in (filed.get("text") or "").lower()
    for row in csv_dicts(filed.get("text") or "", "License No"):
        class_text = _class_text(row)
        names = [row.get("Business Name") or "", row.get("Doing Business As") or ""]
        if not record_matches(query, row.get("License No"), names, class_text):
            continue
        business = row.get("Business Name") or ""
        dba = row.get("Doing Business As") or ""
        name = business
        if dba and dba.lower() != business.lower():
            name = f"{business} dba {dba}".strip()
        record = found_row(
            query,
            license_no=row.get("License No"),
            name=name,
            status=row.get("Status"),
            issue_date=row.get("Issued Date"),
            expiry_date=row.get("Expiration Date"),
            bond="",
            insurance="",
            address=join_address(row.get("Address"), row.get("City"), row.get("State"), row.get("Zip")),
            source_url=csv_url,
        )
        record["class"] = class_text
        if take_match(found, seen, query, record):
            truncated = True
            break
    if not saw_header:
        return outcome([
            status_row(query, "error", "AZ ROC contractor file had no license header.", POSTING_URL),
        ])
    if not found:
        return outcome([
            status_row(
                query,
                "not_found",
                "No license matched this search in the AZ ROC current-contractor file.",
                POSTING_URL,
            ),
        ])
    return outcome(found, truncated)
