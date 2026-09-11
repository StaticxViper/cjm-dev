#!/usr/bin/env python3
"""
search_history.py

Persisted record of completed leadgen searches (keyword × location × mode).
Used to skip repeat work and avoid wasting Places API / Playwright runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
from threading import Lock

_lock = Lock()

HISTORY_VERSION = 1
DEFAULT_HISTORY_PATH = "leadgen_search_history.json"
DEFAULT_USAGE_PATH = "leadgen_usage.json"


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_search_key(
    leadgen_type,
    keyword,
    city,
    state,
    search_radius=None,
    playwright_max_pages=None,
):
    """Stable identity for one discovery unit of work."""
    leadgen_type = (leadgen_type or "api_manager").strip().lower()
    keyword = (keyword or "").strip().lower()
    city = (city or "").strip().lower()
    state = (state or "").strip().upper()
    parts = [leadgen_type, keyword, city, state]
    if leadgen_type == "playwright":
        parts.append(f"pages:{int(playwright_max_pages or 10)}")
    else:
        parts.append(f"radius:{int(search_radius or 50000)}")
    return "|".join(parts)


class SearchHistory:
    """Load/save completed searches and append run summaries."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path(DEFAULT_HISTORY_PATH)
        self._data = {"version": HISTORY_VERSION, "searches": {}, "runs": []}
        self.load()

    def load(self):
        if not self.path.exists():
            return self._data
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return self._data
        if not isinstance(data, dict):
            return self._data
        searches = data.get("searches") or {}
        if isinstance(searches, list):
            # Migrate list form -> dict keyed by search key.
            migrated = {}
            for item in searches:
                if isinstance(item, dict) and item.get("key"):
                    migrated[item["key"]] = item
            searches = migrated
        if not isinstance(searches, dict):
            searches = {}
        runs = data.get("runs") or []
        if not isinstance(runs, list):
            runs = []
        self._data = {
            "version": HISTORY_VERSION,
            "searches": searches,
            "runs": runs,
        }
        return self._data

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        with _lock:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, self.path)

    def get(self, key):
        return self._data.get("searches", {}).get(key)

    def was_searched(self, key):
        return bool(self.get(key))

    def record_search(
        self,
        *,
        leadgen_type,
        keyword,
        city,
        state,
        search_radius=None,
        playwright_max_pages=None,
        businesses_found=0,
        status="completed",
        extra=None,
    ):
        key = make_search_key(
            leadgen_type,
            keyword,
            city,
            state,
            search_radius=search_radius,
            playwright_max_pages=playwright_max_pages,
        )
        entry = {
            "key": key,
            "leadgen_type": leadgen_type,
            "keyword": keyword,
            "city": city,
            "state": state,
            "search_radius": search_radius,
            "playwright_max_pages": playwright_max_pages,
            "businesses_found": int(businesses_found or 0),
            "status": status,
            "completed_at": _iso_now(),
        }
        if extra:
            entry["extra"] = extra
        with _lock:
            self._data.setdefault("searches", {})[key] = entry
        return entry

    def record_run(self, summary):
        """Append a run summary dict (started_at/finished_at/stats/etc.)."""
        payload = dict(summary or {})
        payload.setdefault("finished_at", _iso_now())
        with _lock:
            self._data.setdefault("runs", []).append(payload)
            # Keep the file from growing without bound.
            if len(self._data["runs"]) > 100:
                self._data["runs"] = self._data["runs"][-100:]
        return payload

    def pending_keywords_for_location(
        self,
        keywords,
        city,
        state,
        leadgen_type,
        search_radius=None,
        playwright_max_pages=None,
        skip_searched=True,
    ):
        """Return (to_run, skipped_entries) for one location."""
        to_run = []
        skipped = []
        for keyword in keywords:
            key = make_search_key(
                leadgen_type,
                keyword,
                city,
                state,
                search_radius=search_radius,
                playwright_max_pages=playwright_max_pages,
            )
            prior = self.get(key)
            if skip_searched and prior:
                skipped.append(prior)
            else:
                to_run.append(keyword)
        return to_run, skipped


def update_usage_stats(
    path=None,
    *,
    nearby_calls=0,
    details_calls=0,
    runs=1,
):
    """Increment leadgen_usage.json counters (Places API accounting)."""
    usage_path = Path(path) if path is not None else Path(DEFAULT_USAGE_PATH)
    data = {
        "total_calls": 0,
        "nearby_calls": 0,
        "details_calls": 0,
        "runs": 0,
    }
    if usage_path.exists():
        try:
            with open(usage_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update({k: int(loaded.get(k) or 0) for k in data})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    data["nearby_calls"] += int(nearby_calls or 0)
    data["details_calls"] += int(details_calls or 0)
    data["total_calls"] = data["nearby_calls"] + data["details_calls"]
    data["runs"] += int(runs or 0)
    data["updated_at"] = _iso_now()

    tmp_path = usage_path.with_name(usage_path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, usage_path)
    return data
