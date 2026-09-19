#!/usr/bin/env python3
"""Configurable additive intent scoring for niche lead search."""
from __future__ import annotations

from datetime import datetime, timezone

from lead_signals import detect_lead_signals
from niche_config import load_score_rules, merge_score_rules


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _entry(key, label, points, applied, evidence=""):
    return {
        "key": key,
        "label": label,
        "points": int(points),
        "applied": bool(applied),
        "evidence": evidence,
    }


def _review_band_min(rules, niche):
    band = (rules.get("positive") or {}).get("review_count_band") or {}
    override = (niche or {}).get("scoring_adjustments", {}).get("review_count_band_min")
    if override is not None:
        return _int(override, band.get("min", 15))
    return _int(band.get("min"), 15)


def website_recently_updated(lead, rules, now=None):
    raw = (lead.get("website_analysis") or {}).get("last_updated") or lead.get("website_last_updated")
    if not raw:
        return False
    months = _int(rules.get("recent_website_update_months"), 12)
    now = now or datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw)[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (now - parsed).days <= months * 30


def apply_competitor_gap(leads, rules):
    """Mark leads whose website is much worse than the batch median."""
    gap = _int(rules.get("competitor_quality_gap"), 20)
    scored = []
    for lead in leads:
        quality = _float(lead.get("website_quality_score"))
        if quality is None:
            continue
        if lead.get("lead_signals", {}).get("no_website"):
            continue
        scored.append(quality)
    if len(scored) < 3:
        return leads
    ordered = sorted(scored)
    median = ordered[len(ordered) // 2]
    for lead in leads:
        quality = _float(lead.get("website_quality_score"))
        if quality is None:
            continue
        if quality >= median + gap:
            lead["competitors_better_websites"] = True
    return leads


def score_intent_lead(lead, niche, rules=None, now=None):
    """Return (score, breakdown). Deterministic for the same inputs."""
    rules = merge_score_rules(rules or load_score_rules(), niche)
    if website_recently_updated(lead, rules, now=now):
        lead["website_recently_updated"] = True
    signals = detect_lead_signals(lead, niche, rules=rules)
    positive = rules.get("positive") or {}
    negative = rules.get("negative") or {}
    reviews = _int(lead.get("user_ratings_total"), 0)
    rating = _float(lead.get("rating"))
    quality = _int(lead.get("website_quality_score"), 0)
    analysis = lead.get("website_analysis") or {}

    breakdown = []

    no_website = signals.get("no_website")
    breakdown.append(_entry(
        "no_website",
        "No website",
        positive.get("no_website", 25),
        no_website,
        "No Google website or URL is social/directory" if no_website else "",
    ))
    broken = signals.get("website_broken") and not no_website
    breakdown.append(_entry(
        "website_broken",
        "Website broken or unusable",
        positive.get("website_broken", 25),
        broken,
        (lead.get("website_status") or "") if broken else "",
    ))
    mobile_problem = signals.get("website_mobile_problem") and not no_website
    breakdown.append(_entry(
        "website_mobile_problem",
        "Mobile / viewport CTA problem",
        positive.get("website_mobile_problem", 15),
        mobile_problem,
    ))
    no_conversion = (
        not no_website
        and not broken
        and signals.get("no_booking")
        and signals.get("no_contact_form")
        and not analysis.get("has_click_to_call")
    )
    breakdown.append(_entry(
        "no_conversion_path",
        "No form, booking, or click-to-call",
        positive.get("no_conversion_path", 15),
        no_conversion,
    ))

    band = positive.get("review_count_band") or {}
    band_min = _review_band_min(rules, niche)
    band_max = _int(band.get("max"), 100)
    in_band = band_min <= reviews <= band_max
    breakdown.append(_entry(
        "review_count_band",
        f"{reviews} Google reviews",
        band.get("points", 12),
        in_band,
        f"{reviews} reviews" if in_band else "",
    ))

    high_rating_cfg = positive.get("high_rating") or {}
    high_rating = (
        rating is not None
        and rating >= _float(high_rating_cfg.get("min_rating"), 4.5)
        and reviews >= _int(high_rating_cfg.get("min_reviews"), 15)
    )
    breakdown.append(_entry(
        "high_rating",
        f"{rating} rating" if rating is not None else "Rating",
        high_rating_cfg.get("points", 8),
        high_rating,
        f"{rating} with {reviews} reviews" if high_rating else "",
    ))

    breakdown.append(_entry(
        "active_social",
        "Active Facebook or Instagram",
        positive.get("active_social", 10),
        signals.get("active_social"),
        (lead.get("social") or {}).get("last_post_date") or "",
    ))
    breakdown.append(_entry(
        "high_value_service",
        "High-value specialty",
        positive.get("high_value_service", 10),
        signals.get("high_value_service"),
        ", ".join(lead.get("detected_specialties") or [])[:80],
    ))
    multi_area = signals.get("mobile_service_area") or signals.get("multiple_service_areas")
    breakdown.append(_entry(
        "mobile_or_multi_area",
        "Mobile or multi-area service",
        positive.get("mobile_or_multi_area", 8),
        multi_area,
        lead.get("service_area") or "",
    ))
    breakdown.append(_entry(
        "recent_business_activity",
        "Recent opening, hire, or new service",
        positive.get("recent_business_activity", 8),
        signals.get("recent_business_activity"),
    ))
    breakdown.append(_entry(
        "competitors_better_websites",
        "Competitors have better websites",
        positive.get("competitors_better_websites", 8),
        signals.get("competitors_better_websites"),
    ))
    ads_weak = bool(
        signals.get("ads_detected")
        and (no_website or broken or quality >= _int(rules.get("website_issue_min_quality"), 60))
    )
    breakdown.append(_entry(
        "ads_to_weak_landing",
        "Ads traffic to a weak landing experience",
        positive.get("ads_to_weak_landing", 20),
        ads_weak,
    ))

    breakdown.append(_entry(
        "franchise",
        "National chain/franchise",
        negative.get("franchise", -25),
        signals.get("franchise"),
        lead.get("business_name") or "",
    ))
    strong = signals.get("strong_website")
    breakdown.append(_entry(
        "strong_website",
        "Strong current website",
        negative.get("strong_website", -30),
        strong,
    ))
    breakdown.append(_entry(
        "recently_updated_website",
        "Website updated in the last 12 months",
        negative.get("recently_updated_website", -20),
        signals.get("recently_updated_website"),
        (lead.get("website_analysis") or {}).get("last_updated") or "",
    ))
    breakdown.append(_entry(
        "weak_demand",
        "Very weak demand signals",
        negative.get("weak_demand", -15),
        signals.get("weak_demand"),
    ))
    breakdown.append(_entry(
        "commodity_service",
        "Commodity service with little differentiation",
        negative.get("commodity_service", -10),
        signals.get("commodity_service"),
    ))

    score = sum(item["points"] for item in breakdown if item["applied"])
    lead["lead_score"] = score
    lead["lead_score_breakdown"] = breakdown
    lead["score_model"] = rules.get("score_model") or "intent_v1"
    lead["key_opportunity"] = key_opportunity(breakdown, signals)
    return score, breakdown


def key_opportunity(breakdown, signals):
    applied = [
        item for item in breakdown
        if item["applied"] and item["points"] > 0
    ]
    applied.sort(key=lambda item: (-item["points"], item["key"]))
    labels = []
    for item in applied[:2]:
        labels.append(item["label"])
    if signals.get("no_website") and "No website" not in labels:
        labels.insert(0, "No website")
    return " + ".join(labels[:2]) if labels else "Review manually"


def format_score_breakdown(lead):
    score = _int(lead.get("lead_score"), 0)
    lines = [f"Lead Score: {score}"]
    negatives = []
    for item in lead.get("lead_score_breakdown") or []:
        points = item.get("points") or 0
        prefix = f"{points:+d}"
        line = f"{prefix} {item.get('label')}"
        if item.get("evidence"):
            line += f" ({item['evidence']})"
        if not item.get("applied"):
            line = f"{prefix} {item.get('label')}".replace(prefix, "-0" if points < 0 else "+0", 1)
            if points < 0:
                negatives.append(line)
            continue
        if points < 0:
            negatives.append(f"{prefix} {item.get('label')}")
        else:
            lines.append(f"{prefix} {item.get('label')}")
    if negatives:
        lines.append("")
        lines.append("Negative Signals")
        lines.extend(negatives)
    return "\n".join(lines)
