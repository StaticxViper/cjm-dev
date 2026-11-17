"""Local government bid feed. Official open-data JSON only. No browser, proxy, or CAPTCHA solver."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import REVIEW_ASK, _summarize, actor_input_to_config, billable_row, scrape, status_row
    from .runtime import iso_now
    from .spend import OPPORTUNITY_EVENT, OpportunityLedger
    from .state import STATE_KEY, dump_state, load_state, merge_state, opportunity_key, state_is_readable
except ImportError:
    from fetch import make_live_fetch
    from mapping import REVIEW_ASK, _summarize, actor_input_to_config, billable_row, scrape, status_row
    from runtime import iso_now
    from spend import OPPORTUNITY_EVENT, OpportunityLedger
    from state import STATE_KEY, dump_state, load_state, merge_state, opportunity_key, state_is_readable


log = logging.getLogger("apify")

CAP_MESSAGES = {
    "maxSpendUsd": "maxSpendUsd cannot cover the next bid. {held} bid(s) were not pushed.",
    "chargeLimit": "The run's platform charge limit was reached. {held} bid(s) were not pushed.",
    "pushFailed": "A dataset push failed. {held} bid(s) were not pushed.",
    "chargeFailed": "A charge failed after a bid was pushed. {held} bid(s) were not pushed.",
}


def run_sync(config, seen):
    fetch = make_live_fetch(config)
    try:
        return scrape(config, fetch, seen=seen)
    finally:
        closer = getattr(fetch, "close", None)
        if closer:
            closer()


def _limit_reached(result):
    if isinstance(result, dict):
        return bool(result.get("event_charge_limit_reached"))
    return bool(getattr(result, "event_charge_limit_reached", False))


async def _open_state(name):
    """Return ``(store, seen, error)``. A missing record is a first run."""
    try:
        store = await Actor.open_key_value_store(name=name)
        raw = await store.get_value(STATE_KEY)
    except Exception as exc:
        log.critical("Could not open state store %s: %s", name, exc)
        return None, {}, str(exc) or type(exc).__name__
    if not state_is_readable(raw):
        log.critical("State store %s has an unreadable %s record.", name, STATE_KEY)
        return None, {}, f"unreadable {STATE_KEY} record"
    return store, load_state(raw), ""


async def push_bids(rows, ledger, stamp):
    """Push a bid only when its charge fits. Status rows are free."""
    bids = [row for row in rows if billable_row(row)]
    others = [row for row in rows if not billable_row(row)]
    pushed = []
    stop = ""
    placed = 0
    for row in bids:
        if not ledger.fits([OPPORTUNITY_EVENT]):
            stop = "maxSpendUsd"
            break
        try:
            await Actor.push_data(row)
        except Exception as exc:
            log.critical("Dataset push failed: %s", exc)
            stop = "pushFailed"
            break
        placed += 1
        try:
            result = await Actor.charge(event_name=OPPORTUNITY_EVENT)
        except Exception as exc:
            log.critical("opportunity charge failed: %s", exc)
            stop = "chargeFailed"
            break
        ledger.commit(OPPORTUNITY_EVENT)
        pushed.append(row)
        if _limit_reached(result):
            stop = "chargeLimit"
            break
    held = len(bids) - placed
    if stop:
        log.critical("Local bid feed stopped (%s). %s bid(s) held back.", stop, held)
        others.append(status_row(
            "", "spend_capped", CAP_MESSAGES[stop].format(held=held), stamp,
        ))
    for row in others:
        await Actor.push_data(row)
    return pushed, stop, held, len(others)


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        config = actor_input_to_config(actor_input)
        store, seen, state_error = await _open_state(config["state_store"])
        stamp = iso_now()
        if state_error and config["new_since_last_run"]:
            message = (
                f"newSinceLastRun could not read state store {config['state_store']}: {state_error}. "
                "No bids were fetched or billed, so earlier bids are not sent again."
            )
            row = status_row("", "error", message, stamp)
            summary = _summarize([row], [], config, 0, False, stamp)
            summary["status"] = "error"
            summary["errors"] = 1
            summary["stateError"] = state_error
            summary["found"] = 0
            summary["pushed"] = 1
            summary["billedOpportunities"] = 0
            summary["spendUsd"] = 0
            await Actor.push_data(row)
            await Actor.set_value("SUMMARY", summary)
            return
        active_seen = seen if config["new_since_last_run"] else None
        try:
            rows, summary = await asyncio.to_thread(run_sync, config, active_seen)
        except Exception as exc:
            log.critical("Local bids failed: %s", exc)
            rows = [status_row("", "error", "The run failed before it could finish.", stamp)]
            summary = _summarize(rows, [], config, 0, False, stamp)
            summary["status"] = "error"
            summary["errors"] = 1
        if state_error:
            summary["stateError"] = state_error
        ledger = OpportunityLedger(config["max_spend_usd"])
        pushed, stop, held, status_count = await push_bids(rows, ledger, stamp)
        summary["found"] = len(pushed)
        summary["pushed"] = len(pushed) + status_count
        summary["billedOpportunities"] = ledger.counts.get(OPPORTUNITY_EVENT, 0)
        summary["spendUsd"] = ledger.spend_usd
        summary["chargeCapped"] = stop in ("maxSpendUsd", "chargeLimit")
        summary["heldBack"] = held
        summary["truncated"] = bool(summary.get("truncated")) or held > 0
        if held or stop:
            summary["stopped"] = summary.get("stopped") or stop
        if held and not pushed and summary.get("status") == "ok":
            summary["status"] = "spend_capped"
        if ledger.counts.get(OPPORTUNITY_EVENT, 0):
            summary["reviewAsk"] = REVIEW_ASK
        fresh = iso_now()
        new_seen = {
            opportunity_key(row.get("source"), row.get("solicitationId")): fresh
            for row in pushed
        }
        if store is not None and new_seen:
            merged = merge_state(seen, new_seen)
            try:
                await store.set_value(STATE_KEY, dump_state(merged, fresh))
                summary["stateKeys"] = len(merged)
            except Exception as exc:
                log.critical("Could not save state store %s: %s", config["state_store"], exc)
                summary["stateError"] = str(exc)
                summary["stateKeys"] = len(seen)
        else:
            summary["stateKeys"] = len(seen)
        await Actor.set_value("SUMMARY", summary)
