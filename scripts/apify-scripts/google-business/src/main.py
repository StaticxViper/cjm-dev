"""Google Maps business Actor. Sync Playwright runs in a worker thread.

Requests /maps/search/ and /maps/place/ only. A block page stops the run
with a blocked dataset row and exit 0. proxyConfiguration is ignored.
"""

from __future__ import annotations

import asyncio
import random
import time

from apify import Actor

try:
    from .mapping import (
        GOOGLE_ROBOTS_URL,
        collect_listings,
        maps_allowed,
        queries_from_input,
        read_run_settings,
        reference_tables,
        score_query,
        status_row,
        summarize,
    )
    from .runtime import fetch_text, prepare_imports, unused_proxy_note
except ImportError:
    from mapping import (
        GOOGLE_ROBOTS_URL,
        collect_listings,
        maps_allowed,
        queries_from_input,
        read_run_settings,
        reference_tables,
        score_query,
        status_row,
        summarize,
    )
    from runtime import fetch_text, prepare_imports, unused_proxy_note


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


def run_sync(actor_input):
    actor_input = actor_input or {}
    note = unused_proxy_note(actor_input)
    settings = read_run_settings(actor_input)
    queries = queries_from_input(actor_input, settings)
    robots_txt = fetch_text(GOOGLE_ROBOTS_URL)
    if not maps_allowed(robots_txt):
        rows = [
            status_row(query, "error", "robots_disallowed", error="robots_disallowed")
            for query in queries
        ]
        summary = summarize(rows)
        if note:
            summary["proxy"] = note
        return rows, summary

    zip_county, npa_state = reference_tables()
    session = DelaySession(settings)
    rows = []
    try:
        for query in queries:
            if session.google_blocked:
                rows.append(status_row(query, "blocked", "blocked", error="google_blocked"))
                break
            listings, blocked = collect_listings(session, query)
            if blocked:
                rows.append(status_row(query, "blocked", "blocked", error="google_blocked"))
                break
            rows.append(score_query(query, listings, settings, zip_county, npa_state))
    finally:
        session.close()
    summary = summarize(rows)
    if note:
        summary["proxy"] = note
    return rows, summary


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        try:
            rows, summary = await asyncio.to_thread(run_sync, actor_input)
        except Exception as exc:
            rows = [status_row(None, "error", "error", error=str(exc))]
            summary = {"status": "error", "pushed": 1, "blocked": 0, "errors": 1, "error": str(exc)}
        for row in rows:
            await Actor.push_data(row)
        await Actor.set_value("SUMMARY", summary)
