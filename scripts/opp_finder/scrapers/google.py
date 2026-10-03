"""Google discovery scraper — primary job URL discovery layer."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from scrapers import SearchContext
from utils.browser import BrowserSession
from utils.jobs import (
    RawJob,
    clean_text,
    extract_job_fields_from_html,
    guess_company_website,
    parse_google_results,
)
from utils.normalization import normalize_url

logger = logging.getLogger("opp-finder")

JOB_HOST_HINTS = (
    "indeed.com",
    "ziprecruiter.com",
    "craigslist.org",
    "linkedin.com/jobs",
    "glassdoor.com",
    "simplyhired.com",
    "monster.com",
    "careerbuilder.com",
    "jobs.",
    "/careers",
    "/jobs",
    "/job/",
    "hiring",
)

COMPANY_FROM_TITLE = re.compile(
    r"^(?P<title>.+?)\s+(?:at|@|-|–|—)\s+(?P<company>.+)$",
    re.I,
)


class GoogleScraper:
    name = "google"

    def build_queries(self, ctx: SearchContext) -> list[str]:
        templates = (ctx.config.get("search") or {}).get("query_templates") or [
            '"{keyword}" "{location}" hiring',
            '"{keyword}" "{location}" job',
        ]
        # location_phrases are already ordered (remote-first when prioritize_remote).
        phrases = list(ctx.location_phrases)
        if not phrases:
            phrases = ["Remote United States", "South Jersey"]

        # Query budget scales with max_total_jobs so --limit stays practical.
        max_queries = max(6, min(80, int(ctx.max_total_jobs) * 2))
        ordered_templates = list(templates)
        queries: list[str] = []
        seen: set[str] = set()
        # Round-robin keywords × locations for coverage instead of exploding the cartesian product.
        for template in ordered_templates:
            for location in phrases:
                for keyword in ctx.keywords:
                    q = template.format(keyword=keyword, location=location)
                    key = q.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    queries.append(q)
                    if len(queries) >= max_queries:
                        return queries
        return queries

    def search(self, ctx: SearchContext) -> list[RawJob]:
        browser = ctx.browser
        if browser is None:
            return []
        if browser.is_blocked(self.name):
            return []

        jobs: list[RawJob] = []
        queries = self.build_queries(ctx)
        per_kw = ctx.max_results_per_keyword
        logger.info("[SEARCH] Google — %d queries planned (budgeted)", len(queries))
        for query in queries:
            if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                break
            logger.info("[SEARCH] Google — %s", query)
            _url, html = browser.google_search(query, num=min(10, per_kw))
            if browser.is_blocked(self.name):
                break
            results = parse_google_results(html)
            logger.info("[SEARCH] Found %d results", len(results))
            for item in results[:per_kw]:
                if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                    break
                if not self._looks_like_job(item):
                    continue
                job = self._result_to_job(item, browser)
                if job:
                    jobs.append(job)
        return jobs

    def _looks_like_job(self, item: dict[str, str]) -> bool:
        blob = f"{item.get('title', '')} {item.get('url', '')} {item.get('snippet', '')}".lower()
        if any(h in blob for h in JOB_HOST_HINTS):
            return True
        return any(
            token in blob
            for token in ("hiring", "job", "career", "apply", "opening", "position")
        )

    def _result_to_job(self, item: dict[str, str], browser: BrowserSession) -> RawJob | None:
        url = item.get("url") or ""
        title = clean_text(item.get("title"))
        snippet = clean_text(item.get("snippet"))
        company = ""
        job_title = title
        match = COMPANY_FROM_TITLE.match(title)
        if match:
            job_title = clean_text(match.group("title"))
            company = clean_text(match.group("company"))
            company = re.sub(r"\s*[-|].*$", "", company).strip()

        host = urlparse(url).netloc.lower()
        source = "google"
        if "indeed.com" in host:
            source = "indeed"
        elif "ziprecruiter.com" in host:
            source = "ziprecruiter"
        elif "craigslist.org" in host:
            source = "craigslist"

        detail: dict[str, str] = {}
        if not browser.is_blocked(source):
            final_url, html = browser.goto(url, source=source)
            if html:
                detail = extract_job_fields_from_html(html, final_url or url)
                url = final_url or url

        job = RawJob(
            job_title=detail.get("job_title") or job_title,
            company_name=detail.get("company_name") or company,
            job_description=detail.get("job_description") or snippet,
            responsibilities=detail.get("responsibilities") or "",
            requirements=detail.get("requirements") or "",
            location=detail.get("location") or self._location_from_snippet(snippet),
            salary=detail.get("salary") or "",
            employment_type=detail.get("employment_type") or "",
            source=source if source != "google" else "google",
            source_url=normalize_url(url) or url,
            application_url=url,
            company_website=guess_company_website(url),
            snippet=snippet,
            sources_found=["google"] if source != "google" else ["google"],
        )
        if source != "google" and source not in job.sources_found:
            job.sources_found.append(source)
        job.ensure_defaults()
        if not job.job_title:
            return None
        return job

    @staticmethod
    def _location_from_snippet(snippet: str) -> str:
        match = re.search(
            r"\b([A-Z][a-zA-Z .]+,\s*(?:NJ|PA|DE|NY)(?:\s+\d{5})?)\b",
            snippet or "",
        )
        if match:
            return clean_text(match.group(1))
        if re.search(r"\bremote\b", snippet or "", re.I):
            return "Remote"
        return ""
