#!/usr/bin/env python3
"""Staged website checks for niche lead search.

Stage 2 is a cheap existence/status check. Stage 3 analyzes conversion quality.
Does not invent broken-site claims: a site is broken only after a real request fails
or the URL is unusable (social/directory redirect, empty body).
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
import re

import requests
from bs4 import BeautifulSoup

from email_discovery import DIRECTORY_HOSTS, is_directory_host
from helper_scripts.http.client import html_headers, requests_get
from helper_scripts.web.html_signals import (
    has_title_tag,
    has_viewport,
    is_https_url,
    meta_content,
    text_has_keywords,
    title_text,
)
from helper_scripts.web.urls import normalize_website_url as _normalize_website_url

FETCH_HEADERS = html_headers()

SOCIAL_HOSTS = frozenset({
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "linkedin.com",
})
BOOKING_MARKERS = (
    "calendly.com",
    "acuityscheduling.com",
    "squareup.com/appointments",
    "setmore.com",
    "jobber.com",
    "housecallpro.com",
    "honeybook.com",
    "simplybook.me",
    "mindbodyonline.com",
    "booksy.com",
    "vagaro.com",
)
CMS_MARKERS = (
    ("wp-content", "wordpress"),
    ("wp-includes", "wordpress"),
    ("squarespace.com", "squarespace"),
    ("static1.squarespace", "squarespace"),
    ("wix.com", "wix"),
    ("wixstatic.com", "wix"),
    ("webflow.io", "webflow"),
    ("assets.godaddy.com", "godaddy"),
    ("godaddysites.com", "godaddy"),
    ("shopify.com", "shopify"),
    ("cdn.shopify", "shopify"),
    ("weebly.com", "weebly"),
    ("jimdo.com", "jimdo"),
)
ADS_MARKERS = (
    "gtag('config', 'aw-",
    'gtag("config", "aw-',
    "google_conversion_id",
    "googleadservices.com/pagead/conversion",
    "AW-",
)
PHONE_RE = re.compile(
    r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)
COPYRIGHT_RE = re.compile(r"©\s*(20\d{2})", re.I)
LAST_MODIFIED_FORMATS = (
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S GMT",
)


def normalize_website_url(url):
    return _normalize_website_url(url)


def _host(url):
    try:
        host = urlparse(url if "://" in url else f"https://{url}").hostname or ""
    except Exception:
        return ""
    return host.lower().removeprefix("www.")


def is_social_or_directory_url(url):
    host = _host(url)
    if not host:
        return False
    if any(host == item or host.endswith("." + item) for item in SOCIAL_HOSTS):
        return True
    if any(host == item or host.endswith("." + item) for item in DIRECTORY_HOSTS):
        return True
    return is_directory_host(url)


def website_label(score, has_website=True):
    if not has_website:
        return "None"
    try:
        value = int(score)
    except (TypeError, ValueError):
        return "Unknown"
    if value <= 20:
        return "Excellent"
    if value <= 40:
        return "Good"
    if value <= 60:
        return "Basic"
    if value <= 80:
        return "Poor"
    return "Critical"


def cheap_website_check(url, fetch_fn=None):
    """Stage 2: confirm the URL exists and record status/redirects."""
    result = {
        "url": normalize_website_url(url) if url else "",
        "listed": bool(url and str(url).strip()),
        "http_status": None,
        "https": False,
        "redirect_destination": None,
        "reachable": False,
        "error": None,
        "social_or_directory": False,
        "no_website": False,
        "website_broken": False,
    }
    if not result["url"]:
        result["no_website"] = True
        result["website_status"] = "none"
        return result

    result["social_or_directory"] = is_social_or_directory_url(result["url"])
    if result["social_or_directory"]:
        result["no_website"] = True
        result["website_status"] = "social_or_directory"
        return result

    fetcher = fetch_fn or _fetch_response
    try:
        response = fetcher(result["url"])
    except Exception as exc:
        result["error"] = str(exc)
        result["website_broken"] = True
        result["website_status"] = "error"
        return result

    result["http_status"] = getattr(response, "status_code", None)
    final_url = getattr(response, "url", result["url"]) or result["url"]
    result["redirect_destination"] = final_url if final_url.rstrip("/") != result["url"].rstrip("/") else None
    result["https"] = is_https_url(final_url)
    if is_social_or_directory_url(final_url):
        result["social_or_directory"] = True
        result["no_website"] = True
        result["website_status"] = "redirects_to_social"
        return result

    status = result["http_status"] or 0
    if status >= 400:
        result["website_broken"] = True
        result["website_status"] = f"http_{status}"
        return result

    html = getattr(response, "text", "") or ""
    if len(html.strip()) < 50:
        result["website_broken"] = True
        result["website_status"] = "empty"
        return result

    result["reachable"] = True
    result["website_status"] = "ok"
    result["_html"] = html
    result["_headers"] = dict(getattr(response, "headers", {}) or {})
    result["_final_url"] = final_url
    return result


def _fetch_response(url):
    return requests_get(
        url,
        timeout=10,
        headers=FETCH_HEADERS,
        allow_redirects=True,
        getter=requests.get,
    )


def _meta(soup, name=None, prop=None):
    return meta_content(soup, name=name, prop=prop)


def _detect_cms(html, soup):
    generator = _meta(soup, name="generator").lower()
    haystack = f"{generator} {html[:8000].lower()}"
    for marker, name in CMS_MARKERS:
        if marker in haystack:
            return name
    return None


def _parse_last_modified(headers, html):
    raw = (headers or {}).get("Last-Modified") or (headers or {}).get("last-modified")
    if raw:
        for fmt in LAST_MODIFIED_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                return parsed.date().isoformat()
            except ValueError:
                continue
    match = COPYRIGHT_RE.search(html or "")
    if match:
        return f"{match.group(1)}-01-01"
    return None


def _count_internal_links(soup, base_url):
    host = _host(base_url)
    pages = set()
    for anchor in soup.find_all("a", href=True):
        raw_href = anchor.get("href")
        if isinstance(raw_href, (list, tuple)):
            raw_href = raw_href[0] if raw_href else ""
        raw_href = str(raw_href or "").strip()
        if not raw_href or raw_href.lower().startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        try:
            href = urljoin(base_url or "", raw_href)
            parsed = urlparse(href)
        except ValueError:
            continue
        if _host(href) != host:
            continue
        path = parsed.path or "/"
        if path.startswith(("/cdn-cgi", "/wp-json", "/wp-admin")):
            continue
        pages.add(path.rstrip("/") or "/")
        if len(pages) >= 40:
            break
    return len(pages)


def analyze_website_quality(url, html=None, headers=None, final_url=None, cheap=None):
    """Stage 3: conversion-oriented website analysis. Higher score = worse site."""
    cheap = cheap or cheap_website_check(url) if html is None else dict(cheap or {})
    analysis = {
        "url": cheap.get("url") or normalize_website_url(url),
        "http_status": cheap.get("http_status"),
        "https": bool(cheap.get("https")),
        "redirect_destination": cheap.get("redirect_destination"),
        "reachable": bool(cheap.get("reachable") or html),
        "title": None,
        "meta_description": None,
        "page_count_estimate": None,
        "has_contact_form": False,
        "has_booking": False,
        "has_quote_form": False,
        "has_click_to_call": False,
        "visible_phone": False,
        "service_area_text": None,
        "specialty_pages": False,
        "has_testimonials": False,
        "social_links": {},
        "last_updated": None,
        "cms": None,
        "has_viewport": False,
        "has_mobile_cta": False,
        "ads_detected": False,
        "issues": [],
        "website_quality_score": 0,
        "conversion_quality": "unknown",
    }
    if cheap.get("no_website") or not analysis["url"]:
        analysis["website_quality_score"] = 100
        analysis["issues"] = ["no_website"]
        analysis["conversion_quality"] = "none"
        return analysis
    if cheap.get("website_broken") and html is None:
        analysis["website_quality_score"] = 90
        analysis["issues"] = [cheap.get("website_status") or "broken"]
        analysis["conversion_quality"] = "broken"
        return analysis

    page_html = html if html is not None else cheap.get("_html") or ""
    page_headers = headers if headers is not None else cheap.get("_headers") or {}
    page_url = final_url or cheap.get("_final_url") or analysis["url"]
    soup = BeautifulSoup(page_html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text_lower = text.lower()

    if has_title_tag(soup):
        analysis["title"] = title_text(soup)
    analysis["meta_description"] = _meta(soup, name="description") or None
    analysis["has_viewport"] = has_viewport(soup)
    analysis["cms"] = _detect_cms(page_html, soup)
    analysis["last_updated"] = _parse_last_modified(page_headers, page_html)
    analysis["page_count_estimate"] = _count_internal_links(soup, page_url)
    analysis["visible_phone"] = bool(PHONE_RE.search(text))
    analysis["has_click_to_call"] = any(
        (anchor.get("href") or "").lower().startswith("tel:")
        for anchor in soup.find_all("a", href=True)
    )
    forms = soup.find_all("form")
    form_blob = " ".join(
        f"{form.get('action') or ''} {form.get_text(' ', strip=True)}"
        for form in forms
    ).lower()
    analysis["has_contact_form"] = bool(forms) or "contact form" in text_lower
    analysis["has_quote_form"] = any(
        token in form_blob or token in text_lower
        for token in ("quote", "estimate", "request a consult", "get a quote")
    )
    haystack = page_html.lower()
    analysis["has_booking"] = any(marker in haystack for marker in BOOKING_MARKERS) or any(
        token in text_lower for token in ("book now", "schedule", "book online")
    )
    analysis["has_testimonials"] = any(
        token in text_lower for token in ("testimonial", "what our clients", "google review", "5-star")
    )
    analysis["specialty_pages"] = analysis["page_count_estimate"] >= 4 or any(
        token in text_lower for token in ("our services", "specialt", "service area")
    )
    area_match = re.search(
        r"serv(?:ing|es|ice area)[:\s]([^.!?]{8,80})",
        text,
        re.I,
    )
    if area_match:
        analysis["service_area_text"] = area_match.group(1).strip()
    analysis["has_mobile_cta"] = (
        analysis["has_click_to_call"]
        or analysis["has_booking"]
        or analysis["has_contact_form"]
        or analysis["has_quote_form"]
    )
    analysis["ads_detected"] = any(marker.lower() in haystack for marker in ADS_MARKERS)
    analysis["https"] = is_https_url(page_url) or analysis["https"]

    try:
        from leadenrich_playwright import extract_social_links
        analysis["social_links"] = extract_social_links(page_html, page_url)
    except Exception:
        analysis["social_links"] = {}

    issues = []
    score = 20
    if not analysis["https"]:
        issues.append("insecure")
        score += 15
    if not analysis["has_viewport"]:
        issues.append("no_viewport")
        score += 15
    if not analysis["has_mobile_cta"]:
        issues.append("no_mobile_cta")
        score += 12
    if not analysis["has_contact_form"] and not analysis["has_quote_form"] and not analysis["has_booking"]:
        issues.append("no_conversion_path")
        score += 15
    if not analysis["has_click_to_call"] and not analysis["visible_phone"]:
        issues.append("no_phone_cta")
        score += 8
    if (analysis["page_count_estimate"] or 0) <= 1 and len(page_html) < 4000:
        issues.append("thin_site")
        score += 10
    if not analysis["title"]:
        issues.append("no_title")
        score += 5
    analysis["issues"] = issues
    analysis["website_quality_score"] = max(0, min(100, score))
    if analysis["website_quality_score"] <= 20:
        analysis["conversion_quality"] = "excellent"
    elif analysis["website_quality_score"] <= 40:
        analysis["conversion_quality"] = "good"
    elif analysis["website_quality_score"] <= 60:
        analysis["conversion_quality"] = "outdated"
    elif analysis["website_quality_score"] <= 80:
        analysis["conversion_quality"] = "poor"
    else:
        analysis["conversion_quality"] = "critical"
    return analysis


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
            "https": is_https_url(url),
            "title": "",
            "word_count": 0,
        }

    soup = BeautifulSoup(html, "html.parser")
    issues = []
    recommendations = []
    raw = 0
    url = url or ""
    https = is_https_url(url)

    if not https:
        raw += SEO_WEIGHTS["no_https"]
        issues.append("Site is not served over HTTPS")
        recommendations.append("Enable HTTPS and redirect HTTP traffic")

    if not has_viewport(soup):
        raw += SEO_WEIGHTS["no_viewport"]
        issues.append("Missing mobile viewport meta tag")
        recommendations.append("Add a viewport meta tag for mobile rendering")

    title = title_text(soup) if has_title_tag(soup) else ""
    if not title:
        raw += SEO_WEIGHTS["no_title"]
        issues.append("Missing page title")
        recommendations.append("Add a unique title of about 50-60 characters")
    elif len(title) < MIN_TITLE_LEN or len(title) > MAX_TITLE_LEN:
        raw += SEO_WEIGHTS["title_length"]
        issues.append(f"Title length is {len(title)} characters (aim {MIN_TITLE_LEN}-{MAX_TITLE_LEN})")
        recommendations.append("Rewrite the title to a clear 50-60 character business + city phrase")

    description = _meta(soup, name="description")
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

    canonical = soup.find("link", attrs={"rel": lambda value: value and "canonical" in str(value).lower()})
    if not canonical or not (canonical.get("href") or "").strip():
        raw += SEO_WEIGHTS["no_canonical"]
        issues.append("Missing canonical URL")
        recommendations.append("Add a rel=canonical link to the preferred homepage URL")

    og_title = _meta(soup, prop="og:title")
    og_desc = _meta(soup, prop="og:description")
    if not og_title and not og_desc:
        raw += SEO_WEIGHTS["no_open_graph"]
        issues.append("Missing Open Graph tags")
        recommendations.append("Add og:title, og:description, and og:image for social sharing")

    robots = (_meta(soup, name="robots") or "").lower()
    if "noindex" in robots:
        raw += SEO_WEIGHTS["noindex"]
        issues.append("Robots meta is set to noindex")
        recommendations.append("Remove noindex if the page should appear in Google")

    has_schema = bool(
        soup.find("script", attrs={"type": lambda kind: kind and "ld+json" in kind.lower()})
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
    words = [word for word in re.split(r"\s+", text) if word]
    if len(words) < THIN_CONTENT_WORDS:
        raw += SEO_WEIGHTS["thin_content"]
        issues.append(f"Thin content ({len(words)} words)")
        recommendations.append("Add service pages and a clear description of what the business does")

    if not text_has_keywords(text, CTA_KEYWORDS):
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


def apply_website_fields(lead, cheap, deep=None):
    """Write website analysis fields onto a lead row."""
    lead["website_status"] = cheap.get("website_status")
    lead["website"] = lead.get("website") or cheap.get("url") or ""
    if cheap.get("no_website"):
        lead["website_quality_score"] = 100
        lead["website_issues"] = ["no_website"]
    elif cheap.get("website_broken") and not deep:
        lead["website_quality_score"] = 90
        lead["website_issues"] = [cheap.get("website_status") or "broken"]
    if deep:
        lead["website_quality_score"] = deep.get("website_quality_score")
        lead["website_issues"] = list(deep.get("issues") or [])
        lead["website_analysis"] = {
            "title": deep.get("title"),
            "meta_description": deep.get("meta_description"),
            "http_status": deep.get("http_status"),
            "https": deep.get("https"),
            "redirect_destination": deep.get("redirect_destination"),
            "page_count_estimate": deep.get("page_count_estimate"),
            "has_contact_form": deep.get("has_contact_form"),
            "has_booking": deep.get("has_booking"),
            "has_quote_form": deep.get("has_quote_form"),
            "has_click_to_call": deep.get("has_click_to_call"),
            "visible_phone": deep.get("visible_phone"),
            "service_area": deep.get("service_area_text"),
            "specialty_pages": deep.get("specialty_pages"),
            "has_testimonials": deep.get("has_testimonials"),
            "cms": deep.get("cms"),
            "last_updated": deep.get("last_updated"),
            "ads_detected": deep.get("ads_detected"),
            "conversion_quality": deep.get("conversion_quality"),
        }
        if deep.get("service_area_text") and not lead.get("service_area"):
            lead["service_area"] = deep["service_area_text"]
        social = deep.get("social_links") or {}
        if social.get("facebook") and not lead.get("facebook_url"):
            lead["facebook_url"] = social["facebook"]
        if social.get("instagram") and not lead.get("instagram_url"):
            lead["instagram_url"] = social["instagram"]
        extras = {
            key: value
            for key, value in social.items()
            if key not in ("facebook", "instagram")
        }
        if extras:
            lead["other_social_urls"] = extras
    return lead
