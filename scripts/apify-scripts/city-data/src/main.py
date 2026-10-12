"""City-data Actor. Sync Playwright runs in a worker thread."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .mapping import (
        CITY_ROBOTS_URL,
        actor_input_to_config,
        billable_row,
        error_item,
        scrape_config,
        summarize,
    )
    from .runtime import fetch_text, prepare_imports, push_charged_rows
except ImportError:
    from mapping import (
        CITY_ROBOTS_URL,
        actor_input_to_config,
        billable_row,
        error_item,
        scrape_config,
        summarize,
    )
    from runtime import fetch_text, prepare_imports, push_charged_rows


def run_sync(actor_input):
    prepare_imports()
    from city_data_scraper import CityDataSession

    actor_input = actor_input or {}
    config = actor_input_to_config(actor_input)
    robots_txt = fetch_text(CITY_ROBOTS_URL)
    session = CityDataSession(
        headless=config["headless"],
        timeout_ms=config["timeout_ms"],
        delay_seconds=config["delay_seconds"],
    )
    try:
        rows = scrape_config(config, session, robots_txt)
    finally:
        session.close()
    log = logging.getLogger("apify")
    for row in rows:
        log.critical(
            "City-data: %s, %s -> %s",
            row.get("city"),
            row.get("state"),
            row.get("sourceStatus"),
        )
    return rows, summarize(rows)


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        try:
            rows, summary = await asyncio.to_thread(run_sync, actor_input)
        except Exception as exc:
            rows = [error_item(str(exc))]
            summary = {"status": "error", "pushed": 1, "blocked": 0, "errors": 1, "error": str(exc)}
            logging.getLogger("apify").critical("City-data failed: %s", exc)
        await push_charged_rows(rows, billable_row)
        await Actor.set_value("SUMMARY", summary)
