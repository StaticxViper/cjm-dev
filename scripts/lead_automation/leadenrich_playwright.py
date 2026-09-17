#!/usr/bin/env python3
"""
leadenrich_playwright.py

Google/Playwright lead enrichment — the counterpart to Facebook/Apify
enrichment in leadenrich.py.

For every candidate lead this script Google-searches the business, classifies
Facebook pages / official websites / directory listings, visits the site in
Chromium, and records contact details plus an SEO/improvement audit.

Run: python leadenrich_playwright.py --json-path leads_output.json
     python leadenrich_playwright.py --from-crm
"""
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import argparse
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from email_discovery import (
    BROWSER_TIMEOUT,
    CONTACT_PAGE_PATHS,
    EmailDiscoverySession,
    discover_business_website,
    extract_emails_from_html,
    extract_phones_from_html,
    inspect_website,
    is_directory_host,
    parse_address_parts,
    validate_email,
)
from helper_scripts.api_manager import APIManager
from helper_scripts.utils.logger.logger import setup_logger
from leadenrich import (
    load_leads,
    name_similarity,
    normalize_business_name,
    normalize_facebook_url,
    save_leads,
)

load_dotenv()

DEFAULT_JSON_PATH = "leads_output.json"
DASHBOARD_BASE_URL = "https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1"
CRM_EXPORT_ENDPOINT = "/crm-leads-export"
CRM_PAGE_SIZE = 500
DEFAULT_CRM_STATUSES = ("New Lead", "Contacted")

ENRICHMENT_SOURCE = "playwright_google"
STATUS_ENRICHED = "enriched"
STATUS_RESEARCHED = "researched"
STATUS_NO_MATCH = "no_match"
STATUS_SCRAPE_FAILED = "scrape_failed"
RETRYABLE_STATUSES = frozenset({STATUS_SCRAPE_FAILED})

MAX_QUERIES_PER_LEAD = 4
MIN_TITLE_LEN = 10
MAX_TITLE_LEN = 70
MIN_META_LEN = 50
MAX_META_LEN = 160
THIN_CONTENT_WORDS = 100
CTA_KEYWORDS = ("call", "contact", "quote", "estimate", "book", "schedule")

SEO_WEIGHTS = {
    "no_https": 14,
    "no_viewport": 10,
    "no_title": 10,
    "title_length": 6,
    "no_meta_description": 10,
    "meta_length": 4,
    "no_h1": 8,
    "multiple_h1": 4,
    "no_canonical": 4,
    "no_open_graph": 4,
    "noindex": 6,
    "no_schema": 4,
    "missing_image_alts": 4,
    "thin_content": 6,
    "no_cta": 4,
    "mixed_content": 2,
}
assert sum(SEO_WEIGHTS.values()) == 100

SOCIAL_LABELS = {
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "yelp.com": "yelp",
    "bbb.org": "bbb",
    "yellowpages.com": "yellowpages",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "youtube.com": "youtube",
    "tiktok.com": "tiktok",
}

logger = setup_logger(
    name="leadenrich-playwright",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)


@dataclass
class EnrichConfig:
    json_path: str = DEFAULT_JSON_PATH
    output_path: str = None
    limit: int = 0
    min_similarity: float = 0.72
    max_queries: int = MAX_QUERIES_PER_LEAD
    retry_all: bool = False
    dry_run: bool = False
    dashboard: bool = False
    from_crm: bool = False
    crm_status: list = field(default_factory=lambda: list(DEFAULT_CRM_STATUSES))
    category: str = None
    has_phone: bool = None
    missing_email: bool = True
    min_score: int = None
    max_score: int = None
    search: str = None
    since: str = None
    crm_page_size: int = CRM_PAGE_SIZE


