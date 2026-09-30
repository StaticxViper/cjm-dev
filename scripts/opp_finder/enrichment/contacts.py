"""Public company website and contact research (no guessing, no private data)."""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from utils.constants import FETCH_HEADERS
from utils.jobs import clean_text, guess_company_website
from utils.normalization import normalize_url

logger = logging.getLogger("opp-finder")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)

CONTACT_PATHS = (
    "/contact",
    "/contact-us",
    "/contactus",
    "/about",
    "/about-us",
    "/aboutus",
    "/team",
    "/our-team",
    "/leadership",
    "/people",
    "/careers",
    "/jobs",
)

JUNK_DOMAINS = frozenset({
    "example.com",
    "example.org",
    "sentry.io",
    "wixpress.com",
    "domain.com",
    "email.com",
    "yourdomain.com",
    "googleapis.com",
    "schema.org",
})
JUNK_LOCAL = frozenset({
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "mailer-daemon",
    "postmaster",
    "example",
    "test",
})
ROLE_PRIORITY = [
    ("operations manager", "Operations Manager"),
    ("director of operations", "Director of Operations"),
    ("office manager", "Office Manager"),
    ("owner", "Owner"),
    ("founder", "Founder"),
    ("it manager", "IT Manager"),
    ("technology", "Technology Lead"),
    ("hiring manager", "Hiring Manager"),
    ("recruiter", "Recruiter"),
    ("property manager", "Property Manager"),
    ("general manager", "General Manager"),
]


def validate_email(email: str) -> str:
    value = unescape(str(email or "")).strip()
    if value.lower().startswith("mailto:"):
        value = value[7:]
    value = value.split("?", 1)[0].strip().strip(".,;:<>()[]\"'").lower()
    if not value or not EMAIL_RE.fullmatch(value):
        return ""
    local, _, domain = value.partition("@")
    if not local or not domain or "." not in domain:
        return ""
    if domain in JUNK_DOMAINS or any(domain.endswith("." + d) for d in JUNK_DOMAINS):
        return ""
    if local in JUNK_LOCAL or local.startswith("noreply") or local.startswith("no-reply"):
        return ""
    return value


def extract_emails(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in EMAIL_RE.findall(html or ""):
        email = validate_email(match)
        if email and email not in seen:
            seen.add(email)
            found.append(email)
    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if href.lower().startswith("mailto:"):
            email = validate_email(href)
            if email and email not in seen:
                seen.add(email)
                found.append(email)
    return found


def extract_phones(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in PHONE_RE.findall(html or ""):
        digits = re.sub(r"\D", "", match)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            continue
        pretty = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        if pretty not in seen:
            seen.add(pretty)
            found.append(pretty)
    return found


def _fetch(url: str, timeout: int = 15) -> tuple[str, str]:
    try:
        resp = requests.get(url, headers=FETCH_HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            return "", ""
        return str(resp.url), resp.text or ""
    except requests.RequestException as exc:
        logger.debug("Contact fetch failed for %s: %s", url, exc)
        return "", ""


def _role_from_html(html: str) -> tuple[str, str]:
    """Return (name, role) if a prioritized public role mention is found."""
    text = clean_text(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))
    lower = text.lower()
    for needle, role in ROLE_PRIORITY:
        idx = lower.find(needle)
        if idx < 0:
            continue
        window = text[max(0, idx - 80) : idx + 120]
        # Heuristic: look for a Capitalized Name near the role
        name_match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", window)
        name = name_match.group(1) if name_match else ""
        return name, role
    return "", ""


def recommend_contact_role(job: dict[str, Any]) -> str:
    title = str(job.get("job_title") or "").lower()
    industryish = f"{title} {job.get('job_description') or ''}".lower()
    if "property" in industryish or "real estate" in industryish:
        return "Property Manager"
    if "qa" in industryish or "software" in industryish:
        return "Director of Operations"
    if "ecommerce" in industryish or "listing" in industryish:
        return "Operations Manager"
    if "admin" in industryish or "office" in industryish:
        return "Office Manager"
    return "Operations Manager"


def enrich_company_and_contacts(
    job: dict[str, Any],
    *,
    browser=None,
    max_pages: int = 6,
) -> dict[str, Any]:
    """Research public company pages and return contact enrichment fields only."""
    website = str(job.get("company_website") or "").strip()
    if not website:
        website = guess_company_website(str(job.get("source_url") or ""))
    if not website and job.get("company_name"):
        # Do not invent a domain; leave blank.
        website = ""

    result = {
        "company_website": website,
        "company_industry": "",
        "company_phone": "",
        "company_email": "",
        "recommended_contact_name": "",
        "recommended_contact_role": recommend_contact_role(job),
        "contact_email": "",
        "contact_phone": "",
        "contact_source_url": "",
        "contact_verified": False,
        "contact_confidence": "unverified",
        "contactability_score": 20,
    }
    if not website:
        return result

    parsed = urlparse(website if "://" in website else f"https://{website}")
    base = f"{parsed.scheme}://{parsed.netloc}"
    pages = [base] + [urljoin(base, path) for path in CONTACT_PATHS]
    pages = pages[:max_pages]

    all_emails: list[str] = []
    all_phones: list[str] = []
    best_name = ""
    best_role = result["recommended_contact_role"]
    evidence_url = ""
    about_text = ""

    for page_url in pages:
        if browser is not None:
            final_url, html = browser.goto(page_url, source="company_research")
        else:
            final_url, html = _fetch(page_url)
        if not html:
            continue
        emails = extract_emails(html)
        phones = extract_phones(html)
        if emails or phones:
            if not evidence_url:
                evidence_url = final_url or page_url
            for e in emails:
                if e not in all_emails:
                    all_emails.append(e)
            for p in phones:
                if p not in all_phones:
                    all_phones.append(p)
        name, role = _role_from_html(html)
        if name and not best_name:
            best_name = name
            best_role = role or best_role
            if not evidence_url:
                evidence_url = final_url or page_url
        if "/about" in page_url or page_url.rstrip("/") == base.rstrip("/"):
            about_text = clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))[:500]

    # Prefer business-looking emails over consumer inboxes
    preferred = [e for e in all_emails if not e.split("@")[1] in {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com"
    }]
    chosen_email = (preferred or all_emails or [""])[0]
    chosen_phone = (all_phones or [""])[0]

    result["company_email"] = chosen_email
    result["company_phone"] = chosen_phone
    result["contact_email"] = chosen_email
    result["contact_phone"] = chosen_phone
    result["recommended_contact_name"] = best_name
    result["recommended_contact_role"] = best_role
    result["contact_source_url"] = normalize_url(evidence_url) if evidence_url else ""
    if about_text:
        # Lightweight industry hint from about text — factual excerpt only if keywords exist
        for label, pat in (
            ("Real Estate", r"real estate|propert(y|ies)|mls"),
            ("E-commerce", r"e-?commerce|online store|marketplace"),
            ("Staffing", r"staffing|recruiting|temporary placement"),
            ("Healthcare", r"health ?care|medical|clinic"),
            ("Professional Services", r"consulting|professional services|accounting"),
        ):
            if re.search(pat, about_text, re.I):
                result["company_industry"] = label
                break

    if chosen_email or chosen_phone:
        result["contact_verified"] = True
        result["contact_confidence"] = "verified_public"
        result["contactability_score"] = 75 if chosen_email else 55
        if best_name:
            result["contactability_score"] = min(100, int(result["contactability_score"]) + 15)
    elif website:
        result["contactability_score"] = 35
        result["contact_confidence"] = "unverified"

    return result
