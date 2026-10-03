"""Craigslist multi-metro public search scraper (best-effort)."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from scrapers import SearchContext
from utils.jobs import RawJob, clean_text, extract_job_fields_from_html
from utils.normalization import normalize_url

logger = logging.getLogger("opp-finder")

# Map configured region names -> Craigslist site bases.
CL_SITES_BY_REGION = {
    "south_jersey": "https://southjersey.craigslist.org",
    "philadelphia_metro": "https://philadelphia.craigslist.org",
    "delaware": "https://delaware.craigslist.org",
    "north_jersey": "https://newjersey.craigslist.org",
}

DEFAULT_CL_SITES = [
    "https://southjersey.craigslist.org",
    "https://philadelphia.craigslist.org",
    "https://delaware.craigslist.org",
]


class CraigslistScraper:
    name = "craigslist"

    def _sites(self, ctx: SearchContext) -> list[str]:
        names = list(ctx.region_names or [])
        if not names:
            # Derive from enabled config regions.
            regions = (ctx.config.get("locations") or []) if isinstance(ctx.config, dict) else []
            names = [str(r.get("name") or "") for r in regions if isinstance(r, dict) and r.get("enabled", True)]
        sites: list[str] = []
        seen: set[str] = set()
        for name in names:
            base = CL_SITES_BY_REGION.get(name.lower())
            if base and base not in seen:
                seen.add(base)
                sites.append(base)
        if not sites:
            sites = list(DEFAULT_CL_SITES)
        # When prioritizing remote, still search local CL boards (remote rarely lives on CL).
        return sites

    def search(self, ctx: SearchContext) -> list[RawJob]:
        browser = ctx.browser
        if browser is None or browser.is_blocked(self.name):
            return []
        if ctx.remote_only:
            # Craigslist is mostly local; skip in remote-only mode.
            logger.info("[SEARCH] Craigslist — skipped in remote-only mode")
            return []

        jobs: list[RawJob] = []
        keywords = ctx.keywords[: max(3, min(8, int(ctx.max_total_jobs)))]
        for base in self._sites(ctx):
            if browser.is_blocked(self.name):
                break
            if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                break
            for keyword in keywords:
                if browser.is_blocked(self.name):
                    break
                if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                    break
                query = f"{base}/search/jjj?query={quote_plus(keyword)}"
                logger.info('[SEARCH] Craigslist — %s "%s"', base.replace("https://", ""), keyword)
                final_url, html = browser.goto(query, source=self.name)
                if not html:
                    continue
                cards = self._parse_cards(html, final_url or query)
                logger.info("[SEARCH] Found %d results", len(cards))
                for card in cards[: ctx.max_results_per_keyword]:
                    if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                        break
                    job = self._hydrate(card, browser)
                    if job:
                        jobs.append(job)
        return jobs

    def _parse_cards(self, html: str, base_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html or "", "html.parser")
        cards: list[dict[str, str]] = []
        seen: set[str] = set()
        for node in soup.select("li.cl-static-search-result a, li.result-row a.hdrlnk, a.titlestring"):
            href = node.get("href") or ""
            if not href:
                continue
            url = urljoin(base_url, href)
            title = clean_text(node.get_text())
            if len(title) < 8 or "craigslist" in title.lower():
                continue
            norm = normalize_url(url)
            if not title or norm in seen:
                continue
            seen.add(norm)
            parent = node.find_parent("li")
            location = ""
            if parent:
                loc_el = parent.select_one(".location, .meta, .nearby")
                if loc_el:
                    candidate = clean_text(loc_el.get_text())
                    if 2 < len(candidate) < 80:
                        location = candidate
            if not location:
                loc_match = re.search(r"\(([^)]+)\)\s*$", title)
                if loc_match:
                    location = clean_text(loc_match.group(1))
                    title = clean_text(re.sub(r"\s*\([^)]+\)\s*$", "", title))
            if not location:
                if "philadelphia" in base_url:
                    location = "Philadelphia, PA"
                elif "delaware" in base_url:
                    location = "Delaware"
                elif "newjersey" in base_url:
                    location = "North Jersey, NJ"
                else:
                    location = "South Jersey, NJ"
            cards.append({"title": title, "url": url, "location": location})
        return cards

    def _hydrate(self, card: dict[str, str], browser) -> RawJob | None:
        url = card["url"]
        final_url, html = browser.goto(url, source=self.name)
        detail = extract_job_fields_from_html(html, final_url or url) if html else {}
        job = RawJob(
            job_title=detail.get("job_title") or card.get("title") or "",
            company_name=detail.get("company_name") or "",
            job_description=detail.get("job_description") or "",
            responsibilities=detail.get("responsibilities") or "",
            requirements=detail.get("requirements") or "",
            location=detail.get("location") or card.get("location") or "",
            salary=detail.get("salary") or "",
            employment_type=detail.get("employment_type") or "",
            source=self.name,
            source_url=normalize_url(final_url or url) or url,
            application_url=final_url or url,
            sources_found=[self.name],
        )
        job.ensure_defaults()
        return job if job.job_title else None
