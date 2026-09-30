"""Normalization helpers for deduplication and matching."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlparse, urlunparse

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTI_SPACE = re.compile(r"\s+")

COMPANY_SUFFIXES = (
    "llc",
    "l.l.c",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "pllc",
    "lp",
    "llp",
    "pc",
    "p.c",
)


def normalize_text(value: str | None) -> str:
    """Lowercase, strip punctuation-ish noise, collapse whitespace."""
    text = (value or "").strip().lower()
    text = _NON_ALNUM.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


def normalize_company(name: str | None) -> str:
    """Normalize a company name and drop common legal suffixes."""
    text = normalize_text(name)
    tokens = text.split()
    while tokens and tokens[-1] in COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_title(title: str | None) -> str:
    return normalize_text(title)


def normalize_location(location: str | None) -> str:
    return normalize_text(location)


def normalize_url(url: str | None) -> str:
    """Strip fragments, tracking params, and trailing slashes for comparison."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path = parsed.path or "/"

    # Craigslist serves the same posting under multiple view-hash URLs; collapse by post id.
    if "craigslist.org" in host:
        post_id = ""
        qs = parse_qs(parsed.query, keep_blank_values=False)
        if qs.get("postingID"):
            post_id = qs["postingID"][0]
        if not post_id:
            match = re.search(r"/(\d+)\.html$", path)
            if match:
                post_id = match.group(1)
        if not post_id:
            # Newer /view/d/.../<hash> pages often include numeric post id only in body;
            # keep path stem as a weaker key.
            match = re.search(r"/view/d/[^/]+/([^/?#]+)", path)
            if match:
                post_id = match.group(1)
        if post_id:
            return f"https://craigslist.org/post/{post_id}"

    query = parse_qs(parsed.query, keep_blank_values=False)
    drop_keys = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    }
    kept = []
    for key, values in sorted(query.items()):
        if key.lower() in drop_keys:
            continue
        for value in values:
            kept.append(f"{key}={value}")
    clean = parsed._replace(
        scheme=(parsed.scheme or "https").lower(),
        netloc=host,
        path=path.rstrip("/") or "/",
        params="",
        query="&".join(kept),
        fragment="",
    )
    return urlunparse(clean)


def job_fingerprint(
    company: str | None,
    title: str | None,
    location: str | None,
    url: str | None,
) -> str:
    """Stable id for dedupe across sources."""
    parts = "|".join(
        [
            normalize_company(company),
            normalize_title(title),
            normalize_location(location),
            normalize_url(url),
        ]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:20]


def join_list(values: list[str] | None, sep: str = " | ") -> str:
    if not values:
        return ""
    return sep.join(str(v).strip() for v in values if str(v).strip())
