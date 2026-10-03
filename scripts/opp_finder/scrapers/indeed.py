"""Indeed public search scraper (best-effort; skips on CAPTCHA/block)."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from scrapers import SearchContext
from utils.jobs import RawJob, clean_text, extract_job_fields_from_html
from utils.normalization import normalize_url

logger = logging.getLogger("opp-finder")


class IndeedScraper:
    name = "indeed"

    def search(self, ctx: SearchContext) -> list[RawJob]:
        browser = ctx.browser
        if browser is None or browser.is_blocked(self.name):
            return []

        jobs: list[RawJob] = []
        # Use ordered multi-location phrases (remote-first when configured).
        locations = list(ctx.location_phrases[:8]) if ctx.location_phrases else []
        if ctx.remote_only:
            locations = [p for p in locations if "remote" in p.lower() or "work from home" in p.lower()]
            if not locations:
                locations = ["Remote"]
        elif not locations:
            locations = ["Remote", "South Jersey, NJ", "Philadelphia, PA", "Wilmington, DE"]
        # Cap keyword fan-out for MVP pacing
        keywords = ctx.keywords[: max(3, min(12, int(ctx.max_total_jobs)))]

        for keyword in keywords:
            if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                break
            for location in locations:
                if browser.is_blocked(self.name):
                    return jobs
                if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                    break
                query = f"https://www.indeed.com/jobs?q={quote_plus(keyword)}&l={quote_plus(location)}"
                logger.info('[SEARCH] Indeed — "%s" %s', keyword, location)
                final_url, html = browser.goto(query, source=self.name)
                if not html:
                    continue
                cards = self._parse_listing_cards(html, final_url or query)
                logger.info("[SEARCH] Found %d results", len(cards))
                for card in cards[: ctx.max_results_per_keyword]:
                    if len(ctx.collected) + len(jobs) >= ctx.max_total_jobs:
                        break
                    job = self._hydrate(card, browser)
                    if job:
                        jobs.append(job)
        return jobs

    def _parse_listing_cards(self, html: str, base_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html or "", "html.parser")
        cards: list[dict[str, str]] = []
        seen: set[str] = set()
        for node in soup.select("a[data-jk], a.jcs-JobTitle, div.job_seen_beacon a"):
            href = node.get("href") or ""
            if not href:
                continue
            url = urljoin(base_url, href)
            if "/rc/clk" not in url and "/viewjob" not in url and "jk=" not in url and "/pagead/" not in url:
                # Still accept /job/ style links
                if "/job/" not in url and "indeed.com" not in url:
                    continue
            title = clean_text(node.get_text())
            if len(title) < 3:
                title_el = node.select_one("span, h2")
                title = clean_text(title_el.get_text()) if title_el else title
            norm = normalize_url(url)
            if not title or norm in seen:
                continue
            seen.add(norm)
            parent = node.find_parent("div", class_=lambda c: c and "job" in c.lower()) or node.parent
            company = ""
            location = ""
            if parent:
                company_el = parent.select_one("[data-testid='company-name'], span.companyName, span[class*='company']")
                loc_el = parent.select_one("[data-testid='text-location'], div.companyLocation")
                company = clean_text(company_el.get_text()) if company_el else ""
                location = clean_text(loc_el.get_text()) if loc_el else ""
            cards.append(
                {
                    "title": title,
                    "url": url,
                    "company": company,
                    "location": location,
                }
            )
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
