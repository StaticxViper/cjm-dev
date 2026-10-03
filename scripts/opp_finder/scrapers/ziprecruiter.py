"""ZipRecruiter public search scraper (best-effort; skips on block)."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from scrapers import SearchContext
from utils.jobs import RawJob, clean_text, extract_job_fields_from_html
from utils.normalization import normalize_url

logger = logging.getLogger("opp-finder")


class ZipRecruiterScraper:
    name = "ziprecruiter"

    def search(self, ctx: SearchContext) -> list[RawJob]:
        browser = ctx.browser
        if browser is None or browser.is_blocked(self.name):
            return []

        jobs: list[RawJob] = []
        locations = list(ctx.location_phrases[:6]) if ctx.location_phrases else []
        if ctx.remote_only:
            locations = [p for p in locations if "remote" in p.lower() or "work from home" in p.lower()]
            if not locations:
                locations = ["Remote"]
        elif not locations:
            locations = ["Remote", "South Jersey, NJ", "Philadelphia, PA"]
        keywords = ctx.keywords[: max(3, min(10, int(ctx.max_total_jobs)))]

        for keyword in keywords:
            if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                break
            for location in locations:
                if browser.is_blocked(self.name):
                    return jobs
                if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                    break
                query = (
                    "https://www.ziprecruiter.com/jobs-search?"
                    f"search={quote_plus(keyword)}&location={quote_plus(location)}"
                )
                logger.info('[SEARCH] ZipRecruiter — "%s" %s', keyword, location)
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
        for node in soup.select("a[href*='/jobs/'], article a, h2 a"):
            href = node.get("href") or ""
            if "/jobs/" not in href and "/job/" not in href:
                continue
            url = urljoin(base_url, href)
            title = clean_text(node.get_text())
            norm = normalize_url(url)
            if not title or norm in seen:
                continue
            seen.add(norm)
            parent = node.find_parent("article") or node.find_parent("div")
            company = ""
            location = ""
            if parent:
                company_el = parent.select_one("[class*='company'], a[href*='/co/']")
                loc_el = parent.select_one("[class*='location']")
                company = clean_text(company_el.get_text()) if company_el else ""
                location = clean_text(loc_el.get_text()) if loc_el else ""
            cards.append({"title": title, "url": url, "company": company, "location": location})
        return cards

    def _hydrate(self, card: dict[str, str], browser) -> RawJob | None:
        url = card["url"]
        final_url, html = browser.goto(url, source=self.name)
        detail = extract_job_fields_from_html(html, final_url or url) if html else {}
        job = RawJob(
            job_title=detail.get("job_title") or card.get("title") or "",
            company_name=detail.get("company_name") or card.get("company") or "",
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
