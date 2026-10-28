"""City-data Actor. Sync Playwright runs in a worker thread."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .mapping import (
        CITY_ROBOTS_URL,
        PRICES_USD,
        actor_input_to_config,
        billable_row,
        error_item,
        run_cities,
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
        CITY_ROBOTS_URL,
        PRICES_USD,
        actor_input_to_config,
        billable_row,
        error_item,
        run_cities,
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


def run_sync(actor_input, proxy_url_fn=None, session_factory=None, robots_text=None, solver=None):
    prepare_imports()
    actor_input = actor_input or {}
    access = read_access_settings(actor_input, prices_usd=PRICES_USD)
    policy = AccessPolicy(access, solver=solver)
    config = actor_input_to_config(actor_input)
    robots_txt = robots_text if robots_text is not None else fetch_text(CITY_ROBOTS_URL)

    def open_session(proxy_url):
        if session_factory is not None:
            return session_factory(proxy_url)
        from city_data_scraper import CityDataSession

        return CityDataSession(
            headless=config["headless"],
            timeout_ms=config["timeout_ms"],
            delay_seconds=config["delay_seconds"],
            proxy=playwright_proxy(proxy_url) if proxy_url else None,
        )

    rows, summary = run_cities(
        config,
        robots_txt,
        policy,
        open_session,
        proxy_url_fn or (lambda: ""),
    )
    log = logging.getLogger("apify")
    for row in rows:
        log.critical(
            "City-data: %s, %s -> %s",
            row.get("city"),
            row.get("state"),
            row.get("sourceStatus"),
        )
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
            rows = [error_item(str(exc))]
            summary = {"status": "error", "pushed": 1, "blocked": 0, "errors": 1, "error": str(exc)}
            summary.update(access_summary(access, AccessPolicy(access).ledger))
            logging.getLogger("apify").critical("City-data failed: %s", exc)
        await charge_usage(ledger)
        await push_charged_rows(rows, billable_row, ledger=ledger)
        await Actor.set_value("SUMMARY", summary)
