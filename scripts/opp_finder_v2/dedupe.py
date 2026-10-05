"""Cross-site identity, URL canonicalization, and richer-record merges.

opp_id hashes normalized title and company only. The same role on two boards
keeps one record even when the URLs and location strings differ. An empty
company never merges on title alone.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from opp_finder_v2.models import Criteria, Opportunity
from opp_finder_v2.relevance import score_opportunity

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTI_SPACE = re.compile(r"\s+")
_TITLE_NOISE = re.compile(
    r"(?:"
    r"\s*[\(\[]\s*(?:contract|remote)\s*[\)\]]"
    r"|\s+-\s+(?:remote|contract)"
    r")\s*$",
    re.I,
)

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

_TRACKING_EXACT = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "refid",
    "trackingid",
    "trk",
    "src",
    "source",
}
# Params that identify the posting stay even when they look like campaign tags.
_JOB_ID_PARAMS = {
    "jk",
    "jobid",
    "job_id",
    "gh_jid",
    "postingid",
    "currentjobid",
    "lever-id",
}


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = _NON_ALNUM.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


def normalize_company(name: str | None) -> str:
    text = normalize_text(name)
    tokens = text.split()
    while tokens and tokens[-1] in COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def strip_title_noise(title: str | None) -> str:
    text = (title or "").strip()
    previous = None
    while text and text != previous:
        previous = text
        text = _TITLE_NOISE.sub("", text).strip()
    return text


def normalize_title(title: str | None) -> str:
    return normalize_text(strip_title_noise(title))


def canonical_url(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or "/"

    if "craigslist.org" in host:
        post_id = ""
        query = parse_qs(parsed.query, keep_blank_values=False)
        if query.get("postingID"):
            post_id = query["postingID"][0]
        if not post_id:
            match = re.search(r"/(\d+)\.html$", path)
            if match:
                post_id = match.group(1)
        if post_id:
            return f"https://craigslist.org/post/{post_id}"

    query = parse_qs(parsed.query, keep_blank_values=False)
    kept: list[tuple[str, str]] = []
    for key in sorted(query):
        lowered = key.lower()
        drop = lowered.startswith("utm_") or lowered in _TRACKING_EXACT
        if drop and lowered not in _JOB_ID_PARAMS:
            continue
        for value in query[key]:
            kept.append((key, value))
    clean = parsed._replace(
        scheme=(parsed.scheme or "https").lower(),
        netloc=host,
        path=path.rstrip("/") or "/",
        params="",
        query=urlencode(kept, doseq=True),
        fragment="",
    )
    return urlunparse(clean)


def opp_id_for(title: str | None, company: str | None) -> str:
    material = normalize_title(title) + "|" + normalize_company(company)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def assign_identity(opp: Opportunity) -> Opportunity:
    opp.opp_id = opp_id_for(opp.title, opp.company)
    if opp.url:
        opp.url = canonical_url(opp.url)
    if opp.apply_url:
        opp.apply_url = canonical_url(opp.apply_url)
    cleaned_sources = []
    for source in opp.sources:
        item = dict(source)
        if item.get("url"):
            item["url"] = canonical_url(item["url"])
        cleaned_sources.append(item)
    opp.sources = cleaned_sources
    return opp


def _longer(current: str | None, incoming: str | None) -> str | None:
    if not incoming:
        return current
    if not current:
        return incoming
    return incoming if len(incoming) > len(current) else current


def _known(current, incoming):
    if current is None or current == "":
        return incoming
    if incoming is None or incoming == "":
        return current
    return current


def _union_sources(left: list[dict], right: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for source in list(left) + list(right):
        key = (source.get("site") or "", source.get("url") or "")
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(source))
    return merged


def _union_strings(left: list[str], right: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in list(left) + list(right):
        text = (value or "").strip()
        token = text.lower()
        if not text or token in seen:
            continue
        seen.add(token)
        out.append(text)
    return sorted(out, key=str.lower)


def merge_opportunities(
    existing: Opportunity,
    incoming: Opportunity,
    criteria: Criteria,
    scraped_at: datetime,
) -> Opportunity:
    url = existing.url or incoming.url
    source_site = existing.source_site
    if incoming.url and (not existing.url or len(incoming.url) > len(existing.url)):
        # Prefer a non-empty URL; when both exist, keep the existing listing URL
        # unless the existing one is empty. Length is only a tie-break for empty.
        pass
    if not existing.url and incoming.url:
        url = incoming.url
        source_site = incoming.source_site
    elif existing.url:
        url = existing.url
        source_site = existing.source_site

    rate_min = existing.rate_min if existing.rate_min is not None else incoming.rate_min
    rate_max = existing.rate_max if existing.rate_max is not None else incoming.rate_max
    rate_unit = existing.rate_unit or incoming.rate_unit
    currency = existing.currency or incoming.currency
    if existing.rate_max is None and incoming.rate_max is not None:
        rate_min, rate_max = incoming.rate_min, incoming.rate_max
        rate_unit = incoming.rate_unit or rate_unit
        currency = incoming.currency or currency

    merged = Opportunity(
        opp_id=existing.opp_id,
        title=_longer(existing.title, incoming.title) or existing.title,
        company=_known(existing.company, incoming.company),
        location=_longer(existing.location, incoming.location),
        remote=existing.remote if existing.remote is not None else incoming.remote,
        url=url,
        apply_url=_known(existing.apply_url, incoming.apply_url),
        source_site=source_site,
        sources=_union_sources(existing.sources, incoming.sources),
        posted_date=_known(existing.posted_date, incoming.posted_date),
        snippet=_longer(existing.snippet, incoming.snippet),
        salary_text=_longer(existing.salary_text, incoming.salary_text),
        rate_min=rate_min,
        rate_max=rate_max,
        rate_unit=rate_unit,
        currency=currency,
        employment_type=_known(existing.employment_type, incoming.employment_type),
        tags=_union_strings(existing.tags, incoming.tags),
        matched_keywords=_union_strings(existing.matched_keywords, incoming.matched_keywords),
        relevance_score=0,
        score_breakdown={},
        scraped_at=existing.scraped_at or incoming.scraped_at,
    )
    assign_identity(merged)
    recomputed, breakdown, matched = score_opportunity(merged, criteria, scraped_at)
    # Keep the record scoreable. Hard filters already ran on each side.
    candidates = [
        (recomputed, breakdown, matched),
        (existing.relevance_score, existing.score_breakdown, existing.matched_keywords),
        (incoming.relevance_score, incoming.score_breakdown, incoming.matched_keywords),
    ]
    best_score, best_breakdown, best_matched = max(candidates, key=lambda item: item[0])
    merged.relevance_score = best_score
    merged.score_breakdown = dict(best_breakdown)
    merged.matched_keywords = _union_strings(merged.matched_keywords, best_matched)
    # If the winning score is the recomputed one, its breakdown already matches.
    # Otherwise keep the breakdown that produced the higher score.
    if best_score == recomputed and best_breakdown is breakdown:
        merged.score_breakdown = breakdown
        merged.matched_keywords = _union_strings(matched, merged.matched_keywords)
    return merged


def dedupe_opportunities(
    opportunities: list[Opportunity],
    criteria: Criteria,
    scraped_at: datetime,
) -> tuple[list[Opportunity], int]:
    by_url: dict[str, int] = {}
    by_id: dict[str, int] = {}
    merged_rows: list[Opportunity] = []
    merge_count = 0

    for opp in opportunities:
        assign_identity(opp)
        url_key = canonical_url(opp.url)
        company_key = normalize_company(opp.company)
        id_key = opp.opp_id if company_key else ""
        index = None
        if url_key and url_key in by_url:
            index = by_url[url_key]
        elif id_key and id_key in by_id:
            index = by_id[id_key]
        if index is None:
            merged_rows.append(opp)
            index = len(merged_rows) - 1
        else:
            merge_count += 1
            merged_rows[index] = merge_opportunities(
                merged_rows[index], opp, criteria, scraped_at
            )
        if url_key:
            by_url[url_key] = index
        if id_key:
            by_id[id_key] = index
        # A merge can add another URL. Index that too.
        extra = canonical_url(merged_rows[index].url)
        if extra:
            by_url[extra] = index
    return merged_rows, merge_count
