"""
lead_filter.py

Persistent duplicate filtering module for lead generation.
Prevents exporting leads that already exist in previous runs.
"""
import csv
import os
from threading import Lock

_lock = Lock()


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
