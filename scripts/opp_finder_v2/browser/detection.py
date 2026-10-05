"""Narrow captcha, login-wall, and block detection.

A noscript "enable javascript" line and the bare word "blocked" are not
treated as blocks. Markers stay specific so ordinary job pages are kept.
"""

from __future__ import annotations

import re

from opp_finder_v2.parsing import collapse_ws, html_to_text

_CAPTCHA_BITS = (
    "verify you are human",
    "verify you are a human",
    "recaptcha",
    "hcaptcha",
    "cf-turnstile",
    "challenges.cloudflare.com",
    "cf-challenge",
    "attention required! | cloudflare",
)
_LOGIN_URL_PARTS = ("/login", "/signin", "/authwall", "/checkpoint")
# These strings show up on normal pages and must not, by themselves, be a block.
_IGNORED_BARE = {"blocked", "access denied", "enable javascript"}


def _title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    if not match:
        return ""
    return collapse_ws(html_to_text(match.group(1))).lower()


def classify_page(
    url: str = "",
    html: str = "",
    status_code: int | None = None,
    extra: dict | None = None,
) -> str | None:
    """Return captcha, login_wall, blocked, or None."""
    extra = extra or {}
    current = (url or "").lower()
    body = html or ""
    lowered = body.lower()
    title = _title(body)
    visible_len = len(collapse_ws(html_to_text(body)))

    if "/sorry/" in current or "google.com/sorry" in current:
        return "captcha"
    if any(bit in lowered or bit in current for bit in _CAPTCHA_BITS):
        return "captcha"
    if "unusual traffic" in lowered:
        return "captcha"
    if "our systems have detected" in lowered and "automated" in lowered:
        return "captcha"
    for phrase in extra.get("captcha_text") or []:
        if phrase and phrase.lower() in lowered:
            return "captcha"

    login_parts = list(_LOGIN_URL_PARTS)
    login_parts.extend(str(part).lower() for part in (extra.get("login_wall_url") or []))
    for part in login_parts:
        if part and part in current:
            return "login_wall"

    # Login-wall copy on a long results page (a header "Sign in" link) is not a wall.
    # A short interstitial or a title that is the phrase is.
    for phrase in extra.get("login_wall_text") or []:
        token = (phrase or "").strip().lower()
        if not token:
            continue
        if token == title or (token in title and len(title) < 80):
            return "login_wall"
        if token in lowered and visible_len < 800:
            return "login_wall"

    for phrase in extra.get("block_text") or []:
        token = (phrase or "").strip().lower()
        if not token or token in _IGNORED_BARE:
            continue
        if token in lowered:
            return "blocked"

    if status_code in {403, 429}:
        if any(bit in lowered for bit in ("captcha", "cloudflare", "verify you are", "attention required")):
            return "blocked"
        if status_code == 403 and visible_len < 1500 and "forbidden" in lowered:
            return "blocked"
    return None
