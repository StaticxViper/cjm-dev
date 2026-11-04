"""Federal contract leads. Official SAM.gov and USAspending APIs. No browser, proxy, or CAPTCHA solver."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import _blank_row, _summarize, actor_input_to_config, billable_row, event_for, scrape
    from .runtime import iso_now
    from .sources import redact
    from .spend import AWARD_EVENT, OPPORTUNITY_EVENT, LeadLedger
except ImportError:
    from fetch import make_live_fetch
    from mapping import _blank_row, _summarize, actor_input_to_config, billable_row, event_for, scrape
    from runtime import iso_now
    from sources import redact
    from spend import AWARD_EVENT, OPPORTUNITY_EVENT, LeadLedger


log = logging.getLogger("apify")

CAP_MESSAGES = {
    "maxSpendUsd": "maxSpendUsd cannot cover the next lead. {held} matching lead(s) were not pushed.",
    "chargeLimit": "The run's platform charge limit was reached. {held} matching lead(s) were not pushed.",
    "pushFailed": "A dataset push failed. {held} matching lead(s) were not pushed.",
    "chargeFailed": "A charge failed after a lead was pushed. {held} matching lead(s) were not pushed.",
}


def run_sync(config):
    fetch = make_live_fetch(config)
    try:
        return scrape(config, fetch)
    finally:
        closer = getattr(fetch, "close", None)
        if closer:
            closer()


def _limit_reached(result):
    if isinstance(result, dict):
        return bool(result.get("event_charge_limit_reached"))
    return bool(getattr(result, "event_charge_limit_reached", False))


async def push_leads(rows, ledger):
    """Push each lead only when its charge fits, then the free status rows."""
    leads = [row for row in rows if billable_row(row)]
    others = [row for row in rows if not billable_row(row)]
    pushed = []
    stop = ""
    placed = 0
    for row in leads:
        event = event_for(row)
        if not ledger.fits([event]):
            stop = "maxSpendUsd"
            break
        try:
            await Actor.push_data(row)
        except Exception as exc:
            log.critical("Dataset push failed: %s", exc)
            stop = "pushFailed"
            break
        placed += 1
        ledger.commit(event)
        try:
            result = await Actor.charge(event_name=event)
        except Exception as exc:
            log.critical("%s charge failed: %s", event, exc)
            stop = "chargeFailed"
            pushed.append(row)
            break
        pushed.append(row)
        if _limit_reached(result):
            stop = "chargeLimit"
            break
    held = len(leads) - placed
    if stop:
        log.critical("Lead feed stopped (%s). %s lead row(s) held back.", stop, held)
        others.append(_blank_row(
            "spend_capped", CAP_MESSAGES[stop].format(held=held), iso_now(), decision="stopped",
        ))
    for row in others:
        await Actor.push_data(row)
    return pushed, stop, held, len(others)


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        config = actor_input_to_config(actor_input)
        try:
            rows, summary = await asyncio.to_thread(run_sync, config)
        except Exception as exc:
            log.critical("Federal contracts failed: %s", redact(f"{type(exc).__name__}: {exc}", config.get("sam_api_key")))
            rows = [_blank_row("error", "The run failed before it could finish.", iso_now())]
            summary = _summarize(rows, config, {}, [], "error", False, rows[0]["scrapedAt"])
        ledger = LeadLedger(config["max_spend_usd"])
        pushed, stop, held, status_count = await push_leads(rows, ledger)
        summary["found"] = len(pushed)
        summary["pushed"] = len(pushed) + status_count
        summary["billedOpportunities"] = ledger.counts.get(OPPORTUNITY_EVENT, 0)
        summary["billedAwards"] = ledger.counts.get(AWARD_EVENT, 0)
        summary["spendUsd"] = ledger.spend_usd
        summary["chargeCapped"] = stop in ("maxSpendUsd", "chargeLimit")
        summary["heldBack"] = held
        summary["truncated"] = bool(summary.get("truncated")) or held > 0
        if held or stop:
            summary["stopped"] = summary.get("stopped") or stop
        if held and not pushed:
            summary["status"] = "spend_capped"
        await Actor.set_value("SUMMARY", summary)
