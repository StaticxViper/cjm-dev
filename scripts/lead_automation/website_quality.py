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

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

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
    if not url:
        return ""
    text = str(url).strip()
    if text.startswith("//"):
        text = "https:" + text
    parsed = urlparse(text)
    if not parsed.scheme:
        text = "https://" + text
    return text


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
    result["https"] = str(final_url).lower().startswith("https://")
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
    return requests.get(
        url,
        timeout=10,
        headers=FETCH_HEADERS,
        allow_redirects=True,
    )


def _meta(soup, name=None, prop=None):
    if name:
        tag = soup.find("meta", attrs={"name": lambda value: value and str(value).lower() == name.lower()})
    elif prop:
        tag = soup.find("meta", attrs={"property": lambda value: value and str(value).lower() == prop.lower()})
    else:
        return ""
    if not tag:
        return ""
    return (tag.get("content") or "").strip()


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
        href = urljoin(base_url, anchor.get("href") or "")
        parsed = urlparse(href)
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

    if soup.title and soup.title.string:
        analysis["title"] = soup.title.string.strip()
    analysis["meta_description"] = _meta(soup, name="description") or None
    analysis["has_viewport"] = bool(
        soup.find("meta", attrs={"name": lambda value: value and value.lower() == "viewport"})
    )
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
    analysis["https"] = str(page_url).lower().startswith("https://") or analysis["https"]

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
