"""Home-services lead enricher. Sync Playwright runs in a worker thread.

Maps search uses the google-business session. A block page stops the run
with a blocked dataset row and exit 0. Website enrichment is skipped when
robots.txt disallows the page. Google web search is not requested.
"""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .mapping import billable_events, error_bundle, run_sync
except ImportError:
    from mapping import billable_events, error_bundle, run_sync


async def push_events(rows):
    """Push every row. Charge place, email-found, and score only when produced."""
    log = logging.getLogger("apify")
    capped = False
    for row in rows or []:
        events = billable_events(row)
        await Actor.push_data(row)
        if capped:
            continue
        for event in events:
            result = await Actor.charge(event_name=event)
            if getattr(result, "event_charge_limit_reached", False):
                capped = True
                log.critical("Charge limit reached. Later rows are saved and are not billed.")
                break


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        try:
            rows, summary = await asyncio.to_thread(run_sync, actor_input)
        except Exception as exc:
            rows, summary = error_bundle(exc)
            logging.getLogger("apify").critical("Home services failed: %s", exc)
        await push_events(rows)
        await Actor.set_value("SUMMARY", summary)
