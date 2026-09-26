#!/usr/bin/env python3
"""Data-driven lead signal detection for niche search."""
from __future__ import annotations

from email_discovery import lead_has_valid_email, lead_has_valid_phone


RECENT_ACTIVITY_TERMS = (
    "grand opening",
    "now open",
    "now hiring",
    "we are hiring",
    "second location",
    "new location",
    "rebrand",
    "under new ownership",
    "new service",
    "now offering",
)
MOBILE_AREA_TERMS = (
    "mobile",
    "we come to you",
    "traveling",
    "on-site",
    "on site",
    "house call",
    "in-home",
    "in home",
)
MULTI_AREA_TERMS = (
    "counties",
    "multiple cities",
    "tri-state",
    "tristate",
    "serving",
    "service area",
)


def _haystacks(lead):
    analysis = lead.get("website_analysis") or {}
    extras = lead.get("other_social_urls") or {}
    return {
        "name": lead.get("business_name") or "",
        "text": " ".join(
            str(part)
            for part in (
                lead.get("business_name"),
                lead.get("detected_specialties"),
                lead.get("service_area"),
                lead.get("search_term"),
                analysis.get("title"),
                analysis.get("meta_description"),
                analysis.get("service_area"),
                " ".join(lead.get("website_issues") or []),
            )
            if part
        ),
        "service_area": lead.get("service_area") or analysis.get("service_area") or "",
        "website": lead.get("website") or "",
        "facebook": lead.get("facebook_url") or extras.get("facebook") or "",
        "instagram": lead.get("instagram_url") or extras.get("instagram") or "",
    }


def _contains(haystack, keywords):
    blob = (haystack or "").lower()
    for term in keywords or []:
        needle = str(term or "").strip().lower()
        if needle and needle in blob:
            return True
    return False


def detect_niche_signal_hits(lead, niche):
    """Apply configured niche detectors against observed text fields."""
    fields = _haystacks(lead)
    hits = []
    specialties = []
    for signal in niche.get("lead_signals") or []:
        matched = False
        for field_name in signal.get("fields") or []:
            if _contains(fields.get(field_name, ""), signal.get("keywords")):
                matched = True
                break
        if matched:
            hits.append(signal["id"])
            specialties.extend(signal.get("keywords") or [])
    return hits, _unique(specialties)


def _unique(values):
    seen = set()
    out = []
    for value in values:
        key = str(value).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _review_count(lead):
    try:
        return int(lead.get("user_ratings_total") or 0)
    except (TypeError, ValueError):
        return 0


def _rating(lead):
    try:
        return float(lead.get("rating"))
    except (TypeError, ValueError):
        return None


def _quality(lead):
    try:
        return int(lead.get("website_quality_score"))
    except (TypeError, ValueError):
        return None


def detect_lead_signals(lead, niche, rules=None):
    """Return structured signals from observed lead fields + niche config."""
    analysis = lead.get("website_analysis") or {}
    social = lead.get("social") or {}
    hits, specialties = detect_niche_signal_hits(lead, niche)
    high_value_terms = niche.get("high_value_service_keywords") or []
    blob = " ".join(_haystacks(lead).values()).lower()
    high_value = any(str(term).lower() in blob for term in high_value_terms) or bool(hits)
    website = (lead.get("website") or "").strip()
    no_website = bool(
        lead.get("website_status") in ("none", "social_or_directory", "redirects_to_social")
        or "no_website" in (lead.get("website_issues") or [])
        or not website
    )
    broken = "broken" in (lead.get("website_issues") or []) or bool(
        lead.get("website_status") in ("error", "empty")
        or str(lead.get("website_status") or "").startswith("http_")
    )
    if no_website:
        broken = False
    quality = _quality(lead)
    issues = set(lead.get("website_issues") or [])
    mobile_problem = "no_viewport" in issues or "no_mobile_cta" in issues
    no_booking = not bool(analysis.get("has_booking"))
    no_contact = not bool(analysis.get("has_contact_form") or analysis.get("has_quote_form"))
    if no_website or (quality is None and not analysis):
        no_booking = True
        no_contact = True
    active_social = bool(social.get("appears_active") or lead.get("social", {}).get("appears_active"))
    reviews = _review_count(lead)
    rating = _rating(lead)
    suggested_reviews = int(niche.get("suggested_min_reviews") or 15)
    high_reviews = reviews >= suggested_reviews
    high_rating = rating is not None and rating >= float(niche.get("suggested_min_rating") or 4.5)
    area_text = (lead.get("service_area") or analysis.get("service_area") or blob)
    mobile_area = _contains(area_text, MOBILE_AREA_TERMS) or "mobile" in (
        niche.get("service_area_characteristics") or []
    ) and _contains(lead.get("business_name"), ("mobile", "traveling"))
    multi_area = _contains(area_text, MULTI_AREA_TERMS)
    recent = _contains(blob, RECENT_ACTIVITY_TERMS)
    franchise = bool(lead.get("is_franchise"))
    signals = {
        "no_website": no_website,
        "website_broken": broken,
        "website_mobile_problem": bool(mobile_problem),
        "no_booking": bool(no_booking),
        "no_contact_form": bool(no_contact),
        "active_social": bool(active_social),
        "high_review_count": bool(high_reviews),
        "high_rating": bool(high_rating),
        "high_value_service": bool(high_value),
        "mobile_service_area": bool(mobile_area),
        "multiple_service_areas": bool(multi_area),
        "franchise": franchise,
        "recent_business_activity": bool(recent),
        "has_phone": bool(lead_has_valid_phone(lead)),
        "has_email": bool(lead_has_valid_email(lead)),
        "ads_detected": bool(analysis.get("ads_detected")),
        "strong_website": bool(
            website
            and not no_website
            and quality is not None
            and quality <= int((rules or {}).get("strong_website_max_quality") or 20)
            and analysis.get("has_booking")
            and analysis.get("has_viewport")
            and analysis.get("specialty_pages")
        ),
        "recently_updated_website": bool(lead.get("website_recently_updated")),
        "weak_demand": bool(
            reviews <= 0
            and not active_social
            and (lead.get("business_status") not in (None, "", "OPERATIONAL"))
        ) or bool(reviews <= 0 and not active_social and not lead.get("business_status")),
        "commodity_service": bool(not high_value),
        "competitors_better_websites": bool(lead.get("competitors_better_websites")),
    }
    for hit in hits:
        signals[hit] = True
    lead["detected_specialties"] = specialties
    lead["lead_signals"] = signals
    return signals
