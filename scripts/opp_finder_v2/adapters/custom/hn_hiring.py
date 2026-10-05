"""HN 'Who is hiring?' via the public Algolia API.

The monthly thread is a story. Job posts are comments whose first line is
pipe-separated (company, role, location, employment, pay). That shape is not
a generic JSON job object, so it stays in this hook.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx

from opp_finder_v2.adapters.base import fixture_dir, load_json_file
from opp_finder_v2.artifacts import format_z
from opp_finder_v2.browser.session import USER_AGENT
from opp_finder_v2.models import Criteria, FetchResult, RawListing, RunOptions, SearchQuery, SiteConfig
from opp_finder_v2.parsing import (
    collapse_ws,
    html_to_text,
    normalize_employment,
    parse_salary_text,
)
from opp_finder_v2.politeness import Pacer, retry_delay

_STORY_URL = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?query=Ask%20HN:%20Who%20is%20hiring&tags=story&hitsPerPage=10"
)
_WHO = re.compile(r"who is hiring\?", re.I)
_META = re.compile(
    r"\b(full[- ]?time|part[- ]?time|contract|intern|freelance|remote|on-?site|hybrid|visa)\b",
    re.I,
)


def _get_json(url: str) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        last_error = None
        for attempt in range(3):
            try:
                response = client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= 2:
                    raise
                import time

                time.sleep(retry_delay(attempt, None))
                continue
            if response.status_code == 403:
                response.raise_for_status()
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= 2:
                    response.raise_for_status()
                import time

                time.sleep(retry_delay(attempt, response.headers.get("Retry-After")))
                continue
            response.raise_for_status()
            return response.json()
    if last_error:
        raise last_error
    return {}


def _load_live(site: SiteConfig, options: RunOptions) -> tuple[dict, dict]:
    pacer = Pacer(site, dry_run=False, max_per_site=options.max_per_site)
    if not pacer.acquire():
        return {}, {}
    stories = _get_json(_STORY_URL)
    story_id = _pick_story_id(stories)
    if not story_id or not pacer.acquire():
        return stories, {"hits": []}
    comments_url = (
        "https://hn.algolia.com/api/v1/search_by_date"
        f"?tags=comment,story_{story_id}&hitsPerPage=50"
    )
    return stories, _get_json(comments_url)


def _load_fixtures(site_id: str) -> tuple[dict, dict]:
    folder = fixture_dir(site_id)
    story = load_json_file(folder / "story.json")
    comments = load_json_file(folder / "comments.json")
    return story, comments


def _pick_story_id(payload: dict) -> str | None:
    for hit in payload.get("hits") or []:
        title = hit.get("title") or ""
        if _WHO.search(title):
            return str(hit.get("objectID") or "")
    return None


def _is_meta(part: str) -> bool:
    if re.search(r"https?://", part, re.I):
        return True
    if "$" in part or "€" in part or re.search(r"\b(usd|eur|gbp)\b", part, re.I):
        return True
    if _META.search(part):
        return True
    return False


def _parse_comment(text: str) -> dict | None:
    plain = html_to_text(text)
    lines = [collapse_ws(line) for line in plain.splitlines() if collapse_ws(line)]
    if not lines or "|" not in lines[0]:
        return None
    parts = [part.strip() for part in lines[0].split("|") if part.strip()]
    if len(parts) < 2:
        return None
    company = parts[0]
    if len(company) < 2 or _is_meta(company):
        return None
    role = ""
    location = ""
    employment = None
    for part in parts[1:]:
        found = normalize_employment(part)
        if found and employment is None:
            employment = found
        if re.search(r"\b(remote|on-?site|hybrid)\b", part, re.I) or (
            not _is_meta(part) and not role and len(part) < 80 and "," in part
        ):
            location = location or part
            continue
        if _is_meta(part):
            continue
        if not role and len(part) <= 140:
            role = part
    if not role and len(lines) > 1 and len(lines[1]) <= 140 and "|" not in lines[1]:
        role = lines[1]
    if not role:
        return None
    blob = " ".join(parts)
    remote = None
    if re.search(r"\bremote\b", blob, re.I):
        remote = True
    elif re.search(r"\bon-?site\b", blob, re.I):
        remote = False
    return {
        "title": role,
        "company": company,
        "location": location or None,
        "remote": remote,
        "employment_type": employment,
        "salary_text": lines[0],
        "snippet": plain,
    }


def comments_to_listings(payload: dict, site: SiteConfig, scraped_at: str) -> list[RawListing]:
    listings: list[RawListing] = []
    for hit in payload.get("hits") or []:
        parsed = _parse_comment(hit.get("comment_text") or "")
        if not parsed:
            continue
        object_id = str(hit.get("objectID") or "")
        url = f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""
        apply = None
        link = re.search(r"https?://[^\s<>\"]+", html_to_text(hit.get("comment_text") or ""))
        if link:
            apply = link.group(0).rstrip(").,")
        salary = parse_salary_text(parsed["salary_text"])
        listing = RawListing(
            title=parsed["title"],
            company=parsed["company"],
            location=parsed["location"],
            remote=parsed["remote"],
            url=url,
            apply_url=apply,
            posted_date=hit.get("created_at"),
            snippet=parsed["snippet"],
            salary_text=parsed["salary_text"] if salary else None,
            salary_min=salary["rate_min"] if salary else None,  # type: ignore[arg-type]
            salary_max=salary["rate_max"] if salary else None,  # type: ignore[arg-type]
            rate_unit=salary["rate_unit"] if salary else None,  # type: ignore[arg-type]
            currency=salary["currency"] if salary else None,  # type: ignore[arg-type]
            employment_type=parsed["employment_type"],
            source_site=site.id,
            scraped_at=scraped_at,
        )
        if apply:
            listing.apply_url = urljoin(site.base_url, apply)
        listings.append(listing)
    return listings


def fetch(site, query: SearchQuery, criteria: Criteria, options: RunOptions, browser=None) -> FetchResult:
    del query, criteria, browser
    scraped_at = format_z()
    try:
        if options.dry_run:
            _stories, comments = _load_fixtures(site.id)
        else:
            _stories, comments = _load_live(site, options)
        listings = comments_to_listings(comments, site, scraped_at)
    except (OSError, httpx.HTTPError, KeyError, ValueError) as exc:
        return FetchResult(status="error", error=str(exc))
    from opp_finder_v2.politeness import Pacer as _Pacer

    cap = _Pacer(site, dry_run=options.dry_run, max_per_site=options.max_per_site).max_results
    return FetchResult(listings=listings[:cap], pages=1 if listings or comments else 0, status="ok")
