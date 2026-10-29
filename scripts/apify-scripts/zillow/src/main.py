"""Zillow listing-agent Actor.

On Apify, Zillow pages are HTTP requests through Actor.create_proxy_configuration.
A blocked response is retried once on a second residential session. A local
run uses the same input and does not open a proxy. Dataset rows are
agents. LISTINGS and SUMMARY go to the default key-value store. CHECKPOINT
is rewritten after each search page so a migrated run can resume.
"""

from __future__ import annotations

import asyncio
import logging

from apify import Actor

try:
    from .pipeline import (
        CHECKPOINT_KEY,
        LISTINGS_KEY,
        SUMMARY_KEY,
        billable_row,
        on_platform,
        open_http_proxy_urls,
        proxy_actor_input,
        run_collected,
        seed_checkpoint,
        checkpoint_file,
        run_output_dir,
    )
    from .runtime import push_charged_rows
except ImportError:
    from pipeline import (
        CHECKPOINT_KEY,
        LISTINGS_KEY,
        SUMMARY_KEY,
        billable_row,
        on_platform,
        open_http_proxy_urls,
        proxy_actor_input,
        run_collected,
        seed_checkpoint,
        checkpoint_file,
        run_output_dir,
    )
    from runtime import push_charged_rows


log = logging.getLogger("apify")


class _Checkpoint:
    """Flush the latest pipeline payload onto the Actor event loop."""

    def __init__(self, loop):
        self.loop = loop
        self.payload = None

    def save(self, payload):
        self.payload = payload
        future = asyncio.run_coroutine_threadsafe(self.write(payload), self.loop)
        future.result(timeout=120)

    async def write(self, payload):
        await Actor.set_value(CHECKPOINT_KEY, payload)

    async def persist(self, _event=None):
        if self.payload is not None:
            await self.write(self.payload)


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        at_home = on_platform()
        try:
            proxy_urls = await open_http_proxy_urls(Actor, actor_input, at_home=at_home)
        except Exception as exc:
            log.critical("Zillow proxy setup failed: %s", exc)
            summary = {
                "listings_found": 0,
                "agents_found": 0,
                "agents_enriched": 0,
                "blocked_zips": [],
                "error": str(exc),
            }
            await Actor.set_value(SUMMARY_KEY, summary)
            raise RuntimeError(str(exc)) from exc
        if at_home:
            groups = ",".join(proxy_actor_input(actor_input)["apifyProxyGroups"])
            log.info(
                "Zillow requests use HTTP through Apify Proxy group %s. "
                "One spare session is reserved for a single retry.",
                groups,
            )
        else:
            log.info("Local run. Zillow requests are direct.")

        output_dir = run_output_dir(at_home)
        checkpoint_path = checkpoint_file(at_home, output_dir)
        saved = await Actor.get_value(CHECKPOINT_KEY)
        if seed_checkpoint(checkpoint_path, saved):
            log.info("Resuming from the key-value checkpoint.")

        loop = asyncio.get_running_loop()
        store = _Checkpoint(loop)
        try:
            from apify import Event

            Actor.on(Event.PERSIST_STATE, store.persist)
        except Exception as exc:
            log.info("Persist-state hook was not registered: %s", exc)

        try:
            collected = await asyncio.to_thread(
                run_collected,
                actor_input,
                proxy_urls=proxy_urls,
                output_dir=output_dir,
                checkpoint_path=checkpoint_path,
                on_checkpoint=store.save,
                at_home=at_home,
            )
        except Exception as exc:
            log.critical("Zillow agent run failed: %s", exc)
            summary = {
                "listings_found": 0,
                "agents_found": 0,
                "agents_enriched": 0,
                "blocked_zips": [],
                "error": str(exc),
            }
            await Actor.set_value(SUMMARY_KEY, summary)
            if store.payload is not None:
                await store.write(store.payload)
            raise RuntimeError(str(exc)) from exc

        rows = collected["rows"]
        await push_charged_rows(rows, billable_row)
        await Actor.set_value(LISTINGS_KEY, collected["listings"])
        await Actor.set_value(SUMMARY_KEY, collected["summary"])
        if store.payload is not None:
            await store.write(store.payload)
        log.info(
            "listings_found=%s agents_found=%s agents_enriched=%s blocked_zips=%s",
            collected["summary"].get("listings_found"),
            collected["summary"].get("agents_found"),
            collected["summary"].get("agents_enriched"),
            ",".join(collected["summary"].get("blocked_zips") or []),
        )
