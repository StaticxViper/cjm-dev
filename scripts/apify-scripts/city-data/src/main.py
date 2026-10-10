"""City-data Actor. Sync Playwright runs in a worker thread."""

from __future__ import annotations

import asyncio

from apify import Actor

try:
    from .mapping import (
        CITY_ROBOTS_URL,
        actor_input_to_config,
        error_item,
        scrape_config,
        summarize,
    )
    from .runtime import fetch_text, prepare_imports, unused_proxy_note
except ImportError:
    from mapping import (
        CITY_ROBOTS_URL,
        actor_input_to_config,
        error_item,
        scrape_config,
        summarize,
    )
    from runtime import fetch_text, prepare_imports, unused_proxy_note


def run_sync(actor_input):
    prepare_imports()
    from city_data_scraper import CityDataSession

    actor_input = actor_input or {}
    note = unused_proxy_note(actor_input)
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
            rows = [error_item(str(exc))]
            summary = {"status": "error", "pushed": 1, "blocked": 0, "errors": 1, "error": str(exc)}
        for row in rows:
            await Actor.push_data(row)
        await Actor.set_value("SUMMARY", summary)
