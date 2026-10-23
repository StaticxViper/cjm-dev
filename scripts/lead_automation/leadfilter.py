"""
lead_filter.py

Persistent duplicate filtering module for lead generation.
Prevents exporting leads that already exist in previous runs.
"""
import json
import os
import re
from threading import Lock

from helper_scripts.maps.identity import normalize_profile_url as _normalize_profile_url

_lock = Lock()


def _phone_digits(phone):
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def identity_keys_from_row(row):
    """Return a set of stable identity keys for a lead row."""
    keys = set()
    if not isinstance(row, dict):
        return keys
    place_id = (row.get("place_id") or "").strip()
    if place_id:
        keys.add(("place_id", place_id.lower()))
    profile = _normalize_profile_url(row.get("profile_url") or "")
    if profile:
        keys.add(("profile_url", profile.lower()))
    name = re.sub(r"\s+", " ", (row.get("business_name") or "").strip().lower())
    phone = _phone_digits(row.get("phone_google"))
    if name and phone:
        keys.add(("name_phone", name, phone))
    address = re.sub(r"\s+", " ", (row.get("address") or "").strip().lower())
    address = re.sub(r"[^\w\s,]", "", address)
    if name and address:
        keys.add(("name_address", name, address))
    return keys


def load_existing_place_ids(json_path: str) -> set:
    """
    Load existing place_ids from a JSON leads array if it exists.
    Returns a set of place_ids.
    """
    if not os.path.exists(json_path):
        return set()

    existing = set()
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()

    if not isinstance(data, list):
        return set()

    for row in data:
        if not isinstance(row, dict):
            continue
        place_id = row.get("place_id")
        if place_id:
            existing.add(place_id)

    return existing


def load_existing_identities(json_path: str) -> set:
    """
    Load existing identity keys (place_id, profile_url, name+phone, name+address)
    from a JSON leads array if it exists.
    """
    if not os.path.exists(json_path):
        return set()

    existing = set()
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()

    if not isinstance(data, list):
        return set()

    for row in data:
        existing.update(identity_keys_from_row(row))

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


def is_new_identity(entry, existing_identities: set) -> bool:
    """
    Thread-safe multi-key check. Returns True if none of the entry's identity
    keys were seen before. On success, all keys are inserted.
    """
    keys = identity_keys_from_row(entry)
    place_id = (entry.get("place_id") or "").strip()
    if place_id:
        keys.add(("place_id", place_id.lower()))
    if not keys:
        return True
    with _lock:
        if any(key in existing_identities for key in keys):
            return False
        existing_identities.update(keys)
        return True
