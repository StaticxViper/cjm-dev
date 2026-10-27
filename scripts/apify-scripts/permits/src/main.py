"""Building-permit Actor. Open-data HTTP. No browser and no stealth plugins."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import _blank_row, actor_input_to_config, billable_row, scrape
    from .runtime import (
        AccessPolicy,
        access_summary,
        cached_proxy_url,
        charge_usage,
        iso_now,
        push_charged_rows,
        read_access_settings,
    )
    from .spend import PERMIT_EVENT, PRICES_USD
except ImportError:
    from fetch import make_live_fetch
    from mapping import _blank_row, actor_input_to_config, billable_row, scrape
    from runtime import (
        AccessPolicy,
        access_summary,
        cached_proxy_url,
        charge_usage,
        iso_now,
        push_charged_rows,
        read_access_settings,
    )
    from spend import PERMIT_EVENT, PRICES_USD


def _log_row(row):
    logging.getLogger("apify").critical(
        "Permit %s %s -> %s",
        (row or {}).get("source") or "",
        (row or {}).get("permit_id") or "",
        (row or {}).get("sourceStatus"),
    )


def run_sync(actor_input, proxy_url_fn=None):
    config = actor_input_to_config(actor_input)
    fetch = make_live_fetch(config, proxy_url_fn)
    rows, summary = scrape(config, fetch)
    for row in rows:
        _log_row(row)
    return rows, summary, fetch.ledger


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        access = read_access_settings(actor_input, prices_usd=PRICES_USD)
        proxy_url_fn = cached_proxy_url(access, asyncio.get_running_loop())
        ledger = None
        try:
            rows, summary, ledger = await asyncio.to_thread(run_sync, actor_input, proxy_url_fn)
        except Exception as exc:
            logging.getLogger("apify").critical("Permits failed: %s", exc)
            rows = [_blank_row("error", str(exc), iso_now())]
            summary = {
                "status": "error",
                "pushed": 1,
                "found": 0,
                "billedPermits": 0,
                "blocked": 0,
                "errors": 1,
                "error": str(exc),
                "sources": [],
            }
            summary.update(access_summary(access, AccessPolicy(access).ledger))
            ledger = None
        await charge_usage(ledger)
        await push_charged_rows(rows, billable_row, event_name=PERMIT_EVENT, ledger=ledger)
        if ledger is not None:
            summary["billedPermits"] = ledger.counts.get(PERMIT_EVENT, 0)
            summary["proxyCharges"] = ledger.counts.get("proxy", 0)
            summary["captchaCharges"] = ledger.counts.get("captcha", 0)
            summary["spendUsd"] = ledger.spend_usd
            summary["chargeCapped"] = summary["billedPermits"] < sum(1 for row in rows if billable_row(row))
        await Actor.set_value("SUMMARY", summary)
