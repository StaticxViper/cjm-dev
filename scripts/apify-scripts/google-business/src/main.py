"""Google Maps business Actor. Sync Playwright runs in a worker thread.

Requests /maps/search/ and /maps/place/ only. A block retries once through
Apify Proxy when the spend cap allows it, then pushes a blocked row and
exits 0.
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
        PRICES_USD,
        billable_row,
        maps_allowed,
        queries_from_input,
        read_run_settings,
        reference_tables,
        run_maps,
        status_row,
        summarize,
    )
    from .runtime import (
        AccessPolicy,
        access_summary,
        cached_proxy_url,
        charge_usage,
        fetch_text,
        playwright_proxy,
        prepare_imports,
        push_charged_rows,
        read_access_settings,
    )
except ImportError:
    from mapping import (
        GOOGLE_ROBOTS_URL,
        PRICES_USD,
        billable_row,
        maps_allowed,
        queries_from_input,
        read_run_settings,
        reference_tables,
        run_maps,
        status_row,
        summarize,
    )
    from runtime import (
        AccessPolicy,
        access_summary,
        cached_proxy_url,
        charge_usage,
        fetch_text,
        playwright_proxy,
        prepare_imports,
        push_charged_rows,
        read_access_settings,
    )


class DelaySession:
    """BusinessDiscoverySession with optional delay ranges.

    The CLI class sleeps a fixed delay or the module default range. This
    subclass only changes the sleep when the Actor input overrides the range.
    Launch flags stay inside BusinessDiscoverySession.
    """

    def __init__(self, settings, proxy=None):
        prepare_imports()
        from playwright_discovery import BusinessDiscoverySession

        self._session = BusinessDiscoverySession(headless=settings["headless"], proxy=proxy)
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


def run_sync(actor_input, proxy_url_fn=None, session_factory=None, robots_text=None, solver=None):
    actor_input = actor_input or {}
    settings = read_run_settings(actor_input)
    queries = queries_from_input(actor_input, settings)
    robots_txt = robots_text if robots_text is not None else fetch_text(GOOGLE_ROBOTS_URL)
    access = read_access_settings(actor_input, prices_usd=PRICES_USD)
    policy = AccessPolicy(access, solver=solver)
    if not maps_allowed(robots_txt):
        rows = [
            status_row(query, "error", "robots_disallowed", error="robots_disallowed")
            for query in queries
        ]
        for row in rows:
            _log_row(row)
        summary = summarize(rows)
        summary.update(access_summary(access, policy.ledger))
        return rows, summary, policy.ledger

    zip_county, npa_state = reference_tables()

    def open_session(proxy_url):
        if session_factory is not None:
            return session_factory(proxy_url)
        proxy = playwright_proxy(proxy_url) if proxy_url else None
        return DelaySession(settings, proxy=proxy)

    rows, summary = run_maps(
        queries,
        settings,
        zip_county,
        npa_state,
        policy,
        open_session,
        proxy_url_fn or (lambda: ""),
    )
    for row in rows:
        _log_row(row)
    return rows, summary, policy.ledger


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        access = read_access_settings(actor_input, prices_usd=PRICES_USD)
        proxy_url_fn = cached_proxy_url(access, asyncio.get_running_loop())
        ledger = None
        try:
            rows, summary, ledger = await asyncio.to_thread(run_sync, actor_input, proxy_url_fn)
        except Exception as exc:
            rows = [status_row(None, "error", "error", error=str(exc))]
            summary = {"status": "error", "pushed": 1, "blocked": 0, "errors": 1, "error": str(exc)}
            summary.update(access_summary(access, AccessPolicy(access).ledger))
            logging.getLogger("apify").critical("Google Business failed: %s", exc)
        await charge_usage(ledger)
        await push_charged_rows(rows, billable_row, ledger=ledger)
        await Actor.set_value("SUMMARY", summary)
