"""App Store review Actor. Public iTunes JSON over HTTP. No browser, proxy, or CAPTCHA solver."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import _blank_row, _summarize, actor_input_to_config, billable_row, scrape
    from .runtime import iso_now
    from .spend import REVIEW_EVENT, SENTIMENT_EVENT, ReviewLedger
except ImportError:
    from fetch import make_live_fetch
    from mapping import _blank_row, _summarize, actor_input_to_config, billable_row, scrape
    from runtime import iso_now
    from spend import REVIEW_EVENT, SENTIMENT_EVENT, ReviewLedger


log = logging.getLogger("apify")

CAP_MESSAGES = {
    "maxSpendUsd": "maxSpendUsd cannot cover the next review. {held} matching review(s) were not pushed.",
    "chargeLimit": "The run's platform charge limit was reached. {held} matching review(s) were not pushed.",
    "pushFailed": "A dataset push failed. {held} matching review(s) were not pushed.",
    "chargeFailed": "A charge failed after a review was pushed. {held} matching review(s) were not pushed.",
}


def run_sync(config):
    fetch = make_live_fetch(config)
    try:
        return scrape(config, fetch)
    finally:
        closer = getattr(fetch, "close", None)
        if closer:
            closer()


def _events(sentiment_on):
    if sentiment_on:
        return (REVIEW_EVENT, SENTIMENT_EVENT)
    return (REVIEW_EVENT,)


async def push_reviews(rows, ledger, sentiment_on):
    """Push each review only when its charges fit, then the free status rows.

    A review is pushed only when the review charge and, when sentiment is on,
    the sentiment charge both fit under maxSpendUsd. If the sentiment charge
    fails after the review was pushed, the feed stops.
    """
    reviews = [row for row in rows if billable_row(row)]
    others = [row for row in rows if not billable_row(row)]
    pushed = []
    stop = ""
    placed = 0
    events = _events(sentiment_on)
    for row in reviews:
        if not ledger.fits(events):
            stop = "maxSpendUsd"
            break
        try:
            await Actor.push_data(row)
        except Exception as exc:
            log.critical("Dataset push failed: %s", exc)
            stop = "pushFailed"
            break
        placed += 1
        charged_review = False
        limit = False
        failed = False
        for event in events:
            ledger.commit(event)
            try:
                result = await Actor.charge(event_name=event)
            except Exception as exc:
                log.critical("%s charge failed: %s", event, exc)
                stop = "chargeFailed"
                failed = True
                break
            if event == REVIEW_EVENT:
                charged_review = True
            if getattr(result, "event_charge_limit_reached", False):
                limit = True
        if charged_review:
            pushed.append(row)
        if failed:
            break
        if limit:
            stop = "chargeLimit"
            break
    held = len(reviews) - placed
    if stop:
        log.critical("Review feed stopped (%s). %s review row(s) held back.", stop, held)
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
            log.critical("App reviews failed: %s", exc)
            rows = [_blank_row("error", str(exc), iso_now())]
            summary = _summarize(rows, config, {}, [], "error", False, rows[0]["scrapedAt"])
        ledger = ReviewLedger(config["max_spend_usd"])
        pushed, stop, held, status_count = await push_reviews(rows, ledger, config["sentiment"])
        summary["found"] = len(pushed)
        summary["pushed"] = len(pushed) + status_count
        summary["billedReviews"] = ledger.counts.get(REVIEW_EVENT, 0)
        summary["billedSentiment"] = ledger.counts.get(SENTIMENT_EVENT, 0)
        summary["spendUsd"] = ledger.spend_usd
        summary["chargeCapped"] = stop in ("maxSpendUsd", "chargeLimit")
        summary["heldBackReviews"] = held
        summary["truncated"] = bool(summary.get("truncated")) or held > 0
        if held or stop:
            summary["stopped"] = summary.get("stopped") or stop
        if held and not pushed:
            summary["status"] = "spend_capped"
        await Actor.set_value("SUMMARY", summary)
