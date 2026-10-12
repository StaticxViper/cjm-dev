"""Local grocery lookup queue. Writes prices with the service role and does not call edge functions."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    _SCRIPTS = Path(__file__).resolve().parents[1]
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))

from grocery.config import ConfigError, Settings, load_settings
from grocery.db import GroceryDB
from grocery.lookup import format_pending_header, format_status_line, lookup_link
from grocery.sync import SyncError, build_scraper, open_session

_STORES = ("shoprite", "costco", "amazon")


def connect_client(settings: Settings):
    if not settings.supabase_url or not settings.service_role_key:
        raise ConfigError("Missing SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY")
    from supabase import create_client

    return create_client(settings.supabase_url, settings.service_role_key)


class LookupRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.sessions: dict = {}
        self.scrapers: dict = {}

    def scraper_for(self, provider: str):
        if provider not in _STORES:
            raise ConfigError(f"unsupported store: {provider}")
        if provider not in self.scrapers:
            self.sessions[provider] = open_session(self.settings, headless=True, provider=provider)
            self.scrapers[provider] = build_scraper(provider, self.sessions[provider], self.settings)
        return self.scrapers[provider]

    def lookup(self, link: dict) -> dict:
        return lookup_link(link, self.scraper_for)

    def close(self) -> None:
        for session in self.sessions.values():
            session.close()
        self.sessions.clear()
        self.scrapers.clear()


def render_rows(when: datetime, pairs: list[tuple[dict, dict]], *, mention_pending: bool) -> list[str]:
    if not pairs:
        return []
    lines: list[str] = []
    count = len(pairs)
    if mention_pending and count > 1:
        lines.append(format_pending_header(when, count))
    for link, outcome in pairs:
        pending_count = count if mention_pending and count == 1 else None
        lines.append(format_status_line(when, link, outcome, pending_count=pending_count))
    return lines


def process_rows(rows: list[dict], lookup, db: GroceryDB, *, now: datetime, mention_pending: bool) -> tuple[list[str], int]:
    pairs = []
    failed = 0
    for link in rows:
        outcome = lookup(link)
        db.apply_outcome(link, outcome, now=now)
        pairs.append((link, outcome))
        if outcome.get("status") == "failed":
            failed += 1
    return render_rows(now, pairs, mention_pending=mention_pending), failed


def listen_loop(fetch_pending, handle_rows, *, poll_seconds: float, sleep, max_cycles: int | None = None) -> None:
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        handle_rows(fetch_pending())
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            return
        sleep(poll_seconds)


def run_listen(db: GroceryDB, runner: LookupRunner, *, poll_seconds: float, sleep=time.sleep) -> int:
    def handle(rows: list[dict]) -> None:
        if not rows:
            return
        lines, _failed = process_rows(rows, runner.lookup, db, now=datetime.now().astimezone(), mention_pending=True)
        for line in lines:
            print(line)

    try:
        listen_loop(db.fetch_pending, handle, poll_seconds=poll_seconds, sleep=sleep)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def run_rows(rows: list[dict], runner: LookupRunner, db: GroceryDB, *, mention_pending: bool) -> int:
    if not rows:
        return 0
    lines, failed = process_rows(
        rows,
        runner.lookup,
        db,
        now=datetime.now().astimezone(),
        mention_pending=mention_pending,
    )
    for line in lines:
        print(line)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grocery.scraper",
        description="Look up grocery prices locally and write them to Supabase.",
    )
    parser.add_argument("--listen", action="store_true", help="Poll for check_status=pending every 10 seconds")
    parser.add_argument("--item", help="Scrape every store link for one shopping_items id")
    parser.add_argument("--all", action="store_true", help="Re-check every linked master-list item")
    parser.add_argument(
        "--set-shoprite-store",
        action="store_true",
        help="Open ShopRite, wait for you to pick a store, and save the browser session",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.set_shoprite_store:
            from grocery.sync import run_set_store

            return run_set_store(load_settings(require_supabase=False))
        if not args.listen and not args.item and not args.all:
            print("Choose --listen, --item, or --all.", file=sys.stderr)
            return 2
        settings = load_settings(require_supabase=False)
        db = GroceryDB(connect_client(settings))
        runner = LookupRunner(settings)
        try:
            if args.listen:
                return run_listen(db, runner, poll_seconds=settings.poll_seconds)
            if args.item:
                rows = db.fetch_item(args.item)
                if not rows:
                    print(f"No store links for item {args.item}.", file=sys.stderr)
                    return 1
                return run_rows(rows, runner, db, mention_pending=False)
            return run_rows(db.fetch_all(), runner, db, mention_pending=False)
        finally:
            runner.close()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SyncError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
