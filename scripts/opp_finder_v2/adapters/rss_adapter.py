"""RSS and Atom adapter. Item fields are tag names from sites.json."""

from __future__ import annotations

import logging
from xml.etree import ElementTree as ET

import httpx

from opp_finder_v2.adapters.base import rss_fixture, render_template, template_values
from opp_finder_v2.artifacts import format_z
from opp_finder_v2.browser.session import USER_AGENT
from opp_finder_v2.listings import mapped_to_raw
from opp_finder_v2.models import Criteria, FetchResult, RunOptions, SearchQuery, SiteConfig
from opp_finder_v2.politeness import Pacer, retry_delay

logger = logging.getLogger("opp-finder-v2")


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _child_text(item: ET.Element, name: str) -> str | None:
    for child in list(item):
        if _local(child.tag) != name:
            continue
        text = "".join(child.itertext()).strip()
        if text:
            return text
        href = child.get("href")
        if href:
            return href
    return None


def _entries(root: ET.Element) -> list[ET.Element]:
    items = [node for node in root.iter() if _local(node.tag) == "item"]
    if items:
        return items
    return [node for node in root.iter() if _local(node.tag) == "entry"]


def parse_feed(xml_text: str, site: SiteConfig, scraped_at: str) -> list:
    root = ET.fromstring(xml_text)
    fields = (site.results or {}).get("fields") or {}
    listings = []
    seen: set[str] = set()
    for entry in _entries(root):
        mapped = {}
        for dest, tag in fields.items():
            if isinstance(tag, str):
                mapped[dest] = _child_text(entry, tag)
        if not mapped.get("snippet"):
            mapped["snippet"] = _child_text(entry, "description") or _child_text(entry, "summary")
        raw = mapped_to_raw(mapped, site, scraped_at)
        if not raw.title:
            continue
        key = (raw.url or "") + "|" + raw.title
        if key in seen:
            continue
        seen.add(key)
        listings.append(raw)
    return listings


def _download(url: str) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"}
    last_error: Exception | None = None
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
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
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= 2:
                    response.raise_for_status()
                import time

                time.sleep(retry_delay(attempt, response.headers.get("Retry-After")))
                continue
            response.raise_for_status()
            return response.text
    if last_error:
        raise last_error
    return ""


class RssAdapter:
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
        scraped_at = format_z()
        try:
            if options.dry_run:
                xml_text = rss_fixture(site.id)
            else:
                if not pacer.acquire():
                    return FetchResult(status="ok", pages=0)
                values = template_values(query, criteria, site, page=1, offset=0)
                url = render_template(site.search_url, values)
                xml_text = _download(url)
            listings = parse_feed(xml_text, site, scraped_at)
        except (ET.ParseError, OSError, httpx.HTTPError) as exc:
            logger.info("RSS fetch failed for %s: %s", site.id, exc)
            return FetchResult(status="error", error=str(exc), pages=0)
        return FetchResult(listings=listings[: pacer.max_results], pages=1, status="ok")
