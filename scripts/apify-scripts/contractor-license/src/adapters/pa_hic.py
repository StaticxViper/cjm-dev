"""Pennsylvania home-improvement contractor registration.

Verified 2026-10-24: Pennsylvania does not license general contractors
statewide. The public contractor registry is the Attorney General HIC search
at hicsearch.attorneygeneral.gov (Home Improvement Consumer Protection Act),
not the PALS professional-license system. The search page loads Cloudflare
Turnstile and the results form is not submitted. Municipal contractor licenses
are out of scope.
"""

from __future__ import annotations

try:
    from .base import is_challenge, outcome, status_row, transport_row
except ImportError:
    from adapters.base import is_challenge, outcome, status_row, transport_row


SEARCH_URL = "https://hicsearch.attorneygeneral.gov/"

_MESSAGES = {
    "captcha": (
        "Pennsylvania home-improvement search asks for a Cloudflare Turnstile check. "
        "This adapter does not solve CAPTCHAs or submit the form."
    ),
}
_FORM_HELD = (
    "Pennsylvania HIC search did not show a challenge, and this adapter does not "
    "submit the form until that path is verified as open data."
)


def lookup(query, fetch):
    page = fetch(SEARCH_URL)
    failed = transport_row(query, page, _MESSAGES, SEARCH_URL)
    if failed is not None:
        return outcome([failed])
    # transport_row already classifies challenge bodies. A clean HTML page is
    # still not searched: there is no verified open file behind this form.
    if is_challenge(page.get("text") or "", page.get("content_type") or ""):
        return outcome([status_row(query, "captcha", _MESSAGES["captcha"], SEARCH_URL)])
    return outcome([status_row(query, "unsupported", _FORM_HELD, SEARCH_URL)])
