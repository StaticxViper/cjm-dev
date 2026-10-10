"""Skeleton entry. Copy _template/ and replace this module."""

from __future__ import annotations

import asyncio

from apify import Actor

try:
    from .runtime import iso_now, unused_proxy_note
except ImportError:
    from runtime import iso_now, unused_proxy_note


def run_sync(actor_input):
    """Sync body. Real Actors call Playwright inside this function via to_thread."""
    actor_input = actor_input or {}
    headless = True if actor_input.get("headless") is None else bool(actor_input.get("headless"))
    row = {
        "ok": False,
        "sourceStatus": "error",
        "decision": "error",
        "error": "This folder is the Actor skeleton. Copy it and replace src/main.py.",
        "headless": headless,
        "scrapedAt": iso_now(),
    }
    summary = {"status": "template", "pushed": 1, "blocked": 0, "errors": 1}
    note = unused_proxy_note(actor_input)
    if note:
        summary["proxy"] = note
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
