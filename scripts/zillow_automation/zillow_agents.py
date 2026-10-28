#!/usr/bin/env python3
"""
zillow_agents.py

Collect Zillow listings and listing agents with Playwright, then fill missing
emails and phones from Google and public agent or brokerage pages.

A block or captcha page stops that area and is recorded. This script does not
solve captchas, rotate proxies, or hide the browser. The Apify Actor can pass
one proxy into the browser; the CLI leaves that unset.

Run: python zillow_agents.py
     python zillow_agents.py --zip-codes 08002 --results-limit 25
"""
from pathlib import Path
import sys

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[1]
_SCRIPTS = _SCRIPT_DIR.parent
_LEAD = _SCRIPTS / "lead_automation"
for _entry in (_REPO_ROOT, _SCRIPTS, _LEAD, _SCRIPT_DIR):
    _text = str(_entry)
    if _text in sys.path:
        sys.path.remove(_text)
    sys.path.insert(0, _text)

import argparse
import asyncio
import csv
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

from helper_scripts.utils.logger.logger import setup_logger
from email_discovery import EmailDiscoverySession, is_google_block_page
from opp_finder_v2.browser.detection import classify_page
from opp_finder_v2.models import SiteConfig
from opp_finder_v2.politeness import Pacer, retry_delay

from zillow_enrich import enrich_agents
from zillow_parse import (
    AGENT_CSV_FIELDS,
    LISTING_CSV_FIELDS,
    Collection,
    agent_csv_row,
    build_search_url,
    criteria_hash,
    listing_csv_row,
    listing_id_from_url,
    normalize_address,
    normalize_criteria,
    output_paths,
    parse_listing_page,
    parse_search_page,
    search_areas,
)


logger = setup_logger(
    name="zillow-agents",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)

SCRIPT_DIR = _SCRIPT_DIR
DEFAULT_INPUT_PATH = SCRIPT_DIR / "search_settings.json"
DEFAULT_CHECKPOINT = SCRIPT_DIR / "zillow_agents_checkpoint.json"
DEFAULT_SEEN = SCRIPT_DIR / "zillow_seen.json"
DEFAULT_CACHE = SCRIPT_DIR / "zillow_agent_enrich_cache.json"

# Same resource types city_data_scraper blocks. Styles and scripts stay so the
# listing payload can render.
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
ZILLOW_CHALLENGE_PHRASES = ("press & hold", "press and hold", "are you a robot")
PAGE_TIMEOUT_MS = 30000
MAX_SEARCH_PAGES = 100
FETCH_ATTEMPTS = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def empty_stats():
    return {
        "listings_found": 0,
        "duplicates_skipped": 0,
        "agents_found": 0,
        "agents_enriched": 0,
        "blocked_pages": 0,
        "areas_completed": 0,
        "areas_blocked": 0,
    }


@dataclass
class FetchResult:
    url: str
    html: str = ""
    status: int | None = None
    final_url: str = ""
    blocked: bool = False
    error: str = ""


def is_blocked_page(url, html, status=None):
    """True for a captcha or block page. A normal listing page is not a block."""
    current = url or ""
    host = (urlparse(current).hostname or "").lower()
    if "google." in host and is_google_block_page(html, current):
        return True
    kind = classify_page(
        current,
        html or "",
        status,
        extra={"captcha_text": list(ZILLOW_CHALLENGE_PHRASES)},
    )
    return kind in {"captcha", "blocked"}


def as_fetch_result(url, result):
    if not isinstance(result, FetchResult):
        raise TypeError("fetch must return FetchResult")
    if not result.url:
        result.url = url
    if not result.final_url:
        result.final_url = result.url or url
    if not result.blocked and result.error != "already_blocked":
        result.blocked = is_blocked_page(result.final_url, result.html, result.status)
    return result


def _is_zillow(url):
    host = (urlparse(url or "").hostname or "").lower()
    return host == "zillow.com" or host.endswith(".zillow.com")


