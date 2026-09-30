"""Follow Google-discovered company career pages for additional listings."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scrapers import SearchContext
from utils.jobs import RawJob, clean_text, guess_company_website, parse_google_results
from utils.normalization import normalize_url

logger = logging.getLogger("opp-finder")


class CompanySitesScraper:
    name = "company_sites"

    def search(self, ctx: SearchContext) -> list[RawJob]:
        browser = ctx.browser
        if browser is None or browser.is_blocked("google"):
            return []

        jobs: list[RawJob] = []
        # Limited discovery queries for career pages in-region
        sample_keywords = ctx.keywords[: min(5, len(ctx.keywords))]
        for keyword in sample_keywords:
            if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                break
            query = f'CAREERS "{keyword}" "South Jersey" OR "Camden County NJ"'
            logger.info("[SEARCH] Company sites — %s", query)
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
                if any(x in host for x in ("indeed.com", "ziprecruiter.com", "linkedin.com", "google.com")):
                    continue
                page_jobs = self._extract_from_career_page(browser, url, keyword)
                jobs.extend(page_jobs)
        return jobs

    def _extract_from_career_page(self, browser, url: str, keyword: str) -> list[RawJob]:
        final_url, html = browser.goto(url, source=self.name)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        company = guess_company_website(final_url or url)
        host_name = urlparse(final_url or url).netloc.replace("www.", "").split(".")[0].title()
        found: list[RawJob] = []
        for link in soup.find_all("a", href=True):
            text = clean_text(link.get_text())
            href = urljoin(final_url or url, link["href"])
            if not text or len(text) < 6:
                continue
            blob = f"{text} {href}".lower()
            if keyword.lower() not in blob and not re.search(r"job|career|apply|opening", blob):
                continue
            if not re.search(r"job|career|apply|opening|position", blob):
                continue
            job = RawJob(
                job_title=text[:160],
                company_name=host_name,
                job_description=text,
                location="South Jersey, NJ",
                source=self.name,
                source_url=normalize_url(href) or href,
                application_url=href,
                company_website=company,
                sources_found=[self.name],
            )
            job.ensure_defaults()
            found.append(job)
            if len(found) >= 5:
                break
        return found