def _iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _host_from_url(url):
    if not url:
        return ""
    raw = url if "://" in str(url) else f"http://{url}"
    try:
        host = (urlparse(raw).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""
    return host


def _normalize_website_url(url):
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def build_research_queries(lead, max_queries=MAX_QUERIES_PER_LEAD):
    """Google queries that find the business site, Facebook page, and contact info."""
    name = (lead.get("business_name") or "").strip()
    if not name:
        return []
    addr = parse_address_parts(lead.get("address"))
    city = addr.get("city")
    state = addr.get("state")
    phone = (lead.get("phone_google") or lead.get("phone") or "").strip()
    quoted = f'"{name}"'

    queries = []
    if city and state:
        queries.append(f'{quoted} "{city}" {state}')
        queries.append(f'{quoted} "{city}" {state} facebook')
        queries.append(f'{quoted} "{city}" {state} website')
    else:
        queries.append(quoted)
        queries.append(f"{quoted} facebook")
        queries.append(f"{quoted} official website")
    if phone:
        queries.append(f"{quoted} {phone}")
    if city:
        queries.append(f'{quoted} "{city}" contact')

    seen = set()
    out = []
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        out.append(query)
        if len(out) >= max_queries:
            break
    return out


def classify_serp_result(result, lead, min_similarity=0.72):
    """Tag one SERP hit as facebook, website, or directory. Returns None if unusable."""
    url = (result.get("url") or "").strip() if isinstance(result, dict) else ""
    if not url:
        return None
    title = result.get("title") or ""
    snippet = result.get("snippet") or ""
    facebook_url = normalize_facebook_url(url)
    if facebook_url:
        score = name_similarity(
            normalize_business_name(lead.get("business_name") if lead else ""),
            normalize_business_name(title or facebook_url),
        )
        return {
            "kind": "facebook",
            "url": facebook_url,
            "title": title,
            "snippet": snippet,
            "score": score,
            "accepted": score >= min_similarity,
        }
    host = _host_from_url(url)
    if is_directory_host(url):
        label = None
        for domain, name in SOCIAL_LABELS.items():
            if host == domain or host.endswith("." + domain):
                label = name
                break
        return {
            "kind": "directory",
            "url": url,
            "title": title,
            "snippet": snippet,
            "host": host,
            "label": label or host,
        }
    return {
        "kind": "website",
        "url": url,
        "title": title,
        "snippet": snippet,
        "host": host,
    }


def classify_serp_results(results, lead, min_similarity=0.72):
    classified = []
    seen = set()
    for result in results or []:
        item = classify_serp_result(result, lead, min_similarity)
        if not item:
            continue
        key = (item["kind"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        classified.append(item)
    return classified


def pick_facebook_url(classified, min_similarity=0.72):
    """Return (url, score) for the best accepted Facebook page, or (None, best_score)."""
    best_url = None
    best_score = 0.0
    for item in classified or []:
        if item.get("kind") != "facebook":
            continue
        score = float(item.get("score") or 0.0)
        if score > best_score:
            best_score = score
            if score >= min_similarity:
                best_url = item.get("url")
    return best_url, best_score


def pick_website_url(classified, lead):
    """Official site from the lead row or from non-directory SERP hits."""
    known = (lead.get("website") or "").strip() if lead else ""
    if known and not is_directory_host(known) and not normalize_facebook_url(known):
        return _normalize_website_url(known)
    serp = [
        {"url": item.get("url"), "title": item.get("title"), "snippet": item.get("snippet")}
        for item in classified or []
        if item.get("kind") == "website"
    ]
    found = discover_business_website(serp, lead or {})
    return _normalize_website_url(found) if found else None


def extract_social_links(html, base_url=""):
    """Return {label: url} for Facebook and other social/directory links in HTML."""
    found = {}
    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, (anchor.get("href") or "").strip())
        facebook_url = normalize_facebook_url(href)
        if facebook_url:
            found.setdefault("facebook", facebook_url)
            continue
        host = _host_from_url(href)
        for domain, label in SOCIAL_LABELS.items():
            if host == domain or host.endswith("." + domain):
                found.setdefault(label, href)
                break
    return found


def _meta_content(soup, name=None, prop=None):
    if name:
        tag = soup.find("meta", attrs={"name": lambda v: v and str(v).lower() == name.lower()})
    elif prop:
        tag = soup.find("meta", attrs={"property": lambda v: v and str(v).lower() == prop.lower()})
    else:
        return ""
    if not tag:
        return ""
    return (tag.get("content") or "").strip()


def analyze_seo(html, url="", load_error=None):
    """Heuristic SEO/improvement audit. Higher score = more opportunity (0-100)."""
    if load_error or not html:
        return {
            "score": 100,
            "issues": ["Site did not load or returned no HTML"],
            "recommendations": [
                "Confirm the website URL is correct and the site is online",
                "Rebuild or replace a broken/expired site",
            ],
            "https": str(url or "").lower().startswith("https://"),
            "title": "",
            "word_count": 0,
        }

    soup = BeautifulSoup(html, "html.parser")
    issues = []
    recommendations = []
    raw = 0
    url = url or ""
    https = url.lower().startswith("https://")

    if not https:
        raw += SEO_WEIGHTS["no_https"]
        issues.append("Site is not served over HTTPS")
        recommendations.append("Enable HTTPS and redirect HTTP traffic")

    viewport = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "viewport"})
    if not viewport:
        raw += SEO_WEIGHTS["no_viewport"]
        issues.append("Missing mobile viewport meta tag")
        recommendations.append("Add a viewport meta tag for mobile rendering")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        raw += SEO_WEIGHTS["no_title"]
        issues.append("Missing page title")
        recommendations.append("Add a unique title of about 50-60 characters")
    elif len(title) < MIN_TITLE_LEN or len(title) > MAX_TITLE_LEN:
        raw += SEO_WEIGHTS["title_length"]
        issues.append(f"Title length is {len(title)} characters (aim {MIN_TITLE_LEN}-{MAX_TITLE_LEN})")
        recommendations.append("Rewrite the title to a clear 50-60 character business + city phrase")

    description = _meta_content(soup, name="description")
    if not description:
        raw += SEO_WEIGHTS["no_meta_description"]
        issues.append("Missing meta description")
        recommendations.append("Add a 120-160 character meta description")
    elif len(description) < MIN_META_LEN or len(description) > MAX_META_LEN:
        raw += SEO_WEIGHTS["meta_length"]
        issues.append(f"Meta description length is {len(description)} characters")
        recommendations.append("Tighten the meta description to 120-160 characters")

    h1s = soup.find_all("h1")
    if not h1s:
        raw += SEO_WEIGHTS["no_h1"]
        issues.append("No H1 heading")
        recommendations.append("Add a single H1 with the business name and primary service")
    elif len(h1s) > 1:
        raw += SEO_WEIGHTS["multiple_h1"]
        issues.append(f"Found {len(h1s)} H1 headings")
        recommendations.append("Keep a single H1 and demote the rest to H2")

    canonical = soup.find("link", attrs={"rel": lambda v: v and "canonical" in str(v).lower()})
    if not canonical or not (canonical.get("href") or "").strip():
        raw += SEO_WEIGHTS["no_canonical"]
        issues.append("Missing canonical URL")
        recommendations.append("Add a rel=canonical link to the preferred homepage URL")

    og_title = _meta_content(soup, prop="og:title")
    og_desc = _meta_content(soup, prop="og:description")
    if not og_title and not og_desc:
        raw += SEO_WEIGHTS["no_open_graph"]
        issues.append("Missing Open Graph tags")
        recommendations.append("Add og:title, og:description, and og:image for social sharing")

    robots = (_meta_content(soup, name="robots") or "").lower()
    if "noindex" in robots:
        raw += SEO_WEIGHTS["noindex"]
        issues.append("Robots meta is set to noindex")
        recommendations.append("Remove noindex if the page should appear in Google")

    has_schema = bool(
        soup.find("script", attrs={"type": lambda t: t and "ld+json" in t.lower()})
    )
    if not has_schema:
        raw += SEO_WEIGHTS["no_schema"]
        issues.append("No JSON-LD structured data")
        recommendations.append("Add LocalBusiness JSON-LD with name, address, phone, and hours")

    images = soup.find_all("img")
    if images:
        missing_alt = sum(1 for img in images if not (img.get("alt") or "").strip())
        if missing_alt / len(images) > 0.5:
            raw += SEO_WEIGHTS["missing_image_alts"]
            issues.append(f"{missing_alt}/{len(images)} images are missing alt text")
            recommendations.append("Add descriptive alt text to images")

    text = soup.get_text(separator=" ", strip=True)
    words = [w for w in re.split(r"\s+", text) if w]
    if len(words) < THIN_CONTENT_WORDS:
        raw += SEO_WEIGHTS["thin_content"]
        issues.append(f"Thin content ({len(words)} words)")
        recommendations.append("Add service pages and a clear description of what the business does")

    lowered = text.lower()
    if not any(kw in lowered for kw in CTA_KEYWORDS):
        raw += SEO_WEIGHTS["no_cta"]
        issues.append("No call-to-action wording on the page")
        recommendations.append("Add a visible Call / Contact / Get a quote button")

    if https:
        mixed = False
        for tag in soup.find_all(["img", "script", "link", "iframe"]):
            src = tag.get("src") or tag.get("href") or ""
            if src.startswith("http://"):
                mixed = True
                break
        if mixed:
            raw += SEO_WEIGHTS["mixed_content"]
            issues.append("HTTP assets loaded on an HTTPS page")
            recommendations.append("Serve images and scripts over HTTPS")

    return {
        "score": round(raw / 100 * 100),
        "issues": issues,
        "recommendations": recommendations,
        "https": https,
        "title": title,
        "word_count": len(words),
    }


