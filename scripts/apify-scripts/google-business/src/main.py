"""Google Maps business Actor. Sync Playwright runs in a worker thread.

Requests /maps/search/ and /maps/place/ only. A block page stops the run
with a blocked dataset row and exit 0.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from apify import Actor

try:
    from .mapping import (
        GOOGLE_ROBOTS_URL,
        billable_row,
        collect_listings,
        maps_allowed,
        queries_from_input,
        read_run_settings,
        reference_tables,
        score_query,
        status_row,
        summarize,
    )
    from .runtime import fetch_text, prepare_imports, push_charged_rows
except ImportError:
    from mapping import (
        GOOGLE_ROBOTS_URL,
        billable_row,
        collect_listings,
        maps_allowed,
        queries_from_input,
        read_run_settings,
        reference_tables,
        score_query,
        status_row,
        summarize,
    )
    from runtime import fetch_text, prepare_imports, push_charged_rows


class DelaySession:
    """BusinessDiscoverySession with optional delay ranges.

    The CLI class sleeps a fixed delay or the module default range. This
    subclass only changes the sleep when the Actor input overrides the range.
    Launch flags stay inside BusinessDiscoverySession.
    """

    def __init__(self, settings):
        prepare_imports()
        from playwright_discovery import BusinessDiscoverySession

        self._session = BusinessDiscoverySession(headless=settings["headless"])
        self._search_min = settings["search_delay_min"]
        self._search_max = settings["search_delay_max"]
        self._detail_min = settings["detail_delay_min"]
        self._detail_max = settings["detail_delay_max"]
        self._session._sleep_between_searches = self._sleep_between_searches
        self._session._sleep_between_details = self._sleep_between_details

    def _sleep_between_searches(self):
        if self._session._searches_done <= 0:
            return
        time.sleep(random.uniform(self._search_min, self._search_max))

    def _sleep_between_details(self):
        if self._session._details_done <= 0:
            return
        time.sleep(random.uniform(self._detail_min, self._detail_max))

    def __getattr__(self, name):
        return getattr(self._session, name)


def _log_row(row):
    query = (row or {}).get("query") or {}
    logging.getLogger("apify").critical(
        "Google Business: %s, %s %s -> %s",
        query.get("name") or "",
        query.get("city") or "",
        query.get("state") or "",
        (row or {}).get("decision"),
    )


def run_sync(actor_input):
    actor_input = actor_input or {}
    settings = read_run_settings(actor_input)
    queries = queries_from_input(actor_input, settings)
    robots_txt = fetch_text(GOOGLE_ROBOTS_URL)
    if not maps_allowed(robots_txt):
        rows = [
            status_row(query, "error", "robots_disallowed", error="robots_disallowed")
            for query in queries
        ]
        for row in rows:
            _log_row(row)
        return rows, summarize(rows)

    zip_county, npa_state = reference_tables()
    session = DelaySession(settings)
    rows = []
    try:
        for query in queries:
            if session.google_blocked:
                row = status_row(query, "blocked", "blocked", error="google_blocked")
                rows.append(row)
                _log_row(row)
                break
            listings, blocked = collect_listings(session, query)
            if blocked:
                row = status_row(query, "blocked", "blocked", error="google_blocked")
                rows.append(row)
                _log_row(row)
                break
            row = score_query(query, listings, settings, zip_county, npa_state)
            rows.append(row)
            _log_row(row)
    finally:
        session.close()
    return rows, summarize(rows)


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        try:
            rows, summary = await asyncio.to_thread(run_sync, actor_input)
        except Exception as exc:
            rows = [status_row(None, "error", "error", error=str(exc))]
            summary = {"status": "error", "pushed": 1, "blocked": 0, "errors": 1, "error": str(exc)}
            logging.getLogger("apify").critical("Google Business failed: %s", exc)
        await push_charged_rows(rows, billable_row)
        await Actor.set_value("SUMMARY", summary)
