#!/usr/bin/env python3
"""Job Automation Opportunity Finder — CLI entrypoint."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from helper_scripts.utils.logger.logger import setup_logger  # noqa: E402

from pipeline import run_search  # noqa: E402
from utils.config import load_config  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find South NJ + remote jobs with potentially automatable workflows.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Discover, analyze, and export opportunities")
    search.add_argument("--south-nj", action="store_true", help="Prioritize South/Central NJ targeting")
    search.add_argument("--remote", action="store_true", help="Search/filter for remote U.S. roles")
    search.add_argument("--keyword", type=str, default="", help="Single keyword override")
    search.add_argument("--limit", type=int, default=0, help="Max total jobs to collect")
    search.add_argument("--headless", action="store_true", default=None, help="Run browser headless")
    search.add_argument("--headed", action="store_true", help="Run browser headed")
    search.add_argument("--refresh", action="store_true", help="Reprocess jobs already in CSV")
    search.add_argument("--verbose", action="store_true", help="Verbose debug logging")
    search.add_argument(
        "--config",
        type=str,
        default=str(SCRIPT_DIR / "config.yaml"),
        help="Path to config.yaml",
    )
    search.add_argument(
        "--no-remote",
        action="store_true",
        help="Disable remote job inclusion for this run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    console_levels = ["INFO", "ERROR", "CRITICAL"]
    if args.verbose:
        console_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    logger = setup_logger(name="opp-finder", console_levels=console_levels)
    # Also configure module logger used across package
    logging.getLogger("opp-finder").setLevel(logging.DEBUG if args.verbose else logging.INFO)

    if args.command == "search":
        config = load_config(args.config)
        headless = None
        if args.headed:
            headless = False
        elif args.headless:
            headless = True

        # Default to south-nj + remote when no geo flags given
        south_nj = bool(args.south_nj) or (not args.remote and not args.south_nj)
        remote_only = bool(args.remote) and not args.south_nj
        if args.south_nj and args.remote:
            south_nj = True
            remote_only = False

        options = {
            "south_nj_only": south_nj,
            "remote_only": remote_only,
            "keyword": (args.keyword or "").strip(),
            "limit": args.limit or None,
            "headless": headless,
            "refresh": bool(args.refresh),
            "verbose": bool(args.verbose),
            "no_remote": bool(args.no_remote),
        }
        logger.info(
            "Starting search (south_nj=%s remote_only=%s limit=%s)",
            options["south_nj_only"],
            options["remote_only"],
            options["limit"] or (config.get("search") or {}).get("max_total_jobs"),
        )
        stats = run_search(config, options)
        logger.info("Finished: %s", stats)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
