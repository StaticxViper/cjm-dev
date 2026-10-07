"""Generic JSON API adapter. Field mapping is dotted paths from sites.json."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from opp_finder_v2.adapters.base import (
    dig,
    json_fixtures,
    offset_number,
    page_number,
    render_template,
    template_values,
)
from opp_finder_v2.artifacts import format_z
from opp_finder_v2.browser.detection import classify_page
from opp_finder_v2.browser.session import USER_AGENT
from opp_finder_v2.models import Criteria, FetchResult, RawListing, RunOptions, SearchQuery, SiteConfig
from opp_finder_v2.politeness import Pacer, retry_delay

logger = logging.getLogger("opp-finder-v2")


def _items_from_payload(payload: Any, site: SiteConfig) -> list[Any]:
    path = (site.api or {}).get("items_path")
    found = dig(payload, path if path is not None else "")
    if isinstance(found, dict) and path in (None, ""):
        return []
    if not isinstance(found, list):
        return []
    if (site.api or {}).get("skip_first_item") and found:
        return found[1:]
    return found


def _request_pages(site: SiteConfig, query: SearchQuery, criteria: Criteria, options: RunOptions):
    """Yield (payload, final_url, status_code) for each page."""
    if options.dry_run:
        for payload in json_fixtures(site.id):
            yield payload, site.search_url, 200
        return

    pagination = site.pagination or {}
    kind = pagination.get("type") or "none"
    max_pages = 1 if kind == "none" else int(pagination.get("max_pages") or 1)
    pacer = Pacer(site, dry_run=False, max_per_site=options.max_per_site)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    extra_headers = (site.api or {}).get("headers") or {}
    if isinstance(extra_headers, dict):
        headers.update({str(key): str(value) for key, value in extra_headers.items()})
    method = ((site.api or {}).get("method") or "GET").upper()
    companies = site.companies if site.companies is not None else [None]
    if site.companies is not None and not site.companies:
        return

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for company in companies:
            for index in range(max_pages):
                if not pacer.acquire():
                    return
                values = template_values(
                    query,
                    criteria,
                    site,
                    page=page_number(pagination, index),
                    offset=offset_number(pagination, index),
                )
                if company:
                    values["company"] = quote(company)
                url = render_template(site.search_url, values)
                payload, status, final_url = _get_json(client, method, url, headers)
                yield payload, final_url or url, status
                if status != 200 or payload is None:
                    return
                if kind == "none":
                    break
                if not _items_from_payload(payload, site):
                    break


def _get_json(client: httpx.Client, method: str, url: str, headers: dict[str, str]):
    last_status = 0
    last_text = ""
    response = None
    for attempt in range(3):
        try:
            response = client.request(method, url, headers=headers)
        except httpx.HTTPError as exc:
            logger.info("Request error %s (%s) attempt %s", url, exc, attempt + 1)
            if attempt >= 2:
                raise
            _sleep_retry(attempt, None)
            continue
        last_status = response.status_code
        last_text = response.text or ""
        if response.status_code == 403:
            return {"_body": last_text}, last_status, str(response.url)
        if response.status_code == 429 or response.status_code >= 500:
            if attempt >= 2:
                break
            _sleep_retry(attempt, response)
            continue
        break
    if response is None:
        return None, last_status, url
    if response.status_code != 200:
        return {"_body": last_text}, response.status_code, str(response.url)
    try:
        return response.json(), response.status_code, str(response.url)
    except ValueError:
        return {"_body": last_text}, response.status_code, str(response.url)


def _sleep_retry(attempt: int, response: httpx.Response | None) -> None:
    import time

    header = None
    if response is not None:
        header = response.headers.get("Retry-After")
    time.sleep(retry_delay(attempt, header))


class ApiAdapter:
    def fetch(
        self,
        site: SiteConfig,
        query: SearchQuery,
        criteria: Criteria,
        options: RunOptions,
        browser=None,
    ) -> FetchResult:
        del browser
        pacer = Pacer(site, dry_run=options.dry_run, max_per_site=options.max_per_site)
        listings: list[RawListing] = []
        seen: set[str] = set()
        pages = 0
        fields = ((site.results or {}).get("fields") or {})
        scraped_at = format_z()
        try:
            for payload, url, status in _request_pages(site, query, criteria, options):
                pages += 1
                body = ""
                if isinstance(payload, dict) and "_body" in payload and len(payload) == 1:
                    body = str(payload.get("_body") or "")
                    kind = classify_page(url, body, status_code=status, extra=site.detection)
                    if kind:
                        return FetchResult(
                            listings=listings[: pacer.max_results],
                            pages=pages,
                            status=f"skipped_{kind}",
                            error=f"HTTP {status}",
                        )
                    return FetchResult(
                        listings=listings[: pacer.max_results],
                        pages=pages,
                        status="error",
                        error=f"HTTP {status}",
                    )
                if status and status != 200:
                    kind = classify_page(url, "", status_code=status, extra=site.detection)
                    status_name = f"skipped_{kind}" if kind else "error"
                    return FetchResult(
                        listings=listings[: pacer.max_results],
                        pages=pages,
                        status=status_name,
                        error=f"HTTP {status}",
                    )
                items = _items_from_payload(payload, site)
                added = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    mapped = {}
                    for dest, path in fields.items():
                        if isinstance(path, str):
                            mapped[dest] = dig(item, path)
                    raw = RawListing(source_site=site.id, scraped_at=scraped_at)
                    # Filled by the pipeline via mapped_to_raw. Store mapped on the listing
                    # by converting here to keep the adapter return type stable.
                    from opp_finder_v2.listings import mapped_to_raw

                    raw = mapped_to_raw(mapped, site, scraped_at)
                    key = (raw.url or "") + "|" + (raw.title or "")
                    if not raw.title or key in seen:
                        continue
                    seen.add(key)
                    listings.append(raw)
                    added += 1
                    if len(listings) >= pacer.max_results:
                        return FetchResult(listings=listings, pages=pages, status="ok")
                if added == 0:
                    break
        except FileNotFoundError as exc:
            return FetchResult(status="error", error=str(exc), pages=pages)
        except httpx.HTTPError as exc:
            return FetchResult(
                listings=listings[: pacer.max_results],
                pages=pages,
                status="error",
                error=str(exc),
            )
        return FetchResult(listings=listings[: pacer.max_results], pages=pages, status="ok")
