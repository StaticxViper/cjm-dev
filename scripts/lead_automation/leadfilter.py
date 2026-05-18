"""
lead_filter.py

Persistent duplicate filtering for lead generation and pipeline ingest.
"""
import csv
import os
import re
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple

_lock = Lock()

SCORE_THRESHOLD = 60

_JUNK_EMAIL_FRAGMENTS = ("sentry", "wixpress")


def load_existing_place_ids(csv_path: str) -> set:
    """
    Load existing place_ids from CSV if it exists.
    Returns a set of place_ids.
    """
    if not os.path.exists(csv_path):
        return set()

    existing = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "place_id" in row:
                existing.add(row["place_id"])

    return existing


def is_new_place(place_id: str, existing_ids: set) -> bool:
    """
    Thread-safe check and insert.
    Returns True if place_id was not seen before.
    """
    with _lock:
        if place_id in existing_ids:
            return False
        existing_ids.add(place_id)
        return True


def extract_real_email(raw_email_field: Optional[str]) -> str:
    """First usable email from a semicolon-separated field."""
    if not raw_email_field:
        return ""
    for part in raw_email_field.split(";"):
        email = part.strip().lower()
        if not email:
            continue
        if any(fragment in email for fragment in _JUNK_EMAIL_FRAGMENTS):
            continue
        return email
    return ""


def normalize_email(raw: Optional[str]) -> Optional[str]:
    email = extract_real_email(raw) if raw and ";" in raw else (raw or "").strip().lower()
    if not email:
        return None
    if any(fragment in email for fragment in _JUNK_EMAIL_FRAGMENTS):
        return None
    if "@" not in email:
        return None
    return email


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return digits


def _phones_from_row(row: dict) -> List[str]:
    phones = []
    for key in ("phone_google", "phone_website", "phone"):
        normalized = normalize_phone(row.get(key))
        if normalized:
            phones.append(normalized)
    return phones


def _email_from_row(row: dict) -> Optional[str]:
    return normalize_email(row.get("email"))


def _contact_from_lead(lead: dict) -> Tuple[Optional[str], List[str]]:
    email = normalize_email(lead.get("email"))
    phones = []
    for key in ("phone", "phone_google", "phone_website"):
        normalized = normalize_phone(lead.get(key))
        if normalized:
            phones.append(normalized)
    return email, phones


def _build_existing_indexes(existing_leads: List[dict]) -> Tuple[Set[str], Set[str]]:
    emails: Set[str] = set()
    phones: Set[str] = set()
    for lead in existing_leads:
        email, lead_phones = _contact_from_lead(lead)
        if email:
            emails.add(email)
        phones.update(lead_phones)
    return emails, phones


def filter_by_score(rows: List[dict], threshold: int = SCORE_THRESHOLD) -> List[dict]:
    """Keep rows with lead_score >= threshold."""
    filtered = []
    for row in rows:
        try:
            score = int(row.get("lead_score", 0))
        except (TypeError, ValueError):
            continue
        if score >= threshold:
            filtered.append(row)
    return filtered


def dedupe_against_existing(
    csv_rows: List[dict], existing_leads: List[dict]
) -> Tuple[List[dict], int]:
    """
    Drop CSV rows whose email or phone already exists in API leads.
    Returns (new_rows, skipped_count).
    """
    existing_emails, existing_phones = _build_existing_indexes(existing_leads)
    new_rows: List[dict] = []
    skipped = 0

    for row in csv_rows:
        email = _email_from_row(row)
        row_phones = _phones_from_row(row)
        if email and email in existing_emails:
            skipped += 1
            continue
        if any(p in existing_phones for p in row_phones):
            skipped += 1
            continue
        new_rows.append(row)

    return new_rows, skipped


def _index_csv_by_contact(csv_rows: List[dict]) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    by_email: Dict[str, dict] = {}
    by_phone: Dict[str, dict] = {}
    for row in csv_rows:
        email = _email_from_row(row)
        if email and email not in by_email:
            by_email[email] = row
        for phone in _phones_from_row(row):
            if phone not in by_phone:
                by_phone[phone] = row
    return by_email, by_phone


def _strip_pipeline_fields(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in ("pipeline", "position")}


def match_leads_to_csv(
    existing_leads: List[dict], csv_rows: List[dict]
) -> Tuple[List[dict], int]:
    """
    Match existing API leads to CSV rows (email first, phone second).
    Returns (update_payloads, unmatched_count).
    """
    by_email, by_phone = _index_csv_by_contact(csv_rows)
    matched: List[dict] = []
    unmatched = 0

    for existing in existing_leads:
        email, phones = _contact_from_lead(existing)
        csv_row = None
        if email and email in by_email:
            csv_row = by_email[email]
        elif phones:
            for phone in phones:
                if phone in by_phone:
                    csv_row = by_phone[phone]
                    break

        if csv_row is None:
            unmatched += 1
            continue

        payload = dict(existing)
        if existing.get("id") is not None:
            payload["id"] = existing["id"]
        for key, value in csv_row.items():
            if value not in (None, ""):
                payload[key] = value
        matched.append(_strip_pipeline_fields(payload))

    return matched, unmatched
