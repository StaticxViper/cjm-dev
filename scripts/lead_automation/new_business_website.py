"""Website status for new-business leads, built on website_quality.py."""
from __future__ import annotations

from datetime import date, datetime

from website_quality import (
    COPYRIGHT_RE,
    analyze_website_quality,
    cheap_website_check,
    is_social_or_directory_url,
    website_label,
)

PLACEHOLDER_MARKERS = (
    "lorem ipsum",
    "coming soon",
    "under construction",
    "this domain is for sale",
    "domain is for sale",
    "this domain is parked",
    "buy this domain",
    "parked domain",
    "website coming soon",
    "start your new website today",
    "this is a placeholder",
    "godaddy website builder",
    "create your website for free",
)
HOSTING_ERROR_MARKERS = (
    "getaddrinfo",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "certificate",
    "tls",
    "ssl",
    "expired",
    "hostname",
)
BROKEN_STATUSES = frozenset({"error", "empty"})


def _year_from_copyright(html):
    match = COPYRIGHT_RE.search(html or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _is_placeholder(html):
    text = (html or "").lower()
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


def _is_hosting_error(message):
    text = (message or "").lower()
    return any(marker in text for marker in HOSTING_ERROR_MARKERS)


def _quality_band(score, threshold):
    label = website_label(score, has_website=True)
    if label in ("Excellent", "Good") and score <= 40:
        return "good_website"
    if score >= threshold or label in ("Basic", "Poor", "Critical"):
        return "poor_website"
    return "poor_website" if score >= threshold else "good_website"


def classify_website(
    *,
    url="",
    search_ran=False,
    search_blocked=False,
    check_mode="deep",
    cheap=None,
    deep=None,
    html=None,
    fetch_fn=None,
    today=None,
    poor_website_min_quality_score=41,
):
    """Return website_status, website_issues, and website_quality_score.

    A missing URL is unknown until a website search has actually run.
    check_mode none always yields unknown.
    """
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    mode = (check_mode or "deep").strip().lower()
    issues = []
    if mode == "none" or search_blocked or not search_ran:
        return {
            "website": url or "",
            "website_status": "unknown",
            "website_issues": [],
            "website_quality_score": None,
            "contact_form_url": None,
        }

    website = (url or "").strip()
    if not website:
        return {
            "website": "",
            "website_status": "no_website",
            "website_issues": [],
            "website_quality_score": 100,
            "contact_form_url": None,
        }

    if is_social_or_directory_url(website):
        return {
            "website": website,
            "website_status": "no_website",
            "website_issues": ["social_only"],
            "website_quality_score": 100,
            "contact_form_url": None,
        }

    cheap_result = cheap if cheap is not None else cheap_website_check(website, fetch_fn=fetch_fn)
    status = cheap_result.get("website_status") or ""
    if status in ("none", "social_or_directory", "redirects_to_social") or cheap_result.get("no_website"):
        social = status in ("social_or_directory", "redirects_to_social") or cheap_result.get("social_or_directory")
        return {
            "website": website,
            "website_status": "no_website",
            "website_issues": ["social_only"] if social else [],
            "website_quality_score": 100,
            "contact_form_url": None,
        }

    page_html = html if html is not None else cheap_result.get("_html") or ""
    error_text = cheap_result.get("error") or ""
    hosting = _is_hosting_error(error_text)
    if hosting:
        issues.append("domain_or_hosting_error")
    if status == "error" and not hosting:
        issues.append("error")
    if status == "empty":
        issues.append("empty")
    if str(status).startswith("http_"):
        issues.append(status)

    broken = bool(cheap_result.get("website_broken")) or status in BROKEN_STATUSES or str(status).startswith("http_") or hosting
    placeholder = _is_placeholder(page_html)
    if placeholder:
        issues.append("placeholder_content")

    if mode == "cheap" and not broken and not placeholder:
        return {
            "website": cheap_result.get("url") or website,
            "website_status": "website_found",
            "website_issues": issues,
            "website_quality_score": None,
            "contact_form_url": None,
        }

    if broken or placeholder:
        if placeholder and "placeholder_content" not in issues:
            issues.append("placeholder_content")
        return {
            "website": cheap_result.get("url") or website,
            "website_status": "poor_website",
            "website_issues": issues,
            "website_quality_score": 90,
            "contact_form_url": None,
        }

    analysis = deep if deep is not None else analyze_website_quality(
        website,
        html=page_html or None,
        headers=cheap_result.get("_headers"),
        final_url=cheap_result.get("_final_url"),
        cheap=cheap_result,
    )
    for issue in analysis.get("issues") or []:
        if issue not in issues:
            issues.append(issue)
    if not analysis.get("visible_phone") and not analysis.get("has_contact_form"):
        if "missing_contact_info" not in issues:
            issues.append("missing_contact_info")
    copyright_year = _year_from_copyright(page_html)
    last_updated = analysis.get("last_updated")
    outdated = False
    if copyright_year is not None and copyright_year <= today.year - 3:
        outdated = True
    if last_updated:
        try:
            updated_year = int(str(last_updated)[:4])
            if updated_year <= today.year - 3:
                outdated = True
        except ValueError:
            pass
    if outdated and "outdated_copyright" not in issues:
        issues.append("outdated_copyright")
    if placeholder and "placeholder_content" not in issues:
        issues.append("placeholder_content")

    try:
        score = int(analysis.get("website_quality_score"))
    except (TypeError, ValueError):
        score = 0
    if placeholder or "placeholder_content" in issues:
        score = max(score, 90)
    threshold = int(poor_website_min_quality_score or 41)
    if "placeholder_content" in issues or "domain_or_hosting_error" in issues:
        band = "poor_website"
        score = max(score, 90)
    else:
        band = "good_website" if score <= 40 else "poor_website"
        if score >= threshold:
            band = "poor_website"
        elif score <= 40:
            band = "good_website"
    contact_form = None
    if analysis.get("has_contact_form"):
        contact_form = analysis.get("url") or website
    return {
        "website": analysis.get("url") or website,
        "website_status": band,
        "website_issues": issues,
        "website_quality_score": score,
        "contact_form_url": contact_form,
        "https": analysis.get("https"),
        "has_viewport": analysis.get("has_viewport"),
        "html_length": len(page_html or ""),
        "has_cta": "no_conversion_path" not in issues,
    }
