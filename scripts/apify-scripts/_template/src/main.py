"""Skeleton entry. Copy _template/ and replace this module."""

from __future__ import annotations

import asyncio

from apify import Actor

try:
    from .runtime import (
        AccessPolicy,
        SpendLedger,
        access_summary,
        build_proxy_input,
        iso_now,
        read_access_settings,
    )
except ImportError:
    from runtime import (
        AccessPolicy,
        SpendLedger,
        access_summary,
        build_proxy_input,
        iso_now,
        read_access_settings,
    )


def run_sync(actor_input):
    """Sync body. Real Actors call Playwright inside this function via to_thread.

    The skeleton does not fetch. It records the spend caps and the proxy
    configuration a block would turn on, with spend at zero.
    """
    actor_input = actor_input or {}
    headless = True if actor_input.get("headless") is None else bool(actor_input.get("headless"))
    access = read_access_settings(actor_input)
    ledger = SpendLedger(access["max_spend_usd"], access["max_proxy_usd"], access["prices_usd"])
    row = {
        "ok": False,
        "sourceStatus": "error",
        "decision": "error",
        "error": "This folder is the Actor skeleton. Copy it and replace src/main.py.",
        "headless": headless,
        "scrapedAt": iso_now(),
    }
    summary = {
        "status": "template",
        "pushed": 1,
        "blocked": 0,
        "errors": 1,
        "spend": access_summary(access, ledger),
        "proxyOnBlock": build_proxy_input(access, escalate=True),
    }
    # AccessPolicy is the run gate copied Actors call after a real block.
    summary["allowCaptcha"] = AccessPolicy(access).allow_captcha
    return [row], summary


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        try:
            rows, summary = await asyncio.to_thread(run_sync, actor_input)
        except Exception as exc:
            rows = [{
                "ok": False,
                "sourceStatus": "error",
                "decision": "error",
                "error": str(exc),
                "scrapedAt": iso_now(),
            }]
            summary = {"status": "error", "pushed": 1, "error": str(exc)}
        for row in rows:
            await Actor.push_data(row)
        await Actor.set_value("SUMMARY", summary)
