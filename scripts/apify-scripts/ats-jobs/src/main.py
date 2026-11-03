"""ATS job-board Actor. Public JSON over HTTP. No browser, proxy, or CAPTCHA solver."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import _blank_row, _summarize, actor_input_to_config, billable_row, job_key, scrape
    from .runtime import iso_now
    from .spend import JOB_EVENT, JobLedger
    from .state import STATE_KEY, dump_state, load_state, merge_state
except ImportError:
    from fetch import make_live_fetch
    from mapping import _blank_row, _summarize, actor_input_to_config, billable_row, job_key, scrape
    from runtime import iso_now
    from spend import JOB_EVENT, JobLedger
    from state import STATE_KEY, dump_state, load_state, merge_state


log = logging.getLogger("apify")

CAP_MESSAGES = {
    "maxSpendUsd": "maxSpendUsd cannot cover the next job. {held} matching job(s) were not pushed.",
    "chargeLimit": "The run's platform charge limit was reached. {held} matching job(s) were not pushed.",
    "pushFailed": "A dataset push failed. {held} matching job(s) were not pushed.",
    "chargeFailed": "A job charge failed. {held} matching job(s) were not pushed.",
}


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


def _row_key(row):
    return job_key(row.get("ats"), row.get("companySlug"), row.get("jobId"))


async def push_jobs(rows, ledger):
    """Push each job row only when it can be billed, then the free status rows.

    Returns (pushed job rows, stop reason, held-back job count, status rows
    pushed). A job row is never pushed without its charge, so maxSpendUsd and
    the platform charge limit end the job feed.
    """
    jobs = [row for row in rows if billable_row(row)]
    others = [row for row in rows if not billable_row(row)]
    pushed = []
    stop = ""
    for row in jobs:
        if not ledger.can(JOB_EVENT):
            stop = "maxSpendUsd"
            break
        try:
            await Actor.push_data(row)
        except Exception as exc:
            log.critical("Dataset push failed: %s", exc)
            stop = "pushFailed"
            break
        ledger.commit(JOB_EVENT)
        try:
            result = await Actor.charge(event_name=JOB_EVENT)
        except Exception as exc:
            log.critical("Job charge failed: %s", exc)
            stop = "chargeFailed"
            break
        pushed.append(row)
        if getattr(result, "event_charge_limit_reached", False):
            stop = "chargeLimit"
            break
    held = len(jobs) - len(pushed) - (1 if stop == "chargeFailed" else 0)
    if stop:
        log.critical("Job feed stopped (%s). %s job row(s) held back.", stop, held)
        others.append(_blank_row("spend_capped", CAP_MESSAGES[stop].format(held=held), iso_now(), decision="stopped"))
    for row in others:
        await Actor.push_data(row)
    return pushed, stop, held, len(others)


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
        pushed, stop, held, status_count = await push_jobs(rows, ledger)
        summary["found"] = len(pushed)
        summary["pushed"] = len(pushed) + status_count
        summary["newJobs"] = sum(1 for row in pushed if row.get("decision") == "new")
        summary["repeatJobs"] = sum(1 for row in pushed if row.get("decision") == "repeat")
        summary["billedJobs"] = ledger.counts.get(JOB_EVENT, 0)
        summary["spendUsd"] = ledger.spend_usd
        summary["chargeCapped"] = stop in ("maxSpendUsd", "chargeLimit")
        summary["heldBackJobs"] = held
        summary["truncated"] = bool(summary.get("truncated")) or held > 0
        if held:
            summary["stopped"] = summary.get("stopped") or stop
            if not pushed:
                summary["status"] = "spend_capped"
        pushed_keys = {_row_key(row) for row in pushed}
        new_seen = {key: first for key, first in new_seen.items() if key in pushed_keys}
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