def _empty_visit(url, error):
    return {
        "url": url,
        "final_url": url,
        "html": "",
        "title": "",
        "status": None,
        "emails": [],
        "phones": [],
        "social": {},
        "error": error,
        "via": None,
    }


def _visit_with_playwright(page, url):
    """Load homepage (and contact paths if needed) with the shared Chromium page."""
    url = _normalize_website_url(url)
    result = _empty_visit(url, None)
    result["via"] = "playwright"
    html = ""
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT * 1000)
        result["status"] = getattr(response, "status", None) if response is not None else None
        result["final_url"] = page.url or url
        html = page.content() or ""
        result["title"] = page.title() or ""
    except Exception as exc:
        result["error"] = str(exc)
        return result

    result["html"] = html
    result["emails"] = extract_emails_from_html(html, website=url)
    result["phones"] = extract_phones_from_html(html)
    result["social"] = extract_social_links(html, result["final_url"])

    if result["emails"]:
        return result

    parsed = urlparse(result["final_url"] or url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for path in CONTACT_PAGE_PATHS:
        page_url = urljoin(base + "/", path.lstrip("/"))
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT * 1000)
            page_html = page.content() or ""
        except Exception:
            continue
        emails = extract_emails_from_html(page_html, website=url)
        phones = extract_phones_from_html(page_html)
        social = extract_social_links(page_html, page_url)
        result["emails"] = emails
        result["phones"] = sorted(set(result["phones"]) | set(phones))
        for key, value in social.items():
            result["social"].setdefault(key, value)
        if emails:
            result["html"] = result["html"] + "\n" + page_html
            break
    return result


