"""Shared job record helpers and HTML extraction."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from utils.geo import detect_remote_status
from utils.normalization import job_fingerprint, normalize_url


@dataclass
class RawJob:
    job_title: str = ""
    company_name: str = ""
    job_description: str = ""
    responsibilities: str = ""
    requirements: str = ""
    location: str = ""
    remote_status: str = ""
    employment_type: str = ""
    salary: str = ""
    posting_date: str = ""
    source: str = ""
    source_url: str = ""
    application_url: str = ""
    company_website: str = ""
    snippet: str = ""
    sources_found: list[str] = field(default_factory=list)

    def ensure_defaults(self) -> "RawJob":
        if not self.application_url:
            self.application_url = self.source_url
        if not self.remote_status:
            self.remote_status = detect_remote_status(
                self.location,
                " ".join([self.job_description, self.snippet, self.responsibilities]),
            )
        if self.source and self.source not in self.sources_found:
            self.sources_found.append(self.source)
        return self

    def fingerprint(self) -> str:
        return job_fingerprint(
            self.company_name,
            self.job_title,
            self.location,
            self.source_url or self.application_url,
        )

    def to_dict(self) -> dict[str, Any]:
        self.ensure_defaults()
        data = asdict(self)
        data["job_id"] = self.fingerprint()
        data["sources_found"] = " | ".join(self.sources_found)
        return data


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: str | None) -> str:
    text = re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()
    return text


def parse_google_results(html: str) -> list[dict[str, str]]:
    """Parse organic Google result blocks into title/url/snippet dicts."""
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for block in soup.select("div.g"):
        link = block.find("a", href=True)
        if not link:
            continue
        href = link["href"]
        if not href.startswith("http"):
            continue
        if "google.com" in urlparse(href).netloc:
            continue
        title_el = block.find("h3")
        title = clean_text(title_el.get_text() if title_el else link.get_text())
        snippet_el = block.select_one("div[data-sncf], div.VwiC3b, span.aCOpRe")
        snippet = clean_text(snippet_el.get_text()) if snippet_el else ""
        norm = normalize_url(href)
        if not title or norm in seen:
            continue
        seen.add(norm)
        results.append({"title": title, "url": href, "snippet": snippet})

    # Fallback for alternate SERP layouts
    if not results:
        for link in soup.select("a[href^='http']"):
            href = link.get("href") or ""
            host = urlparse(href).netloc.lower()
            if not host or "google." in host:
                continue
            title = clean_text(link.get_text())
            if len(title) < 8:
                continue
            norm = normalize_url(href)
            if norm in seen:
                continue
            seen.add(norm)
            results.append({"title": title, "url": href, "snippet": ""})
            if len(results) >= 10:
                break
    return results


SALARY_RE = re.compile(
    r"(\$?\d{2,3}(?:,\d{3})?(?:\.\d+)?\s*(?:-|to)\s*\$?\d{2,3}(?:,\d{3})?(?:\.\d+)?"
    r"(?:\s*(?:an hour|/hr|per hour|a year|/yr|per year))?|"
    r"\$?\d{2,3}(?:,\d{3})?\s*(?:an hour|/hr|per hour|a year|/yr|per year))",
    re.I,
)
EMPLOYMENT_RE = re.compile(
    r"\b(full[-\s]?time|part[-\s]?time|contract|temporary|internship|seasonal)\b",
    re.I,
)


def extract_job_fields_from_html(html: str, url: str = "") -> dict[str, str]:
    """Best-effort extraction of job fields from a public job page."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    host = urlparse(url or "").netloc.lower()
    is_craigslist = "craigslist.org" in host

    title = ""
    for sel in (
        "#titletextonly",
        "span#titletextonly",
        "h1.postingtitle",
        "h1",
        "h1.jobsearch-JobInfoHeader-title",
        "[data-testid='jobsearch-JobInfoHeader-title']",
    ):
        el = soup.select_one(sel)
        if el and clean_text(el.get_text()):
            title = clean_text(el.get_text())
            break
    if not title and soup.title:
        title = clean_text(soup.title.get_text().split("|")[0].split("-")[0])

    # Prefer main posting body when available (Craigslist #postingbody).
    body_el = soup.select_one("#postingbody, .jobsearch-JobComponent-description, [class*='description']")
    if body_el:
        body = clean_text(body_el.get_text(" ", strip=True))[:12000]
    else:
        body = clean_text(soup.get_text(" ", strip=True))[:12000]

    responsibilities = ""
    requirements = ""
    for heading_pat, target in (
        (r"responsibilit", "responsibilities"),
        (r"requirement|qualification|what you.*(need|bring)|you will", "requirements"),
    ):
        match = re.search(
            rf"({heading_pat}[^\n]{{0,40}})(.{{0,1200}})",
            body,
            re.I,
        )
        if match:
            chunk = clean_text(match.group(0))[:800]
            if target == "responsibilities":
                responsibilities = chunk
            else:
                requirements = chunk

    salary = ""
    salary_match = SALARY_RE.search(body)
    if salary_match:
        salary = clean_text(salary_match.group(0))
    else:
        comp = re.search(
            r"compensation:\s*([^\n<]+)",
            clean_text(soup.get_text("\n", strip=True)),
            re.I,
        )
        if comp:
            salary = clean_text(comp.group(1))
    employment_match = EMPLOYMENT_RE.search(body)

    company = ""
    for sel in (
        "[data-company-name]",
        ".jobsearch-InlineCompanyRating a",
        "a[data-testid='InlineCompanyName']",
        ".company",
        ".employer",
    ):
        el = soup.select_one(sel)
        if el and clean_text(el.get_text()):
            company = clean_text(el.get_text())
            break
    if not company and is_craigslist:
        # Sometimes company appears near the title block as plain text.
        poster = soup.select_one(".postingtitletext, .house, header.postingtitle")
        poster_text = clean_text(poster.get_text(" ", strip=True)) if poster else ""
        # Look for Inc/LLC style names in attrs/body start
        company_match = re.search(
            r"\b([A-Z][A-Za-z0-9&.' ]{2,60}\s(?:Inc|LLC|L\.L\.C|Corp|Corporation|Ltd)\.?)\b",
            clean_text(soup.get_text(" ", strip=True))[:1500],
        )
        if company_match:
            company = clean_text(company_match.group(1))
        elif poster_text and len(poster_text) < 80:
            company = ""

    location = ""
    for sel in (
        ".postingtitletext small",
        "span.mapaddress",
        "[data-testid='job-location']",
        ".jobsearch-JobInfoHeader-subtitle div",
        ".location",
    ):
        el = soup.select_one(sel)
        if el and clean_text(el.get_text()):
            candidate = clean_text(el.get_text())
            if 2 < len(candidate) < 120:
                location = candidate
                break
    if not location and is_craigslist:
        # Title often ends with "(Cherry Hill)"
        loc_match = re.search(r"\(([^)]+)\)\s*$", title)
        if loc_match:
            location = clean_text(loc_match.group(1))
            title = clean_text(re.sub(r"\s*\([^)]+\)\s*$", "", title))
        elif re.search(r"\bnj\b|south jersey", body, re.I):
            location = "South Jersey, NJ"
    if len(location) > 120:
        location = location[:120]

    return {
        "job_title": title,
        "company_name": company,
        "job_description": body,
        "responsibilities": responsibilities,
        "requirements": requirements,
        "location": location,
        "salary": salary,
        "employment_type": clean_text(employment_match.group(0)) if employment_match else "",
        "source_url": url,
    }


def guess_company_website(url: str) -> str:
    """Return likely company website when URL is a career page, else blank."""
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    if not host:
        return ""
    job_hosts = (
        "indeed.com",
        "ziprecruiter.com",
        "craigslist.org",
        "linkedin.com",
        "glassdoor.com",
        "google.com",
        "bing.com",
        "facebook.com",
        "simplyhired.com",
        "monster.com",
        "careerbuilder.com",
    )
    if any(h in host for h in job_hosts):
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}"
