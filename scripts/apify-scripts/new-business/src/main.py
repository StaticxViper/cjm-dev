"""New-business Actor. Open-data HTTP. No browser and no stealth plugins."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import _blank_row, actor_input_to_config, scrape
    from .runtime import iso_now
    from .spend import BUSINESS_EVENT, CAPTCHA_EVENT, ENRICHMENT_EVENT, PROXY_EVENT
except ImportError:
    from fetch import make_live_fetch
    from mapping import _blank_row, actor_input_to_config, scrape
    from runtime import iso_now
    from spend import BUSINESS_EVENT, CAPTCHA_EVENT, ENRICHMENT_EVENT, PROXY_EVENT


def _log_row(row):
    logging.getLogger("apify").critical(
        "New business: %s %s -> %s",
        (row or {}).get("state") or "",
        (row or {}).get("entity_id") or (row or {}).get("name") or "",
        (row or {}).get("sourceStatus"),
    )


def run_sync(actor_input):
    config = actor_input_to_config(actor_input)
    fetch = make_live_fetch(config)
    rows, summary = scrape(config, fetch)
    for row in rows:
        _log_row(row)
    return rows, summary


async def _charge(event_name, times):
    capped = False
    for _ in range(times):
        if capped:
            break
        result = await Actor.charge(event_name=event_name)
        if getattr(result, "event_charge_limit_reached", False):
            capped = True
            logging.getLogger("apify").critical(
                "%s charge limit reached. Later events are not billed.",
                event_name,
            )
    return capped


def _public_row(row):
    return {key: value for key, value in (row or {}).items() if not str(key).startswith("_")}


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        try:
            rows, summary = await asyncio.to_thread(run_sync, actor_input)
        except Exception as exc:
            logging.getLogger("apify").critical("New business failed: %s", exc)
            rows = [_blank_row("error", str(exc), iso_now())]
            summary = {
                "status": "error",
                "pushed": 1,
                "found": 0,
                "billedBusiness": 0,
                "billedEnrichment": 0,
                "proxyCharges": 0,
                "captchaCharges": 0,
                "error": str(exc),
            }
            for row in rows:
                row["_chargeBusiness"] = False
                row["_chargeEnrichment"] = False
        for row in rows:
            await Actor.push_data(_public_row(row))
        await _charge(PROXY_EVENT, int(summary.get("proxyCharges") or 0))
        await _charge(CAPTCHA_EVENT, int(summary.get("captchaCharges") or 0))
        business_left = int(summary.get("billedBusiness") or 0)
        enrichment_left = int(summary.get("billedEnrichment") or 0)
        for row in rows:
            if business_left and row.get("_chargeBusiness"):
                if await _charge(BUSINESS_EVENT, 1):
                    break
                business_left -= 1
            if enrichment_left and row.get("_chargeEnrichment"):
                if await _charge(ENRICHMENT_EVENT, 1):
                    break
                enrichment_left -= 1
        await Actor.set_value("SUMMARY", summary)