def _visit_with_requests(url):
    """Fallback site fetch when the Playwright page is unavailable."""
    url = _normalize_website_url(url)
    inspected = inspect_website(url)
    html = ""
    if not inspected.get("error"):
        try:
            from email_discovery import fetch_html

            html = fetch_html(url)
        except Exception:
            html = ""
    return {
        "url": url,
        "final_url": inspected.get("page_url") or url,
        "html": html,
        "title": "",
        "status": None if inspected.get("error") else 200,
        "emails": inspected.get("emails") or [],
        "phones": inspected.get("phones") or [],
        "social": extract_social_links(html, url),
        "error": inspected.get("error"),
        "via": "requests",
    }


def visit_website(session, url):
    """Visit a business site via the shared session page, else requests."""
    if not url:
        return _empty_visit(url, "no url")
    page = None
    if session is not None and not getattr(session, "google_blocked", False):
        ensure = getattr(session, "_ensure_browser", None)
        if callable(ensure):
            page = ensure()
    if page is not None:
        return _visit_with_playwright(page, url)
    return _visit_with_requests(url)


def needs_enrichment(lead, retry_all=False):
    """True when the lead has not completed Playwright Google research."""
    enrichment = (lead or {}).get("enrichment") or {}
    if retry_all or enrichment.get("source") != ENRICHMENT_SOURCE:
        return True
    return enrichment.get("status") in RETRYABLE_STATUSES


