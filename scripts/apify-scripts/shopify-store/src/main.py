"""Shopify store Actor. Public catalog JSON over HTTP. No browser, proxy, or CAPTCHA solver."""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .fetch import make_live_fetch
    from .mapping import _blank_row, _summarize, actor_input_to_config, billable_event, scrape
    from .runtime import iso_now
    from .spend import PRODUCT_EVENT, STORE_EVENT, CatalogLedger
    from .state import STATE_KEY, dump_state, load_state, merge_state
except ImportError:
    from fetch import make_live_fetch
    from mapping import _blank_row, _summarize, actor_input_to_config, billable_event, scrape
    from runtime import iso_now
    from spend import PRODUCT_EVENT, STORE_EVENT, CatalogLedger
    from state import STATE_KEY, dump_state, load_state, merge_state


log = logging.getLogger("apify")

CAP_MESSAGES = {
    "maxSpendUsd": "maxSpendUsd cannot cover the next row. {held} product row(s) were not pushed.",
    "chargeLimit": "The run's platform charge limit was reached. {held} product row(s) were not pushed.",
    "pushFailed": "A dataset push failed. {held} product row(s) were not pushed.",
    "chargeFailed": "A charge failed after a row was pushed. {held} product row(s) were not pushed.",
}


def run_sync(config, prices):
    fetch = make_live_fetch(config)
    try:
        return scrape(config, fetch, prices=prices)
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


async def _push_and_charge(row, ledger, event):
    try:
        await Actor.push_data(row)
    except Exception as exc:
        log.critical("Dataset push failed: %s", exc)
        return "pushFailed"
    ledger.commit(event)
    try:
        result = await Actor.charge(event_name=event)
    except Exception as exc:
        log.critical("%s charge failed: %s", event, exc)
        return "chargeFailed"
    if getattr(result, "event_charge_limit_reached", False):
        return "chargeLimit"
    return "ok"


async def push_catalog(rows, ledger):
    """Push each store and product only when its own charge fits, then free status rows.

    A store profile is not pushed when the store charge does not fit, and neither
    are the products that follow it. Product rows stop at the first one that
    does not fit. Status rows, including blocked, are saved and not billed.
    """
    data = [row for row in rows if billable_event(row)]
    others = [row for row in rows if not billable_event(row)]
    pushed_products = []
    pushed_stores = []
    stop = ""
    index = 0
    while index < len(data) and not stop:
        row = data[index]
        event = billable_event(row)
        if not ledger.can(event):
            stop = "maxSpendUsd"
            break
        placed = await _push_and_charge(row, ledger, event)
        if placed == "pushFailed":
            stop = "pushFailed"
            break
        if placed == "chargeFailed":
            stop = "chargeFailed"
            break
        if event == STORE_EVENT:
            pushed_stores.append(row)
        else:
            pushed_products.append(row)
        index += 1
        if placed == "chargeLimit":
            stop = "chargeLimit"
            break
    held_start = index + 1 if stop == "chargeFailed" else index
    held = sum(1 for row in data[held_start:] if billable_event(row) == PRODUCT_EVENT)
    if stop:
        log.critical("Catalog feed stopped (%s). %s product row(s) held back.", stop, held)
        others.append(_blank_row(
            "spend_capped", CAP_MESSAGES[stop].format(held=held), iso_now(), decision="stopped",
        ))
    for row in others:
        await Actor.push_data(row)
    return pushed_products, pushed_stores, stop, held, len(others)


def _pushed_prices(new_prices, pushed_products):
    keep = {(row.get("store"), row.get("productId")) for row in pushed_products}
    selected = {}
    for key, record in (new_prices or {}).items():
        parts = str(key).split("|", 2)
        if len(parts) < 3:
            continue
        if (parts[0], parts[1]) in keep:
            selected[key] = record
    return selected


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        config = actor_input_to_config(actor_input)
        store, prices = await _open_state(config["state_store"])
        try:
            rows, summary, new_prices = await asyncio.to_thread(run_sync, config, prices)
        except Exception as exc:
            log.critical("Shopify store failed: %s", exc)
            rows = [_blank_row("error", str(exc), iso_now())]
            summary = _summarize(rows, config, {}, [], "error", False, rows[0]["scrapedAt"])
            new_prices = {}
        ledger = CatalogLedger(config["max_spend_usd"])
        pushed_products, pushed_stores, stop, held, status_count = await push_catalog(rows, ledger)
        summary["products"] = len(pushed_products)
        summary["stores"] = len(pushed_stores)
        summary["found"] = len(pushed_products) + len(pushed_stores)
        summary["pushed"] = summary["found"] + status_count
        summary["priceChanges"] = sum(1 for row in pushed_products if row.get("priceChanged") is True)
        summary["billedProducts"] = ledger.counts.get(PRODUCT_EVENT, 0)
        summary["billedStores"] = ledger.counts.get(STORE_EVENT, 0)
        summary["spendUsd"] = ledger.spend_usd
        summary["chargeCapped"] = stop in ("maxSpendUsd", "chargeLimit")
        summary["heldBackProducts"] = held
        summary["truncated"] = bool(summary.get("truncated")) or held > 0
        if held or stop:
            summary["stopped"] = summary.get("stopped") or stop
        if held and not pushed_products and not pushed_stores:
            summary["status"] = "spend_capped"
        selected = _pushed_prices(new_prices, pushed_products)
        if store is not None and selected:
            merged = merge_state(prices, selected)
            try:
                await store.set_value(STATE_KEY, dump_state(merged, iso_now()))
                summary["stateKeys"] = len(merged)
            except Exception as exc:
                log.critical("Could not save state store %s: %s", config["state_store"], exc)
                summary["stateError"] = str(exc)
        else:
            summary["stateKeys"] = len(prices)
            if store is None:
                summary["stateError"] = summary.get("stateError") or "state store unavailable"
        await Actor.set_value("SUMMARY", summary)
