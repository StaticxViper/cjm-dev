#!/usr/bin/env python3
"""Evidence-based outreach angles for niche leads."""
from __future__ import annotations


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def generate_outreach_angle(lead, niche=None):
    """Short outreach angle from applied signals. Never generic filler."""
    signals = lead.get("lead_signals") or {}
    reviews = _int(lead.get("user_ratings_total"), 0)
    niche_name = (niche or {}).get("display_name") or lead.get("niche") or "this service"
    specialties = lead.get("detected_specialties") or []
    specialty = specialties[0] if specialties else None
    social = lead.get("social") or {}
    has_ig = bool(lead.get("instagram_url"))
    has_fb = bool(lead.get("facebook_url"))
    active = bool(signals.get("active_social") or social.get("appears_active"))
    quality = _int(lead.get("website_quality_score"), 0)

    if signals.get("no_website") and reviews:
        if specialty:
            return (
                f"Strong Google presence ({reviews} reviews) and {specialty} demand, "
                f"but no owned website for local-search customers."
            )
        return (
            f"Strong Google presence ({reviews} reviews) for {niche_name.lower()}, "
            f"but no owned website for local-search customers."
        )
    if signals.get("no_website") and active and has_ig:
        detail = specialty or niche_name.lower()
        return (
            f"Active Instagram proof for {detail}, but no owned website to convert "
            f"social traffic into booked work."
        )
    if signals.get("no_website") and active and has_fb:
        return (
            f"Active Facebook promotion for {niche_name.lower()}, but no dedicated "
            f"site for seller-side or consultation leads."
        )
    if signals.get("website_broken"):
        return (
            f"Google listing is live"
            + (f" with {reviews} reviews" if reviews else "")
            + ", but the listed website is unreachable or unusable."
        )
    if active and (has_ig or has_fb) and quality >= 41:
        detail = specialty or niche_name.lower()
        return (
            f"Strong visual proof on {'Instagram' if has_ig else 'Facebook'} for {detail}, "
            f"but a weak path from social traffic to quote requests."
        )
    if signals.get("no_booking") and signals.get("no_contact_form") and not signals.get("no_website"):
        return (
            f"Site exists for {niche_name.lower()}"
            + (f" ({reviews} reviews)" if reviews else "")
            + ", but there is no booking or contact flow."
        )
    if signals.get("website_mobile_problem") and not signals.get("no_website"):
        return (
            f"Local demand is visible"
            + (f" ({reviews} reviews)" if reviews else "")
            + ", but the website fails basic mobile conversion."
        )
    if signals.get("ads_detected") and (signals.get("no_website") or quality >= 60):
        return (
            f"Paid/local-ad signals are present, but traffic lands on a weak or missing site."
        )
    if signals.get("high_value_service") and (signals.get("no_website") or quality >= 41):
        return (
            f"High-value specialty ({specialty or 'detected'}) with a weak or missing "
            f"owned-web conversion path."
        )
    if reviews:
        return (
            f"{reviews} Google reviews for {niche_name.lower()}, but the digital "
            f"conversion path is weaker than the demand signals."
        )
    return f"Local {niche_name.lower()} listing needs a clearer owned-web conversion path."