def crm_lead_to_row(crm):
    """Map a CRM Pipeline export item onto the leadgen row shape."""
    if not isinstance(crm, dict):
        return {}
    email = crm.get("email") or ""
    if email is None:
        email = ""
    phone = crm.get("phone") or ""
    score = crm.get("score")
    try:
        score = int(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return {
        "crm_id": crm.get("id"),
        "business_name": crm.get("business_name") or "",
        "address": crm.get("address") or "",
        "phone_google": phone,
        "email": email,
        "has_email": bool(str(email).strip()),
        "website": crm.get("website") or "",
        "lead_score": score,
        "business_status": crm.get("business_status"),
        "niche_key": crm.get("source_group_name") or crm.get("category"),
        "tags": list(crm.get("tags") or []),
        "notes": crm.get("notes") or "",
        "source": "crm_pipeline",
    }


def _crm_leads_from_response(response):
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if not isinstance(response, dict):
        return []
    leads = response.get("leads")
    if isinstance(leads, list):
        return [item for item in leads if isinstance(item, dict)]
    return []


def build_crm_export_body(config, limit, offset):
    """Request body for POST /crm-leads-export."""
    body = {"format": "json", "limit": int(limit), "offset": int(offset)}
    statuses = list(config.crm_status or [])
    if statuses:
        body["status"] = statuses
    if config.category:
        body["category"] = config.category
    if config.has_phone is not None:
        body["has_phone"] = bool(config.has_phone)
    if config.missing_email is not None:
        body["missing_email"] = bool(config.missing_email)
    if config.min_score is not None:
        body["min_score"] = int(config.min_score)
    if config.max_score is not None:
        body["max_score"] = int(config.max_score)
    if config.search:
        body["search"] = config.search
    if config.since:
        body["since"] = config.since
    return body


def fetch_crm_leads(config, api_cls=None):
    """Pull Pipeline leads via API Manager. Paginates until limit or end of list."""
    manager_cls = api_cls or APIManager
    page_size = int(config.crm_page_size or CRM_PAGE_SIZE)
    if config.limit and 0 < config.limit < page_size:
        page_size = config.limit

    offset = 0
    collected = []
    total = None
    while True:
        body = build_crm_export_body(config, limit=page_size, offset=offset)
        logger.critical(
            "[CRM] Exporting leads offset=%d limit=%d",
            offset,
            page_size,
        )
        response = manager_cls().build_request(
            base_url=DASHBOARD_BASE_URL,
            endpoint=CRM_EXPORT_ENDPOINT,
            json_body=body,
            api="Lead Ingest",
            method="POST",
            timeout=60.0,
        )
        batch = _crm_leads_from_response(response)
        if isinstance(response, dict) and total is None:
            try:
                total = int(response.get("total")) if response.get("total") is not None else None
            except (TypeError, ValueError):
                total = None
        if not batch:
            break
        collected.extend(batch)
        if config.limit and len(collected) >= config.limit:
            collected = collected[: config.limit]
            break
        offset += len(batch)
        if total is not None and offset >= total:
            break
        if len(batch) < page_size:
            break

    rows = [crm_lead_to_row(item) for item in collected]
    logger.critical("[CRM] Pulled %d leads from Pipeline export", len(rows))
    return rows


def _best_email(candidates, website=None):
    for email in candidates or []:
        valid = validate_email(email)
        if valid:
            return valid
    return None


def apply_research(lead, research):
    """Write Google/site findings onto a lead in place and return the status."""
    research = research or {}
    website = research.get("website")
    facebook_url = research.get("facebook_url")
    email = research.get("email")
    phones = research.get("phones") or []
    load_error = research.get("load_error")
    url_source = research.get("url_source")

    gained_email = False
    if email and not str(lead.get("email") or "").strip():
        lead["email"] = email
        lead["has_email"] = True
        lead["email_source"] = "playwright_google"
        gained_email = True
    if website and not str(lead.get("website") or "").strip():
        lead["website"] = website
    if facebook_url:
        lead["facebook_url"] = facebook_url
    if phones and not str(lead.get("phone_website") or "").strip():
        lead["phone_website"] = ";".join(phones)
    if research.get("seo"):
        lead["seo"] = research["seo"]
    lead["research"] = {
        "queries": research.get("queries") or [],
        "links": research.get("links") or [],
        "load_ok": not bool(load_error),
        "title": (research.get("seo") or {}).get("title") or research.get("title") or "",
        "visit_via": research.get("visit_via"),
    }

    if research.get("failed"):
        status = STATUS_SCRAPE_FAILED
    elif gained_email:
        status = STATUS_ENRICHED
    elif website or facebook_url:
        status = STATUS_RESEARCHED
    else:
        status = STATUS_NO_MATCH

    lead["enrichment"] = {
        "source": ENRICHMENT_SOURCE,
        "status": status,
        "url_source": url_source,
        "checked_at": _iso_now(),
    }
    return status


def research_lead(lead, session, config):
    """Google-search and (unless dry-run) visit the business. Does not mutate lead."""
    queries = build_research_queries(lead, max_queries=config.max_queries)
    serp = []
    for query in queries:
        if getattr(session, "google_blocked", False):
            logger.info("[GOOGLE] Blocked; skipping remaining searches for %s", lead.get("business_name"))
            break
        serp.extend(session.search(query) or [])

    classified = classify_serp_results(serp, lead, config.min_similarity)
    facebook_url, fb_score = pick_facebook_url(classified, config.min_similarity)
    known_facebook = normalize_facebook_url(lead.get("facebook_url") or lead.get("website"))
    if known_facebook and not facebook_url:
        facebook_url = known_facebook
        fb_score = 1.0
    website = pick_website_url(classified, lead)
    directory_links = [
        {"label": item.get("label"), "url": item.get("url"), "title": item.get("title")}
        for item in classified
        if item.get("kind") == "directory"
    ]
    url_source = None
    if website and _host_from_url(website) == _host_from_url(lead.get("website")):
        url_source = "website"
    elif website:
        url_source = "search"
    elif facebook_url:
        url_source = "facebook" if known_facebook else "search"

    research = {
        "queries": queries,
        "website": website,
        "facebook_url": facebook_url,
        "facebook_score": fb_score,
        "links": directory_links,
        "url_source": url_source,
        "email": None,
        "phones": [],
        "seo": None,
        "title": "",
        "load_error": None,
        "visit_via": None,
    }

    if config.dry_run:
        logger.critical(
            "[dry run] %s queries=%d facebook=%s website=%s",
            lead.get("business_name"),
            len(queries),
            facebook_url or "none",
            website or "none",
        )
        return research

    visit = None
    if website:
        visit = visit_website(session, website)
        research["visit_via"] = (visit or {}).get("via")
        research["load_error"] = (visit or {}).get("error")
        research["title"] = (visit or {}).get("title") or ""
        social = (visit or {}).get("social") or {}
        if not facebook_url:
            facebook_url = social.get("facebook")
            research["facebook_url"] = facebook_url
            if facebook_url and not url_source:
                research["url_source"] = "website"
        for label, link in social.items():
            if label == "facebook":
                continue
            directory_links.append({"label": label, "url": link, "title": ""})
        research["links"] = directory_links
        research["email"] = _best_email((visit or {}).get("emails"), website)
        research["phones"] = (visit or {}).get("phones") or []
        research["seo"] = analyze_seo(
            (visit or {}).get("html") or "",
            (visit or {}).get("final_url") or website,
            load_error=(visit or {}).get("error"),
        )
    elif facebook_url:
        research["seo"] = analyze_seo("", "", load_error="no website to audit")
        research["load_error"] = "no website to audit"
    else:
        research["load_error"] = "no website or facebook match"
        research["seo"] = analyze_seo("", "", load_error=research["load_error"])

    return research


def enrich_leads(leads, config=None, session=None):
    """Enrich a list of lead rows in place; returns rows that received a research record.

    This is the entry point used by leadgen at the end of a Playwright run.
    """
    config = config or EnrichConfig()
    enrich_stages = 4
    logger.critical("[ENRICH STAGE 1/%d] Select Playwright Google candidates", enrich_stages)

    candidates = [lead for lead in leads if needs_enrichment(lead, config.retry_all)]
    if config.limit > 0:
        candidates = candidates[: config.limit]
    if not candidates:
        logger.critical(
            "[ENRICH STAGE 1/%d] No leads need Playwright enrichment "
            "(%d total leads inspected)",
            enrich_stages,
            len(leads),
        )
        return []

    logger.critical(
        "[ENRICH STAGE 1/%d] Researching %d of %d leads",
        enrich_stages,
        len(candidates),
        len(leads),
    )
    for index, lead in enumerate(candidates, 1):
        logger.info(
            "[ENRICH STEP 1.%d] Candidate %d/%d: %s (address=%s website=%s)",
            index,
            index,
            len(candidates),
            lead.get("business_name") or "(unnamed)",
            (lead.get("address") or "")[:60] or "none",
            "yes" if (lead.get("website") or "").strip() else "no",
        )

    own_session = session is None
    if session is None:
        session = EmailDiscoverySession()

    processed = []
    status_counts = {}
    try:
        logger.critical("[ENRICH STAGE 2/%d] Google search + classify", enrich_stages)
        logger.critical("[ENRICH STAGE 3/%d] Visit websites and SEO audit", enrich_stages)
        logger.critical("[ENRICH STAGE 4/%d] Apply research to leads", enrich_stages)
        for index, lead in enumerate(candidates, 1):
            try:
                research = research_lead(lead, session, config)
            except Exception as exc:
                logger.error(
                    "Playwright enrichment failed for %s: %s",
                    lead.get("business_name"),
                    exc,
                )
                research = {
                    "queries": [],
                    "load_error": str(exc),
                    "url_source": None,
                    "failed": True,
                }
            if config.dry_run:
                continue
            status = apply_research(lead, research)
            status_counts[status] = status_counts.get(status, 0) + 1
            processed.append(lead)
            business_name = lead.get("business_name") or "(unnamed)"
            if status == STATUS_ENRICHED:
                logger.info(
                    "[ENRICH STEP 4.%d] Found %s for %s",
                    index,
                    lead.get("email"),
                    business_name,
                )
            else:
                logger.info(
                    "[ENRICH STEP 4.%d] %s -> %s (website=%s facebook=%s)",
                    index,
                    business_name,
                    status,
                    lead.get("website") or "none",
                    lead.get("facebook_url") or "none",
                )
    finally:
        if own_session:
            session.close()

    if config.dry_run:
        logger.critical("[ENRICH STAGE 4/%d] Dry run — skip apply/write", enrich_stages)
        return []

    for status, count in sorted(status_counts.items()):
        logger.critical("[ENRICH STAGE 4/%d] %s: %d", enrich_stages, status, count)
    logger.critical(
        "[ENRICH STAGE 4/%d] Done — %d researched / %d candidates",
        enrich_stages,
        len(processed),
        len(candidates),
    )
    return processed


def run_enrichment(config):
    """Load leads from CRM and/or JSON, enrich, save, optionally ingest."""
    if config.dashboard and not os.getenv("LEAD_INGEST_KEY"):
        logger.error("LEAD_INGEST_KEY is required for dashboard ingest.")
        return
    if config.from_crm and not os.getenv("LEAD_INGEST_KEY"):
        logger.error("LEAD_INGEST_KEY is required to pull CRM Pipeline leads.")
        return

    if config.from_crm:
        try:
            leads = fetch_crm_leads(config)
        except Exception as exc:
            logger.error("CRM Pipeline export failed: %s", exc)
            return
        if not leads:
            logger.critical("No leads returned from CRM export.")
            return
    else:
        leads = load_leads(config.json_path)
        if not leads:
            return

    snapshots = {id(lead): str(lead.get("email") or "") for lead in leads}
    processed = enrich_leads(leads, config)
    if config.dry_run:
        return

    save_leads(leads, config.output_path or config.json_path)

    emailed = [
        lead for lead in processed
        if str(lead.get("email") or "").strip()
        and str(lead.get("email") or "").strip() != snapshots.get(id(lead), "")
    ]
    if config.dashboard and emailed:
        from leadgen import send_to_dashboard

        send_to_dashboard(emailed)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enrich leads with Google/Playwright research and SEO analysis",
    )
    parser.add_argument(
        "--json-path",
        default=DEFAULT_JSON_PATH,
        help=f"Leads JSON produced by leadgen (default {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--output-path",
        help="Write results here instead of overwriting the input file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum leads to enrich this run; 0 means no limit",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.72,
        help="Minimum business name similarity to accept a Facebook match (default 0.72)",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=MAX_QUERIES_PER_LEAD,
        help=f"Google searches per lead (default {MAX_QUERIES_PER_LEAD})",
    )
    parser.add_argument(
        "--retry-all",
        action="store_true",
        help="Re-attempt every lead, including ones already researched",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and report matches only; skip site visits and writes",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Bulk-ingest newly emailed leads to the dashboard",
    )
    parser.add_argument(
        "--from-crm",
        action="store_true",
        help="Pull Pipeline leads from POST /crm-leads-export instead of a JSON file",
    )
    parser.add_argument(
        "--status",
        action="append",
        dest="crm_status",
        help="CRM status filter (repeatable; default New Lead and Contacted)",
    )
    parser.add_argument(
        "--category",
        help="CRM category / source group filter",
    )
    parser.add_argument(
        "--has-phone",
        dest="has_phone",
        action="store_true",
        default=None,
        help="CRM: only leads that have a phone",
    )
    parser.add_argument(
        "--missing-email",
        dest="missing_email",
        action="store_true",
        default=None,
        help="CRM: only leads missing an email (default when --from-crm)",
    )
    parser.add_argument(
        "--no-missing-email",
        dest="missing_email",
        action="store_false",
        help="CRM: include leads that already have an email",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        help="CRM minimum score filter",
    )
    parser.add_argument(
        "--max-score",
        type=int,
        help="CRM maximum score filter",
    )
    parser.add_argument(
        "--search",
        help="CRM text search filter",
    )
    parser.add_argument(
        "--since",
        help="CRM created-since filter (YYYY-MM-DD)",
    )
    return parser.parse_args()


def config_from_args(args):
    statuses = args.crm_status if args.crm_status else list(DEFAULT_CRM_STATUSES)
    missing_email = args.missing_email
    if missing_email is None:
        missing_email = True
    return EnrichConfig(
        json_path=args.json_path,
        output_path=args.output_path,
        limit=args.limit,
        min_similarity=args.min_similarity,
        max_queries=args.max_queries,
        retry_all=args.retry_all,
        dry_run=args.dry_run,
        dashboard=args.dashboard,
        from_crm=args.from_crm,
        crm_status=statuses,
        category=args.category,
        has_phone=args.has_phone,
        missing_email=missing_email,
        min_score=args.min_score,
        max_score=args.max_score,
        search=args.search,
        since=args.since,
    )


def main():
    run_enrichment(config_from_args(parse_args()))


if __name__ == "__main__":
    main()
