"""Additive new-business score. Standard-mode score_lead is unchanged."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

_DIR = Path(__file__).resolve().parent
DEFAULT_RULES_PATH = _DIR / "new_business_score_rules.json"

VERY_NEW_TYPES = frozenset({"registration_date", "formation_date", "filing_date"})
YEAR_TYPES = VERY_NEW_TYPES | frozenset({"license_date", "opening_date"})
SOFT_TYPES = frozenset({
    "grand_opening",
    "now_open",
    "ribbon_cutting",
    "new_chamber_member",
    "new_license_notice",
    "recently_opened",
    "announcement",
    "soft_signal",
})
BROKEN_ISSUES = frozenset({
    "placeholder_content",
    "domain_or_hosting_error",
    "error",
    "empty",
    "broken",
})
DATE_FIELDS = (
    ("registration_date", "registration_date"),
    ("formation_date", "formation_date"),
    ("filing_date", "filing_date"),
    ("opening_date", "opening_date"),
)


def load_score_rules(path=None):
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    if not rules_path.is_absolute():
        from_cwd = Path.cwd() / rules_path
        beside_module = _DIR / rules_path
        rules_path = from_cwd if from_cwd.is_file() else beside_module
    with open(rules_path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Score rules must be an object: {rules_path}")
    return data


def _points(rules):
    return dict(rules.get("points") or {})


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_iso_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _age_days(value, today):
    parsed = parse_iso_date(value)
    if parsed is None:
        return None
    return (today - parsed).days


def _evidence_items(row):
    items = []
    for field_name, evidence_type in DATE_FIELDS:
        parsed = parse_iso_date(row.get(field_name))
        if parsed is not None:
            items.append({"type": evidence_type, "date": parsed})
    for item in row.get("newness_evidence") or []:
        if not isinstance(item, dict):
            continue
        evidence_type = (item.get("type") or "").strip()
        parsed = parse_iso_date(item.get("date"))
        items.append({"type": evidence_type, "date": parsed})
    return items


def _keyword_keys():
    path = _DIR / "keywords.json"
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        return [str(key).strip().lower() for key in data.keys() if str(key).strip()]
    return []


def _category_match(row, rules):
    haystacks = [
        str(row.get("category") or ""),
        str(row.get("description") or ""),
        str(row.get("business_name") or ""),
    ]
    blob = " ".join(haystacks).lower()
    if not blob.strip():
        return False
    for key in _keyword_keys():
        if key and key in blob:
            return True
    for extra in rules.get("local_categories") or []:
        text = str(extra or "").strip().lower()
        if text and text in blob:
            return True
    return False


def _accepted_email(row):
    email = str(row.get("email") or "").strip()
    if not email or "@" not in email:
        return False
    confidence = str(row.get("email_confidence") or "").strip().lower()
    return confidence in ("high", "medium")


def _valid_phone(row):
    from email_discovery import is_valid_us_phone

    return is_valid_us_phone(row.get("phone") or row.get("phone_google"))


def _has_contact(row):
    if _accepted_email(row) or _valid_phone(row):
        return True
    return bool(str(row.get("contact_form_url") or "").strip())


def _website_bucket(row, rules):
    status = str(row.get("website_status") or "unknown").strip()
    issues = {str(item) for item in (row.get("website_issues") or [])}
    if status == "no_website":
        return "no_website"
    if status == "good_website":
        return "good_website"
    if status != "poor_website":
        return None
    broken = bool(issues & BROKEN_ISSUES) or any(item.startswith("http_") for item in issues)
    if broken:
        return "broken_website"
    try:
        quality = int(row.get("website_quality_score"))
    except (TypeError, ValueError):
        quality = None
    threshold = _int(rules.get("poor_website_min_quality_score"), 41)
    if quality is None or quality >= threshold:
        return "poor_website"
    return "poor_website"


def _clamp(value):
    return max(0, min(100, int(value)))


def score_new_business(row, rules=None, today=None, very_new_days=None, max_age_days=None):
    """Return (new_business_score, score_reasons, score_breakdown).

    Missing or unknown data adds 0. The score is the clamped sum of the breakdown.
    """
    rules = rules or load_score_rules()
    points = _points(rules)
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    very_new = _int(
        very_new_days if very_new_days is not None else rules.get("very_new_days"),
        90,
    )
    max_age = _int(
        max_age_days if max_age_days is not None else rules.get("max_age_days"),
        365,
    )
    established_after = _int(rules.get("established_after_days"), 1095)
    established_reviews = _int(rules.get("established_review_count"), 50)

    breakdown = {}

    best_newness = None
    best_points = 0
    oldest_reliable = None
    defaults = {
        "new_business_registered_90d": 35,
        "new_business_registered": 25,
        "recently_opened_signal": 15,
    }
    for item in _evidence_items(row or {}):
        evidence_type = item["type"]
        age = None if item["date"] is None else (today - item["date"]).days
        if item["date"] is not None and evidence_type in YEAR_TYPES and age is not None and age >= 0:
            if oldest_reliable is None or item["date"] < oldest_reliable:
                oldest_reliable = item["date"]
        candidate = None
        if age is not None and 0 <= age <= very_new and evidence_type in VERY_NEW_TYPES:
            candidate = "new_business_registered_90d"
        elif age is not None and 0 <= age <= max_age and evidence_type in YEAR_TYPES:
            candidate = "new_business_registered"
        elif evidence_type in SOFT_TYPES:
            candidate = "recently_opened_signal"
        if not candidate:
            continue
        candidate_points = _int(points.get(candidate), defaults[candidate])
        if candidate_points > best_points:
            best_newness = candidate
            best_points = candidate_points
    if best_newness:
        breakdown[best_newness] = best_points

    bucket = _website_bucket(row or {}, rules)
    if bucket == "no_website":
        breakdown["no_website"] = _int(points.get("no_website"), 30)
    elif bucket == "broken_website":
        breakdown["broken_website"] = _int(points.get("broken_website"), 25)
    elif bucket == "poor_website":
        breakdown["poor_website"] = _int(points.get("poor_website"), 15)
    elif bucket == "good_website":
        breakdown["good_website"] = _int(points.get("good_website"), -15)

    if _accepted_email(row or {}):
        breakdown["business_email_found"] = _int(points.get("business_email_found"), 15)
    if _valid_phone(row or {}):
        breakdown["public_phone_found"] = _int(points.get("public_phone_found"), 5)
    if _category_match(row or {}, rules):
        breakdown["local_service_category"] = _int(points.get("local_service_category"), 10)

    established = False
    if oldest_reliable is not None and (today - oldest_reliable).days > established_after:
        established = True
    reviews = (row or {}).get("user_ratings_total")
    if reviews not in (None, ""):
        try:
            if int(reviews) >= established_reviews:
                established = True
        except (TypeError, ValueError):
            pass
    if established:
        breakdown["established_business"] = _int(points.get("established_business"), -25)

    require_contact = bool(rules.get("require_contact", True))
    if not _has_contact(row or {}) and not require_contact:
        breakdown["no_contact_info"] = _int(points.get("no_contact_info"), -20)

    reasons = [
        reason for reason, _pts in sorted(
            breakdown.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    score = _clamp(sum(breakdown.values()))
    return score, reasons, breakdown


def contact_drop_reason(row, rules=None):
    """Return no_contact_info when the rules require a contact method and none exists."""
    rules = rules or load_score_rules()
    if bool(rules.get("require_contact", True)) and not _has_contact(row or {}):
        return "no_contact_info"
    return None
