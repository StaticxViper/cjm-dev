"""Discover local staffing-agency job pages via Google, then extract listings."""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scrapers import SearchContext
from utils.jobs import RawJob, clean_text, parse_google_results
from utils.normalization import normalize_url

logger = logging.getLogger("opp-finder")


class StaffingScraper:
    name = "staffing"

    def search(self, ctx: SearchContext) -> list[RawJob]:
        browser = ctx.browser
        if browser is None or browser.is_blocked("google"):
            return []

        jobs: list[RawJob] = []
        queries = [
            'staffing agency jobs "South Jersey" OR "Camden County NJ"',
            'temporary staffing "data entry" "New Jersey"',
            'staffing "administrative assistant" "South Jersey" hiring',
        ]
        for query in queries:
            if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                break
            logger.info("[SEARCH] Staffing — %s", query)
            _url, html = browser.google_search(query, num=8)
            if browser.is_blocked("google"):
                break
            results = parse_google_results(html)
            logger.info("[SEARCH] Found %d results", len(results))
            for item in results:
                if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                    break
                url = item.get("url") or ""
                host = urlparse(url).netloc.lower()
                if "google.com" in host:
                    continue
                page_jobs = self._extract(browser, url, item)
                jobs.extend(page_jobs)
        return jobs

    def _extract(self, browser, url: str, item: dict[str, str]) -> list[RawJob]:
        final_url, html = browser.goto(url, source=self.name)
        if not html:
            # Fall back to SERP snippet as a lightweight lead
            title = clean_text(item.get("title"))
            if not title:
                return []
            job = RawJob(
                job_title=title,
                company_name="",
                job_description=clean_text(item.get("snippet")),
                location="South Jersey, NJ",
                source=self.name,
                source_url=normalize_url(url) or url,
                application_url=url,
                sources_found=[self.name],
            )
            job.ensure_defaults()
            return [job]

        soup = BeautifulSoup(html, "html.parser")
        host_name = urlparse(final_url or url).netloc.replace("www.", "").split(".")[0].title()
        found: list[RawJob] = []
        for link in soup.find_all("a", href=True):
            text = clean_text(link.get_text())
            href = urljoin(final_url or url, link["href"])
            blob = f"{text} {href}".lower()
            if len(text) < 8:
                continue
            if not any(tok in blob for tok in ("job", "career", "apply", "opening", "position")):
                continue
            job = RawJob(
                job_title=text[:160],
                company_name=host_name,
                job_description=text,
                location="South Jersey, NJ",
                source=self.name,
                source_url=normalize_url(href) or href,
                application_url=href,
                sources_found=[self.name],
            )
            job.ensure_defaults()
            found.append(job)
            if len(found) >= 5:
                break
        return found
