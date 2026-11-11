"""Building-permit Actor. Open-data HTTP. No browser and no stealth plugins."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import _blank_row, actor_input_to_config, billable_row, permit_access_settings, scrape
    from .runtime import (
        AccessPolicy,
        access_summary,
        cached_proxy_url,
        charge_usage,
        iso_now,
    )
    from .spend import PERMIT_EVENT
    from .state import STATE_KEY, dump_state, load_state, merge_state, permit_key
except ImportError:
    from fetch import make_live_fetch
    from mapping import _blank_row, actor_input_to_config, billable_row, permit_access_settings, scrape
    from runtime import (
        AccessPolicy,
        access_summary,
        cached_proxy_url,
        charge_usage,
        iso_now,
    )
    from spend import PERMIT_EVENT
    from state import STATE_KEY, dump_state, load_state, merge_state, permit_key


log = logging.getLogger("apify")


def _log_row(row):
    log.critical(
        "Permit %s %s -> %s",
        (row or {}).get("source") or "",
        (row or {}).get("permit_id") or "",
        (row or {}).get("sourceStatus"),
    )


def run_sync(actor_input, proxy_url_fn=None, seen_state=None):
    config = actor_input_to_config(actor_input)
    fetch = make_live_fetch(config, proxy_url_fn)
    rows, summary = scrape(config, fetch, seen_state=seen_state)
    for row in rows:
        _log_row(row)
    return rows, summary, fetch.ledger


async def _open_state(name):
    try:
        store = await Actor.open_key_value_store(name=name)
        return store, load_state(await store.get_value(STATE_KEY))
    except Exception as exc:
        log.critical("Could not open state store %s: %s", name, exc)
        return None, {}


async def push_permits(rows, ledger):
    """Push every row. Charge ``permit`` only for billable rows the spend cap still covers.

    Same contract as the shared ``push_charged_rows``, but returns the rows
    that were charged so newSinceLastRun records only those.
    """
    charged = []
    capped = False
    for row in rows or []:
        await Actor.push_data(row)
        if capped or not billable_row(row):
            continue
        if ledger is not None and not ledger.can(PERMIT_EVENT):
            capped = True
            log.critical("%s spend cap reached. Later rows are saved and are not billed.", PERMIT_EVENT)
            continue
        if ledger is not None:
            ledger.commit(PERMIT_EVENT)
        result = await Actor.charge(event_name=PERMIT_EVENT)
        charged.append(row)
        if getattr(result, "event_charge_limit_reached", False):
            capped = True
            log.critical("%s charge limit reached. Later rows are saved and are not billed.", PERMIT_EVENT)
    return charged


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        config = actor_input_to_config(actor_input)
        access = permit_access_settings(actor_input)
        proxy_url_fn = cached_proxy_url(access, asyncio.get_running_loop())
        store, seen = await _open_state(config["state_store"])
        ledger = None
        try:
            rows, summary, ledger = await asyncio.to_thread(run_sync, actor_input, proxy_url_fn, seen)
        except Exception as exc:
            log.critical("Permits failed: %s", exc)
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
        charged = await push_permits(rows, ledger)
        if ledger is not None:
            summary["billedPermits"] = ledger.counts.get(PERMIT_EVENT, 0)
            summary["proxyCharges"] = ledger.counts.get("proxy", 0)
            summary["captchaCharges"] = ledger.counts.get("captcha", 0)
            summary["spendUsd"] = ledger.spend_usd
            summary["chargeCapped"] = summary["billedPermits"] < sum(1 for row in rows if billable_row(row))
        first_seen = iso_now()
        new_seen = {permit_key(row.get("source"), row.get("permit_id")): first_seen for row in charged}
        if store is not None and new_seen:
            merged = merge_state(seen, new_seen)
            try:
                await store.set_value(STATE_KEY, dump_state(merged, first_seen))
                summary["stateKeys"] = len(merged)
            except Exception as exc:
                log.critical("Could not save state store %s: %s", config["state_store"], exc)
                summary["stateError"] = str(exc)
        else:
            summary["stateKeys"] = len(seen)
        await Actor.set_value("SUMMARY", summary)
