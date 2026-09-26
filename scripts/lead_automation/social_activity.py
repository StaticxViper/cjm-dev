#!/usr/bin/env python3
"""Social activity classification for niche lead search.

A profile is marked active only when a real post date was retrieved and falls
within the configured window. A Facebook/Instagram URL alone is not activity.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from niche_config import load_score_rules


def _parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _days_between(later, earlier):
    return max(0, (later - earlier).total_seconds() / 86400.0)


def classify_social_activity(lead, posts=None, now=None, rules=None):
    """Return social fields and score from URLs plus optional retrieved posts."""
    rules = rules or load_score_rules()
    window = int(rules.get("active_social_days") or 30)
    now = now or datetime.now(timezone.utc)
    facebook_url = (lead.get("facebook_url") or "").strip() or None
    instagram_url = (lead.get("instagram_url") or "").strip() or None
    other = lead.get("other_social_urls") or {}
    retrieved = list(posts or lead.get("social_posts") or [])

    dated = []
    for item in retrieved:
        parsed = _parse_date((item or {}).get("date") or (item or {}).get("timestamp"))
        if parsed is None:
            continue
        dated.append({
            "date": parsed,
            "platform": (item or {}).get("platform"),
            "followers": (item or {}).get("followers"),
        })
    dated.sort(key=lambda item: item["date"], reverse=True)
    last_post = dated[0]["date"] if dated else None
    last_post_iso = last_post.date().isoformat() if last_post else None
    appears_active = bool(last_post and (now - last_post) <= timedelta(days=window))

    frequency = None
    if len(dated) >= 2:
        span_days = _days_between(dated[0]["date"], dated[-1]["date"]) or 1
        posts_per_week = (len(dated) / span_days) * 7
        frequency = round(posts_per_week, 2)

    followers = None
    for item in dated:
        if item.get("followers"):
            followers = item["followers"]
            break
    if followers is None:
        followers = lead.get("social_followers")

    score = 0
    if appears_active:
        score = 80
        if facebook_url and instagram_url:
            score = 100
        elif frequency and frequency >= 1:
            score = 90
    elif last_post:
        score = 35
    elif facebook_url or instagram_url:
        score = 15

    return {
        "facebook_url": facebook_url,
        "instagram_url": instagram_url,
        "other_social_urls": other or None,
        "last_post_date": last_post_iso,
        "posting_frequency": frequency,
        "appears_active": appears_active,
        "follower_count": followers,
        "recent_content": bool(dated),
        "social_activity_score": score,
        "active_social": appears_active,
    }


def apply_social_fields(lead, classification):
    lead["facebook_url"] = classification.get("facebook_url")
    lead["instagram_url"] = classification.get("instagram_url")
    if classification.get("other_social_urls"):
        lead["other_social_urls"] = classification["other_social_urls"]
    lead["social_activity_score"] = classification.get("social_activity_score") or 0
    lead["social"] = {
        "last_post_date": classification.get("last_post_date"),
        "posting_frequency": classification.get("posting_frequency"),
        "appears_active": bool(classification.get("appears_active")),
        "follower_count": classification.get("follower_count"),
        "recent_content": bool(classification.get("recent_content")),
    }
    return lead
