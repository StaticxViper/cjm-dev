#!/usr/bin/env python3
"""Filter, sort, display, and CSV-export niche search results."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from email_discovery import lead_has_valid_email, lead_has_valid_phone
from intent_scoring import format_score_breakdown
from niche_config import load_score_rules
from website_quality import website_label

SORT_KEYS = {
    "score": lambda row: int(row.get("lead_score") or 0),
    "reviews": lambda row: int(row.get("user_ratings_total") or 0),
    "rating": lambda row: float(row.get("rating") or 0),
    "website_quality": lambda row: int(row.get("website_quality_score") or 0),
    "social": lambda row: int(row.get("social_activity_score") or 0),
    "date": lambda row: str(row.get("date_discovered") or ""),
}

CSV_COLUMNS = (
    "business_name",
    "niche",
    "location",
    "phone",
    "email",
    "website",
    "google_maps",
    "rating",
    "reviews",
    "lead_score",
    "website_quality",
    "social_urls",
    "key_lead_signals",
    "outreach_angle",
)


def load_leads(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _signals(row):
    return row.get("lead_signals") or {}


def _quality(row):
    try:
        return int(row.get("website_quality_score"))
    except (TypeError, ValueError):
        return None


def location_label(row):
    city = row.get("city")
    state = row.get("state")
    if city and state:
        return f"{city}, {state}"
    return row.get("location_searched") or row.get("address") or ""


def social_label(row):
    social = row.get("social") or {}
    if social.get("appears_active") or _signals(row).get("active_social"):
        return "Active"
    if row.get("facebook_url") or row.get("instagram_url"):
        return "Found"
    return "None"


def apply_filters(rows, filters=None, rules=None):
    """Filter rows in Python (JSON is the backing store)."""
    filters = filters or {}
    rules = rules or load_score_rules()
    strong_max = int(rules.get("exclude_strong_website_max_quality") or 40)
    issue_min = int(rules.get("website_issue_min_quality") or 60)
    out = []
    for row in rows:
        signals = _signals(row)
        quality = _quality(row)
        reviews = int(row.get("user_ratings_total") or 0)
        try:
            rating = float(row.get("rating"))
        except (TypeError, ValueError):
            rating = None
        score = int(row.get("lead_score") or 0)
        if filters.get("min_score") is not None and score < int(filters["min_score"]):
            continue
        if filters.get("max_score") is not None and score > int(filters["max_score"]):
            continue
        if filters.get("min_reviews") is not None and reviews < int(filters["min_reviews"]):
            continue
        if filters.get("min_rating") is not None and (rating is None or rating < float(filters["min_rating"])):
            continue
        if filters.get("min_website_quality") is not None and (
            quality is None or quality < int(filters["min_website_quality"])
        ):
            continue
        if filters.get("max_website_quality") is not None and (
            quality is None or quality > int(filters["max_website_quality"])
        ):
            continue
        if filters.get("no_website") and not signals.get("no_website"):
            continue
        if filters.get("has_website") and signals.get("no_website"):
            continue
        if filters.get("weak_or_no_website"):
            if not signals.get("no_website") and (quality is None or quality <= strong_max):
                continue
        if filters.get("active_social") and not (
            signals.get("active_social") or (row.get("social") or {}).get("appears_active")
        ):
            continue
        if filters.get("facebook") and not row.get("facebook_url"):
            continue
        if filters.get("instagram") and not row.get("instagram_url"):
            continue
        if filters.get("require_phone") and not lead_has_valid_phone(row):
            continue
        if filters.get("require_email") and not lead_has_valid_email(row):
            continue
        if filters.get("high_value_specialty") and not signals.get("high_value_service"):
            continue
        if filters.get("franchise") is True and not signals.get("franchise"):
            continue
        if filters.get("franchise") is False and signals.get("franchise"):
            continue
        if filters.get("exclude_strong_websites") and quality is not None and quality <= strong_max and not signals.get("no_website"):
            continue
        if filters.get("require_active_business"):
            if row.get("business_status") in ("CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"):
                continue
        if filters.get("service_area"):
            needle = str(filters["service_area"]).lower()
            hay = f"{row.get('service_area') or ''} {location_label(row)}".lower()
            if needle not in hay:
                continue
        if filters.get("outreach_status") and (row.get("outreach_status") or "new") != filters["outreach_status"]:
            continue
        if filters.get("website_issue") and (signals.get("no_website") or quality is None or quality < issue_min):
            continue
        out.append(row)
    return out


def apply_preset(rows, preset_id, rules=None):
    rules = rules or load_score_rules()
    preset = (rules.get("result_presets") or {}).get(preset_id)
    if not preset:
        raise ValueError(f"Unknown preset: {preset_id}")
    return apply_filters(rows, preset.get("filters") or {}, rules=rules)


def sort_leads(rows, key="score", reverse=True):
    fn = SORT_KEYS.get(key) or SORT_KEYS["score"]
    return sorted(rows, key=fn, reverse=reverse)


def format_results_table(rows, limit=25):
    lines = [
        f"{'#':>3} {'Score':>5}  {'Business':<28} {'Rev':>4} {'Rat':>4}  {'Web':<8} {'Social':<7} {'Opportunity'}"
    ]
    lines.append("-" * 110)
    for index, row in enumerate(rows[:limit], start=1):
        name = (row.get("business_name") or "")[:28]
        reviews = int(row.get("user_ratings_total") or 0)
        rating = row.get("rating")
        rating_s = f"{float(rating):.1f}" if rating not in (None, "") else "-"
        web = website_label(row.get("website_quality_score"), not (row.get("lead_signals") or {}).get("no_website"))
        opportunity = (row.get("key_opportunity") or "")[:36]
        lines.append(
            f"{index:>3} {int(row.get('lead_score') or 0):>5}  {name:<28} {reviews:>4} {rating_s:>4}  "
            f"{web:<8} {social_label(row):<7} {opportunity}"
        )
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more")
    return "\n".join(lines)


def format_lead_profile(row):
    analysis = row.get("website_analysis") or {}
    social = row.get("social") or {}
    signals = _signals(row)
    true_signals = [key for key, value in signals.items() if value]
    lines = [
        f"{row.get('business_name')}",
        f"Niche: {row.get('niche')}",
        f"Location: {location_label(row)}",
        f"Address: {row.get('address')}",
        f"Phone: {row.get('phone_google') or row.get('phone_website') or ''}",
        f"Email: {row.get('email') or ''}",
        f"Website: {row.get('website') or 'None'}",
        f"Google Maps: {row.get('profile_url') or ''}",
        f"Rating: {row.get('rating')}  Reviews: {row.get('user_ratings_total')}",
        "",
        "Website analysis",
        f"  Quality: {row.get('website_quality_score')} ({website_label(row.get('website_quality_score'), not signals.get('no_website'))})",
        f"  Status: {row.get('website_status')}",
        f"  Issues: {', '.join(row.get('website_issues') or []) or 'none'}",
        f"  HTTPS: {analysis.get('https')}  Booking: {analysis.get('has_booking')}  Form: {analysis.get('has_contact_form')}",
        "",
        "Social",
        f"  Facebook: {row.get('facebook_url') or ''}",
        f"  Instagram: {row.get('instagram_url') or ''}",
        f"  Active: {social.get('appears_active')}  Last post: {social.get('last_post_date')}",
        f"  Social score: {row.get('social_activity_score')}",
        "",
        format_score_breakdown(row),
        "",
        f"Signals: {', '.join(true_signals) or 'none'}",
        f"Opportunity: {row.get('key_opportunity') or ''}",
        f"Outreach angle: {row.get('outreach_angle') or ''}",
        f"Outreach status: {row.get('outreach_status') or 'new'}",
        f"Tags: {', '.join(row.get('tags') or [])}",
        f"Notes: {row.get('notes') or ''}",
    ]
    return "\n".join(lines)


def export_csv(rows, path):
    output = Path(path)
    with open(output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            signals = _signals(row)
            socials = [value for value in (row.get("facebook_url"), row.get("instagram_url")) if value]
            extras = row.get("other_social_urls") or {}
            if isinstance(extras, dict):
                socials.extend(str(value) for value in extras.values() if value)
            writer.writerow({
                "business_name": row.get("business_name") or "",
                "niche": row.get("niche") or "",
                "location": location_label(row),
                "phone": row.get("phone_google") or row.get("phone_website") or "",
                "email": row.get("email") or "",
                "website": row.get("website") or "",
                "google_maps": row.get("profile_url") or "",
                "rating": row.get("rating") if row.get("rating") is not None else "",
                "reviews": row.get("user_ratings_total") if row.get("user_ratings_total") is not None else "",
                "lead_score": row.get("lead_score") if row.get("lead_score") is not None else "",
                "website_quality": row.get("website_quality_score") if row.get("website_quality_score") is not None else "",
                "social_urls": "; ".join(socials),
                "key_lead_signals": "; ".join(key for key, value in signals.items() if value),
                "outreach_angle": row.get("outreach_angle") or "",
            })
    return str(output)


def review_leads(rows=None, json_path="niche_leads_output.json"):
    """Interactive results reviewer."""
    rules = load_score_rules()
    if rows is None:
        if not Path(json_path).exists():
            print(f"No results file at {json_path}")
            return
        rows = load_leads(json_path)
    working = list(rows)
    sort_key = "score"
    filters = {}
    while True:
        visible = sort_leads(apply_filters(working, filters, rules=rules), key=sort_key)
        print(f"\n{len(visible)} qualified leads found\n")
        print(format_results_table(visible))
        print()
        print("s) Sort  f) Filter  p) Preset  v) View  e) Export CSV  c) Clear filters  q) Back")
        choice = input("Select: ").strip().lower() or "q"
        if choice in ("q", "b"):
            return visible
        if choice == "s":
            raw = input("Sort by score/reviews/rating/website_quality/social/date [score]: ").strip() or "score"
            if raw in SORT_KEYS:
                sort_key = raw
            continue
        if choice == "f":
            filters.update(_prompt_filters(filters))
            continue
        if choice == "p":
            presets = list((rules.get("result_presets") or {}).items())
            for index, (key, preset) in enumerate(presets, start=1):
                print(f" {index}) {preset.get('label') or key}")
            raw = input("Preset number: ").strip()
            try:
                _key, preset = presets[int(raw) - 1]
                filters = dict(preset.get("filters") or {})
            except (ValueError, IndexError):
                print("Invalid preset.")
            continue
        if choice == "c":
            filters = {}
            continue
        if choice == "e":
            path = input("CSV path [niche_leads.csv]: ").strip() or "niche_leads.csv"
            export_csv(visible, path)
            print(f"Wrote {path}")
            continue
        if choice == "v":
            raw = input("Lead number: ").strip()
            try:
                lead = visible[int(raw) - 1]
            except (ValueError, IndexError):
                print("Invalid lead number.")
                continue
            print()
            print(format_lead_profile(lead))
            input("\nEnter to return to table: ")
            continue
        print("Unknown command.")


def _prompt_filters(current):
    updated = dict(current)
    raw = input("min score (blank=keep): ").strip()
    if raw:
        updated["min_score"] = int(raw)
    raw = input("min reviews (blank=keep): ").strip()
    if raw:
        updated["min_reviews"] = int(raw)
    raw = input("min rating (blank=keep): ").strip()
    if raw:
        updated["min_rating"] = float(raw)
    flag = input("no website only? [y/N]: ").strip().lower()
    if flag == "y":
        updated["no_website"] = True
    flag = input("active social only? [y/N]: ").strip().lower()
    if flag == "y":
        updated["active_social"] = True
    flag = input("phone required? [y/N]: ").strip().lower()
    if flag == "y":
        updated["require_phone"] = True
    flag = input("email required? [y/N]: ").strip().lower()
    if flag == "y":
        updated["require_email"] = True
    return updated
