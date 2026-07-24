"""
lead_filter.py

Persistent duplicate filtering module for lead generation.
Prevents exporting leads that already exist in previous runs.
"""
import json
import os
from threading import Lock

_lock = Lock()


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
