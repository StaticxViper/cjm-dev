"""ATS job-board Actor. Public JSON over HTTP. No browser, proxy, or CAPTCHA solver."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import _blank_row, _summarize, actor_input_to_config, billable_row, scrape
    from .runtime import iso_now, push_charged_rows
    from .spend import JOB_EVENT, JobLedger
    from .state import STATE_KEY, dump_state, load_state, merge_state
except ImportError:
    from fetch import make_live_fetch
    from mapping import _blank_row, _summarize, actor_input_to_config, billable_row, scrape
    from runtime import iso_now, push_charged_rows
    from spend import JOB_EVENT, JobLedger
    from state import STATE_KEY, dump_state, load_state, merge_state


log = logging.getLogger("apify")


def run_sync(config, seen):
    fetch = make_live_fetch(config)
    try:
        return scrape(config, fetch, seen=seen)
    finally:
        closer = getattr(fetch, "close", None)
        if closer:
            closer()


async def _open_state(name):
    try:
        store = await Actor.open_key_value_store(name=name)
        return store, load_state(await store.get_value(STATE_KEY))
    except Exception as exc:
        log.critical("Could not open state store %s: %s", name, exc)
        return None, {}


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        config = actor_input_to_config(actor_input)
        store, seen = await _open_state(config["state_store"])
        try:
            rows, summary, new_seen = await asyncio.to_thread(run_sync, config, seen)
        except Exception as exc:
            log.critical("ATS jobs failed: %s", exc)
            rows = [_blank_row("error", str(exc), iso_now())]
            summary = _summarize(rows, config, {}, [], "error", False, rows[0]["scrapedAt"])
            new_seen = {}
        ledger = JobLedger(config["max_spend_usd"])
        await push_charged_rows(rows, billable_row, event_name=JOB_EVENT, ledger=ledger)
        found = sum(1 for row in rows if billable_row(row))
        summary["billedJobs"] = ledger.counts.get(JOB_EVENT, 0)
        summary["spendUsd"] = ledger.spend_usd
        summary["chargeCapped"] = summary["billedJobs"] < found
        if store is not None and new_seen:
            merged = merge_state(seen, new_seen)
            try:
                await store.set_value(STATE_KEY, dump_state(merged, iso_now()))
                summary["stateKeys"] = len(merged)
            except Exception as exc:
                log.critical("Could not save state store %s: %s", config["state_store"], exc)
                summary["stateError"] = str(exc)
        else:
            summary["stateKeys"] = len(seen)
        await Actor.set_value("SUMMARY", summary)