def _make_pacer(host):
    zillow = host == "zillow.com" or host.endswith(".zillow.com")
    cap = 100000 if zillow else 30
    site = SiteConfig.from_dict(
        {
            "id": host or "web",
            "name": host or "web",
            "enabled": True,
            "base_url": f"https://{host}" if host else "https://example.com",
            "mode": "browser",
            "access": "guest",
            "rate_limit": {
                "min_delay_s": 2.0,
                "max_delay_s": 4.5,
                "max_requests": cap,
                "max_results": cap,
            },
        }
    )
    return Pacer(site, sleep=lambda _seconds: None)


class HostPacer:
    """One Pacer per host. The delay runs outside the lock so hosts do not queue."""

    def __init__(self, sleep=None):
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._pacers = {}

    def acquire(self, url):
        host = (urlparse(url or "").hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        with self._lock:
            pacer = self._pacers.get(host)
            if pacer is None:
                pacer = _make_pacer(host)
                self._pacers[host] = pacer
            delay = {}

            def record(seconds):
                delay["seconds"] = seconds

            pacer._sleep = record
            allowed = pacer.acquire()
        seconds = delay.get("seconds") or 0
        if seconds:
            self._sleep(seconds)
        return allowed


def _abort_heavy_route(route):
    try:
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
            route.abort()
            return
        route.continue_()
    except Exception:
        return


def _stop_playwright(playwright):
    """Stop the driver after cancelled tasks have finished.

    Playwright's own stop() closes the event loop while its connection task is
    still cancelling. That prints TargetClosedError once the process exits.
    """
    manager = getattr(getattr(playwright, "stop", None), "__self__", None)
    if manager is not None and getattr(manager, "_exit_was_called", False):
        return
    impl = getattr(playwright, "_impl_obj", None)
    connection = getattr(impl, "_connection", None)
    loop = getattr(connection, "_loop", None) if connection is not None else None
    if connection is not None:
        original_cleanup = connection.cleanup

        def cleanup(cause=None):
            futures = [
                callback.future
                for callback in list(connection._callbacks.values())
                if not getattr(callback, "no_reply", False)
            ]
            original_cleanup(cause)
            for future in futures:
                if future.done() and not future.cancelled():
                    future.exception()

        connection.cleanup = cleanup
        try:
            connection.stop_sync()
        except Exception as exc:
            logger.error("Failed to stop Playwright connection: %s", exc)
    if loop is not None and not loop.is_closed():
        try:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception as exc:
            logger.error("Failed to drain Playwright tasks: %s", exc)
        try:
            if not loop.is_closed():
                loop.close()
        except Exception as exc:
            logger.error("Failed to close Playwright loop: %s", exc)
    if manager is not None:
        manager._exit_was_called = True


class _Slot:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None


class ZillowBrowser:
    """Playwright fetches with per-host pacing. Each worker owns its own browser.

    The sync Playwright API is not safe to share across threads, so a concurrency
    of 2 is two browsers, not two pages in one browser.
    """

    def __init__(self, concurrency=2, headless=True, timeout_ms=PAGE_TIMEOUT_MS, sleep=None, proxy=None):
        self.concurrency = max(1, int(concurrency or 1))
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.proxy = proxy or None
        self._sleep = sleep or time.sleep
        self._pacer = HostPacer(sleep=self._sleep)
        self._local = threading.local()
        self._slots = []
        self._slots_lock = threading.Lock()
        self._block_lock = threading.Lock()
        self._zillow_blocked = False

    def close(self):
        with self._slots_lock:
            slots = list(self._slots)
            self._slots = []
        self._local.slot = None
        for slot in slots:
            page = slot.page
            slot.page = None
            if page is not None:
                try:
                    page.unroute("**/*", _abort_heavy_route)
                except Exception:
                    pass
            browser = slot.browser
            slot.browser = None
            if browser is not None:
                try:
                    browser.close()
                except Exception as exc:
                    logger.error("Failed to close browser: %s", exc)
            playwright = slot.playwright
            slot.playwright = None
            if playwright is not None:
                _stop_playwright(playwright)

    def _mark_blocked(self):
        with self._block_lock:
            self._zillow_blocked = True

    def _blocked(self):
        with self._block_lock:
            return self._zillow_blocked

    def _slot(self):
        slot = getattr(self._local, "slot", None)
        if slot is not None and slot.page is not None:
            return slot
        from playwright.sync_api import sync_playwright

        slot = _Slot()
        slot.playwright = sync_playwright().start()
        launch_kwargs = {"headless": self.headless}
        if self.proxy:
            launch_kwargs["proxy"] = self.proxy
        slot.browser = slot.playwright.chromium.launch(**launch_kwargs)
        slot.page = slot.browser.new_page(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        slot.page.set_default_timeout(self.timeout_ms)
        slot.page.route("**/*", _abort_heavy_route)
        self._local.slot = slot
        with self._slots_lock:
            self._slots.append(slot)
        return slot

    def fetch(self, url):
        if _is_zillow(url) and self._blocked():
            return FetchResult(url=url, blocked=True, error="already_blocked")
        if not self._pacer.acquire(url):
            return FetchResult(url=url, error="rate_limit")
        try:
            page = self._slot().page
        except Exception as exc:
            return FetchResult(url=url, error=str(exc))
        last_error = ""
        for attempt in range(FETCH_ATTEMPTS):
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                status = response.status if response is not None else None
                html = page.content() or ""
                final = page.url or url
            except Exception as exc:
                last_error = str(exc)
                if attempt < FETCH_ATTEMPTS - 1:
                    self._sleep(retry_delay(attempt))
                    continue
                return FetchResult(url=url, error=last_error)
            if is_blocked_page(final, html, status):
                self._mark_blocked()
                return FetchResult(
                    url=url,
                    html=html,
                    status=status,
                    final_url=final,
                    blocked=True,
                )
            if status in RETRY_STATUSES and attempt < FETCH_ATTEMPTS - 1:
                self._sleep(retry_delay(attempt))
                continue
            return FetchResult(url=url, html=html, status=status, final_url=final)
        return FetchResult(url=url, error=last_error or "fetch failed")

    def map_fetch(self, urls):
        if not urls:
            return []
        workers = max(1, min(self.concurrency, len(urls)))
        try:
            if workers == 1:
                return [self.fetch(url) for url in urls]
            with ThreadPoolExecutor(max_workers=workers) as pool:
                return list(pool.map(self.fetch, urls))
        finally:
            # A block stops the current batch only. The next area is fetched on its own.
            with self._block_lock:
                self._zillow_blocked = False


def save_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def _save_csv_atomic(path, fieldnames, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    os.replace(tmp, path)


def _read_json(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def load_seen(path):
    payload = _read_json(path) if path else None
    payload = payload or {}
    return {
        "ids": {str(item) for item in (payload.get("ids") or []) if str(item).strip()},
        "addresses": {str(item) for item in (payload.get("addresses") or []) if str(item).strip()},
    }


def save_seen(path, seen):
    if not path:
        return
    save_json_atomic(
        path,
        {
            "ids": sorted(seen.get("ids") or []),
            "addresses": sorted(seen.get("addresses") or []),
        },
    )


def _blank_area():
    return {"status": "pending", "next_page": 1, "pending_urls": []}


def _checkpoint_path_for(path, digest):
    """Keep a checkpoint for different criteria instead of overwriting it."""
    if not path:
        return path
    path = Path(path)
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return path
    saved = payload.get("criteria_hash")
    if not saved or saved == digest:
        return path
    switched = path.with_name(f"{path.stem}_{digest}{path.suffix}")
    logger.info(
        "Checkpoint %s is for different criteria; using %s.",
        path.name,
        switched.name,
    )
    return switched


def load_checkpoint(path, criteria, resume):
    collection = Collection()
    stats = empty_stats()
    areas = {area: _blank_area() for area in search_areas(criteria)}
    digest = criteria_hash(criteria)
    if not resume or not path:
        return collection, stats, areas, digest
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return collection, stats, areas, digest
    if payload.get("criteria_hash") != digest:
        logger.info("Checkpoint at %s is for different criteria; starting over.", path)
        return collection, stats, areas, digest
    saved_stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    for key in stats:
        if key in saved_stats:
            stats[key] = saved_stats[key]
    saved_areas = payload.get("areas") if isinstance(payload.get("areas"), dict) else {}
    for area, state in saved_areas.items():
        if area not in areas or not isinstance(state, dict):
            continue
        areas[area] = {
            "status": state.get("status") or "pending",
            "next_page": int(state.get("next_page") or 1),
            "pending_urls": [str(url) for url in (state.get("pending_urls") or []) if url],
        }
    collection.load(payload)
    return collection, stats, areas, digest


def _checkpoint_payload(digest, criteria, areas, collection, stats):
    return {
        "version": 1,
        "criteria_hash": digest,
        "criteria": criteria,
        "areas": areas,
        "listings": collection.listings,
        "agents": collection.agents,
        "stats": stats,
    }


def _note_block(stats, url, area):
    stats["blocked_pages"] = int(stats.get("blocked_pages") or 0) + 1
    logger.error("Blocked page at %s; stopping area %s.", url, area)


def _consume_details(pending, fetch_many, collection, seen, stats, area, concurrency):
    blocked = False
    batch_size = max(1, int(concurrency or 1))
    while pending and not blocked:
        batch = list(pending[:batch_size])
        rest = list(pending[batch_size:])
        results = list(fetch_many(batch))
        while len(results) < len(batch):
            results.append(FetchResult(url=batch[len(results)], error="missing result"))
        leftover = []
        for index, (url, result) in enumerate(zip(batch, results)):
            result = as_fetch_result(url, result)
            if result.blocked:
                if result.error != "already_blocked":
                    _note_block(stats, result.final_url or url, area)
                blocked = True
                leftover = batch[index + 1 :]
                break
            if result.error and not result.html:
                logger.error("Fetch failed for %s: %s", url, result.error)
                continue
            listing = parse_listing_page(result.html, result.final_url or url)
            listing["area"] = area
            if not listing.get("listing_id"):
                listing["listing_id"] = listing_id_from_url(url)
            address_key = normalize_address(listing.get("address"))
            if (listing.get("listing_id") and listing["listing_id"] in seen["ids"]) or (
                address_key and address_key in seen["addresses"]
            ):
                stats["duplicates_skipped"] = int(stats.get("duplicates_skipped") or 0) + 1
                continue
            if collection.add(listing) == "duplicate":
                stats["duplicates_skipped"] = int(stats.get("duplicates_skipped") or 0) + 1
        pending = leftover + rest if blocked else rest
    return pending, blocked


def _search_urls(parsed, pending, seen, collection, stats, room):
    new_urls = []
    for item in parsed.get("listings") or []:
        if room is not None and len(new_urls) >= room:
            break
        listing_id = str(item.get("listing_id") or "")
        url = item.get("url") or ""
        if not url:
            continue
        if listing_id and (listing_id in seen["ids"] or collection.known(listing_id=listing_id)):
            stats["duplicates_skipped"] = int(stats.get("duplicates_skipped") or 0) + 1
            continue
        if url in pending or url in new_urls:
            continue
        new_urls.append(url)
    return new_urls


def run_pipeline(
    criteria,
    *,
    fetch,
    output_dir,
    checkpoint_path,
    seen_path,
    fetch_many=None,
    concurrency=2,
    cache_path=None,
    resume=True,
    enrich=True,
    enrich_fn=None,
    run_date=None,
    max_listings=None,
    max_agents=None,
    on_checkpoint=None,
    browser_proxy=None,
):
    """Search each area, dedupe, enrich missing contacts, and write JSON and CSV."""
    criteria = normalize_criteria(criteria)
    areas_list = search_areas(criteria)
    if fetch_many is None:
        def fetch_many(urls):
            return [fetch(url) for url in urls]

    digest = criteria_hash(criteria)
    checkpoint_path = _checkpoint_path_for(checkpoint_path, digest)
    collection, stats, areas, digest = load_checkpoint(checkpoint_path, criteria, resume)
    seen = load_seen(seen_path)
    limit = int(criteria.get("resultsLimit") or 0)
    total_cap = int(max_listings or 0)
    agent_cap = int(max_agents or 0)

    def listings_full():
        return total_cap > 0 and len(collection.listings) >= total_cap

    def agents_full():
        return agent_cap > 0 and len(collection.agents) >= agent_cap

    def capped():
        return listings_full() or agents_full()

    def save_checkpoint():
        payload = _checkpoint_payload(digest, criteria, areas, collection, stats)
        if checkpoint_path:
            save_json_atomic(checkpoint_path, payload)
        if on_checkpoint is not None:
            on_checkpoint(payload)

    def consume_within_cap(pending_urls):
        """Fetch only as many pending listings as the total cap still allows."""
        if agents_full():
            return list(pending_urls), False
        pending_urls = list(pending_urls)
        if total_cap > 0:
            room = max(0, total_cap - len(collection.listings))
            take, tail = pending_urls[:room], pending_urls[room:]
        else:
            take, tail = pending_urls, []
        if not take:
            return tail, False
        leftover, blocked_now = _consume_details(
            take, fetch_many, collection, seen, stats, area, concurrency
        )
        return leftover + tail, blocked_now

    for area in areas_list:
        if capped():
            break
        state = areas.get(area) or _blank_area()
        if state.get("status") == "done":
            areas[area] = state
            continue
        pending = list(state.get("pending_urls") or [])
        page_num = max(1, int(state.get("next_page") or 1))
        blocked = False
        failed = False

        def area_count(current=area):
            return sum(1 for item in collection.listings if item.get("area") == current)

        if pending:
            pending, blocked = consume_within_cap(pending)
            state["pending_urls"] = pending
            state["status"] = "blocked" if blocked else "in_progress"
            areas[area] = state
            save_checkpoint()

        while not blocked and not failed and not capped() and page_num <= MAX_SEARCH_PAGES:
            if limit > 0 and area_count() >= limit:
                break
            search_url = build_search_url(area, criteria, page_num)
            fetched = list(fetch_many([search_url]) or [])
            if not fetched:
                logger.error("Fetch failed for %s: missing result", search_url)
                failed = True
                break
            result = as_fetch_result(search_url, fetched[0])
            if result.blocked:
                if result.error != "already_blocked":
                    _note_block(stats, result.final_url or search_url, area)
                blocked = True
                break
            if result.error and not result.html:
                logger.error("Fetch failed for %s: %s", search_url, result.error)
                failed = True
                break
            parsed = parse_search_page(result.html)
            room_parts = []
            if limit > 0:
                room_parts.append(max(0, limit - area_count() - len(pending)))
            if total_cap > 0:
                room_parts.append(max(0, total_cap - len(collection.listings) - len(pending)))
            room = min(room_parts) if room_parts else None
            if room == 0:
                break
            new_urls = _search_urls(parsed, pending, seen, collection, stats, room)
            pending.extend(new_urls)
            page_num += 1
            state["next_page"] = page_num
            state["pending_urls"] = pending
            state["status"] = "in_progress"
            areas[area] = state
            save_checkpoint()
            if pending:
                pending, blocked = consume_within_cap(pending)
                state["pending_urls"] = pending
                areas[area] = state
                save_checkpoint()
            if blocked or not parsed.get("has_next") or not parsed.get("listings") or capped():
                break
            if limit > 0 and area_count() >= limit:
                break

        if blocked:
            state["status"] = "blocked"
        elif failed or capped() or pending:
            state["status"] = "in_progress"
        else:
            state["status"] = "done"
        state["pending_urls"] = pending
        areas[area] = state
        save_checkpoint()

    if agent_cap > 0 and len(collection.agents) > agent_cap:
        collection.agents = collection.agents[:agent_cap]

    if enrich_fn is not None:
        stats["agents_enriched"] = int(stats.get("agents_enriched") or 0) + int(
            enrich_fn(collection.agents) or 0
        )
    elif enrich and collection.agents:
        session = EmailDiscoverySession(
            cache_path=str(cache_path) if cache_path else None,
            proxy=browser_proxy,
        )
        visit_pacer = HostPacer()

        def before_visit(url):
            return visit_pacer.acquire(url)

        try:
            stats["agents_enriched"] = int(stats.get("agents_enriched") or 0) + enrich_agents(
                collection.agents,
                session,
                before_visit=before_visit,
            )
        finally:
            session.close()
        save_checkpoint()

    stats["listings_found"] = len(collection.listings)
    stats["agents_found"] = len(collection.agents)
    stats["areas_completed"] = sum(1 for state in areas.values() if state.get("status") == "done")
    stats["areas_blocked"] = sum(1 for state in areas.values() if state.get("status") == "blocked")
    run = dict(stats)
    run["areas"] = {area: state.get("status") for area, state in areas.items()}
    stamp = run_date or datetime.now().strftime("%Y-%m-%d")
    paths = output_paths(output_dir, stamp, areas_list)
    save_json_atomic(paths["agents_json"], {"run": run, "agents": collection.agents})
    save_json_atomic(paths["listings_json"], {"run": run, "listings": collection.listings})
    _save_csv_atomic(paths["agents_csv"], AGENT_CSV_FIELDS, [agent_csv_row(agent) for agent in collection.agents])
    _save_csv_atomic(
        paths["listings_csv"],
        LISTING_CSV_FIELDS,
        [listing_csv_row(listing) for listing in collection.listings],
    )
    for listing in collection.listings:
        if listing.get("listing_id"):
            seen["ids"].add(str(listing["listing_id"]))
        address_key = normalize_address(listing.get("address"))
        if address_key:
            seen["addresses"].add(address_key)
    save_seen(seen_path, seen)
    save_checkpoint()
    logger.info(
        "listings_found=%s duplicates_skipped=%s agents_found=%s agents_enriched=%s "
        "blocked_pages=%s areas_completed=%s areas_blocked=%s",
        stats["listings_found"],
        stats["duplicates_skipped"],
        stats["agents_found"],
        stats["agents_enriched"],
        stats["blocked_pages"],
        stats["areas_completed"],
        stats["areas_blocked"],
    )
    logger.info("Wrote %s", paths["agents_json"])
    return {"stats": stats, "paths": paths, "areas": areas, "run": run}


def load_criteria_file(path):
    path = Path(path)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return normalize_criteria(data)


def resolve_criteria(args):
    """Load the settings file, then apply CLI overrides."""
    input_path = Path(args.input) if args.input else DEFAULT_INPUT_PATH
    if input_path.is_file():
        criteria = load_criteria_file(input_path)
        logger.info("Loaded search input from %s", input_path)
    else:
        if args.input and Path(args.input) != DEFAULT_INPUT_PATH:
            raise FileNotFoundError(f"Search input file not found: {input_path}")
        criteria = normalize_criteria(
            {
                "zipCodes": ["08002"],
                "priceMin": 100000,
                "priceMax": 500000,
                "forSaleByAgent": True,
                "forSaleByOwner": False,
                "forRent": False,
                "sold": False,
                "resultsLimit": 100,
            }
        )
    if args.zip_codes:
        criteria["zipCodes"] = [str(code).strip() for code in args.zip_codes if str(code).strip()]
    if args.areas:
        criteria["areas"] = [str(area).strip() for area in args.areas if str(area).strip()]
    if args.price_min is not None:
        criteria["priceMin"] = args.price_min
    if args.price_max is not None:
        criteria["priceMax"] = args.price_max
    if args.beds_min is not None:
        criteria["bedsMin"] = args.beds_min
    if args.baths_min is not None:
        criteria["bathsMin"] = args.baths_min
    if args.home_types:
        criteria["homeTypes"] = list(args.home_types)
    if args.days_on_zillow is not None:
        criteria["daysOnZillow"] = args.days_on_zillow
    if args.results_limit is not None:
        criteria["resultsLimit"] = args.results_limit
    if args.for_sale_by_agent is not None:
        criteria["forSaleByAgent"] = args.for_sale_by_agent
    if args.for_sale_by_owner is not None:
        criteria["forSaleByOwner"] = args.for_sale_by_owner
    if args.for_rent is not None:
        criteria["forRent"] = args.for_rent
    if args.sold is not None:
        criteria["sold"] = args.sold
    return normalize_criteria(criteria)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Collect Zillow listing agents with Playwright and enrich missing contact fields",
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH), help="Search criteria JSON")
    parser.add_argument("--output-dir", default=str(SCRIPT_DIR), help="Directory for JSON and CSV output")
    parser.add_argument("--zip-codes", nargs="+", help="ZIP codes to search (overrides the file)")
    parser.add_argument("--areas", nargs="+", help="Cities, counties, or other area strings")
    parser.add_argument("--price-min", type=int, help="Minimum listing price")
    parser.add_argument("--price-max", type=int, help="Maximum listing price")
    parser.add_argument("--beds-min", type=int, help="Minimum bedrooms")
    parser.add_argument("--baths-min", type=int, help="Minimum bathrooms")
    parser.add_argument("--home-types", nargs="+", help="house, condo, townhouse, multi, manufactured, land, apartment")
    parser.add_argument("--days-on-zillow", help="Maximum days on Zillow")
    parser.add_argument("--results-limit", type=int, help="Maximum listings per area (0 means no cap)")
    parser.add_argument("--for-sale-by-agent", dest="for_sale_by_agent", action="store_true")
    parser.add_argument("--no-for-sale-by-agent", dest="for_sale_by_agent", action="store_false")
    parser.add_argument("--for-sale-by-owner", dest="for_sale_by_owner", action="store_true")
    parser.add_argument("--no-for-sale-by-owner", dest="for_sale_by_owner", action="store_false")
    parser.add_argument("--for-rent", dest="for_rent", action="store_true")
    parser.add_argument("--no-for-rent", dest="for_rent", action="store_false")
    parser.add_argument("--sold", dest="sold", action="store_true")
    parser.add_argument("--no-sold", dest="sold", action="store_false")
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT), help="Resume file")
    parser.add_argument("--seen", default=str(DEFAULT_SEEN), help="Listing ids already collected")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE), help="Agent enrichment cache")
    parser.add_argument("--resume", action="store_true", help="Continue a matching checkpoint (this is the default)")
    parser.add_argument("--fresh", action="store_true", help="Ignore the checkpoint and start this criteria over")
    parser.add_argument("--no-enrich", action="store_true", help="Skip Google and website enrichment")
    parser.add_argument("--concurrency", type=int, default=2, help="Listing-page workers (default 2)")
    parser.add_argument("--headed", action="store_true", help="Show the browser")
    parser.add_argument("--run-date", help="Date stamp for output file names (YYYY-MM-DD)")
    parser.set_defaults(
        for_sale_by_agent=None,
        for_sale_by_owner=None,
        for_rent=None,
        sold=None,
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        criteria = resolve_criteria(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("%s", exc)
        return 1
    browser = ZillowBrowser(concurrency=max(1, args.concurrency or 1), headless=not args.headed)
    try:
        run_pipeline(
            criteria,
            fetch=browser.fetch,
            fetch_many=browser.map_fetch,
            concurrency=max(1, args.concurrency or 1),
            output_dir=args.output_dir,
            checkpoint_path=args.checkpoint,
            seen_path=args.seen,
            cache_path=args.cache,
            resume=not args.fresh,
            enrich=not args.no_enrich,
            run_date=args.run_date,
        )
    except Exception as exc:
        logger.error("Zillow agent run failed: %s", exc)
        return 1
    finally:
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
