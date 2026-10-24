"""Contractor license Actor. Open-data HTTP lookups. No browser and no CAPTCHA solving."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_fetch
    from .mapping import LICENSE_EVENT, actor_input_to_config, billable_row, scrape
    from .runtime import push_charged_rows
except ImportError:
    from fetch import make_fetch
    from mapping import LICENSE_EVENT, actor_input_to_config, billable_row, scrape
    from runtime import push_charged_rows


def _log_row(row):
    logging.getLogger("apify").critical(
        "Contractor license: %s %s -> %s",
        (row or {}).get("state") or "",
        (row or {}).get("license_no") or (row or {}).get("name") or "",
        (row or {}).get("sourceStatus"),
    )


def run_sync(actor_input):
    config = actor_input_to_config(actor_input)
    fetch = make_fetch(config["delay_seconds"], config["max_requests"])
    rows, summary = scrape(config, fetch)
    for row in rows:
        _log_row(row)
    return rows, summary


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        try:
            rows, summary = await asyncio.to_thread(run_sync, actor_input)
        except Exception as exc:
            config = actor_input_to_config(actor_input)
            rows, summary = scrape(
                {"query": config["query"], "error": str(exc)},
                fetch=lambda url: {"status": 0, "text": "", "error": "not_called", "content_type": ""},
            )
            summary["status"] = "error"
            summary["error"] = str(exc)
            logging.getLogger("apify").critical("Contractor license failed: %s", exc)
        await push_charged_rows(rows, billable_row, event_name=LICENSE_EVENT)
        await Actor.set_value("SUMMARY", summary)
