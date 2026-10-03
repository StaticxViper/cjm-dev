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
from utils.config import configured_locations, load_config  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find multi-location + remote jobs with potentially automatable workflows. "
            "Remote roles are prioritized by default."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Discover, analyze, and export opportunities")
    search.add_argument(
        "--south-nj",
        action="store_true",
        help="Limit local targeting to the south_jersey region (remote still included unless --no-remote)",
    )
    search.add_argument(
        "--remote",
        action="store_true",
        help="Search/filter for remote U.S. roles only",
    )
    search.add_argument(
        "--locations",
        type=str,
        default="",
        help=(
            "Comma-separated location region names from config.yaml "
            "(e.g. south_jersey,philadelphia_metro,delaware,north_jersey). "
            "Default: all enabled regions."
        ),
    )
    search.add_argument(
        "--prioritize-remote",
        action="store_true",
        default=None,
        help="Search and rank remote roles first (default from config, usually on)",
    )
    search.add_argument(
        "--no-prioritize-remote",
        action="store_true",
        help="Do not put remote phrases/jobs ahead of local ones",
    )
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
    logging.getLogger("opp-finder").setLevel(logging.DEBUG if args.verbose else logging.INFO)

    if args.command == "search":
        config = load_config(args.config)
        headless = None
        if args.headed:
            headless = False
        elif args.headless:
            headless = True

        region_names = [p.strip() for p in (args.locations or "").split(",") if p.strip()]
        available = {r["name"] for r in configured_locations(config)}
        unknown = [n for n in region_names if n not in available]
        if unknown:
            logger.error(
                "Unknown location region(s): %s. Available: %s",
                ", ".join(unknown),
                ", ".join(sorted(available)) or "(none)",
            )
            return 2

        # Default: all configured locations + remote included, remote prioritized.
        # --south-nj narrows local regions; --remote means remote-only.
        south_nj = bool(args.south_nj)
        remote_only = bool(args.remote) and not args.south_nj and not region_names
        if args.south_nj and args.remote:
            # Explicit south-nj + remote => keep south_jersey locals and remotes.
            south_nj = True
            remote_only = False
            if not region_names:
                region_names = ["south_jersey"]

        prioritize_remote = None
        if args.no_prioritize_remote:
            prioritize_remote = False
        elif args.prioritize_remote:
            prioritize_remote = True

        options = {
            "south_nj_only": south_nj,
            "remote_only": remote_only,
            "region_names": region_names,
            "prioritize_remote": prioritize_remote,
            "no_prioritize_remote": bool(args.no_prioritize_remote),
            "keyword": (args.keyword or "").strip(),
            "limit": args.limit or None,
            "headless": headless,
            "refresh": bool(args.refresh),
            "verbose": bool(args.verbose),
            "no_remote": bool(args.no_remote),
        }
        logger.info(
            "Starting search (regions=%s remote_only=%s prioritize_remote=%s limit=%s)",
            ",".join(region_names) or "all",
            options["remote_only"],
            prioritize_remote if prioritize_remote is not None else config.get("prioritize_remote", True),
            options["limit"] or (config.get("search") or {}).get("max_total_jobs"),
        )
        stats = run_search(config, options)
        logger.info("Finished: %s", stats)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
