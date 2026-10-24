"""New Jersey Department of Community Affairs registered new-home builders.

Verified 2026-10-24: the public builders page no longer links a PDF or CSV.
"List of Registered Builders" points at the DCA service portal, whose anonymous
response does not include builder records. This adapter does not open that
portal. Home-improvement registrations on newjersey.mylicense.com are a
different board (Division of Consumer Affairs) and are not requested.
"""

from __future__ import annotations

from urllib.parse import urlparse

try:
    from .base import html_links, outcome, status_row, transport_row
except ImportError:
    from adapters.base import html_links, outcome, status_row, transport_row


BUILDERS_URL = "https://www.nj.gov/dca/codes/publications/registered_builders.shtml"
PORTAL_HOST = "serviceportal.dca.nj.gov"

_MESSAGES = {
    "captcha": "NJ DCA returned a challenge page. This adapter does not bypass it.",
}
_UNSUPPORTED = (
    "NJ Department of Community Affairs does not publish an open builder file. "
    "The public page links to a service portal that does not return records anonymously. "
    "This adapter does not open that portal or the Consumer Affairs mylicense form."
)


def lookup(query, fetch):
    page = fetch(BUILDERS_URL)
    failed = transport_row(query, page, _MESSAGES, BUILDERS_URL)
    if failed is not None:
        return outcome([failed])
    data_link = ""
    portal = False
    for href, text in html_links(page.get("text") or "", BUILDERS_URL):
        host = urlparse(href).netloc.lower()
        path = urlparse(href).path.lower()
        label = text.lower()
        if PORTAL_HOST in host:
            portal = True
            continue
        if "privacy" in path or "privacy" in label:
            continue
        spreadsheet = path.endswith((".csv", ".xls", ".xlsx", ".json"))
        builder_pdf = path.endswith(".pdf") and "builder" in label
        if spreadsheet or builder_pdf:
            data_link = href
            break
    if data_link:
        return outcome([
            status_row(
                query,
                "unsupported",
                "NJ DCA linked a data file this adapter has not verified, so it was not downloaded.",
                data_link,
            ),
        ])
    if portal:
        return outcome([status_row(query, "unsupported", _UNSUPPORTED, BUILDERS_URL)])
    return outcome([
        status_row(
            query,
            "unsupported",
            "NJ DCA builders page had no open data file.",
            BUILDERS_URL,
        ),
    ])
