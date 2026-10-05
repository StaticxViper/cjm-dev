"""Argument parsing for `python -m opp_finder_v2`."""

from __future__ import annotations

import argparse
import sys

from opp_finder_v2.config import (
    PACKAGE_DIR,
    ConfigError,
    format_site_table,
    load_criteria,
    load_sites,
)
from opp_finder_v2.models import RunOptions
from opp_finder_v2.pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opp_finder_v2",
        description="Find remote and contract job listings from configured boards.",
    )
    parser.add_argument("--config", default=str(PACKAGE_DIR / "sites.json"))
    parser.add_argument("--criteria", default=str(PACKAGE_DIR / "criteria.json"))
    parser.add_argument("--keywords", default=None, help="Comma-separated keywords; replaces keywords.any")
    parser.add_argument("--sites", default=None, help="Comma-separated site ids to run")
    parser.add_argument("--out", default=None, help="Output JSON path")
    parser.add_argument("--format", choices=("json", "csv", "both"), default="json")
    parser.add_argument("--dry-run", action="store_true", help="Read fixtures only; do not use the network")
    parser.add_argument("--headful", action="store_true", help="Show the browser")
    parser.add_argument("--max-per-site", type=int, default=None)
    parser.add_argument("--since-days", type=int, default=None)
    parser.add_argument("--allow-login", action="store_true")
    parser.add_argument("--no-artifacts", action="store_true")
    parser.add_argument("--list-sites", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def options_from_args(args: argparse.Namespace) -> RunOptions:
    from pathlib import Path

    return RunOptions(
        config_path=Path(args.config),
        criteria_path=Path(args.criteria),
        keywords=_split_csv(args.keywords),
        sites=_split_csv(args.sites),
        out=Path(args.out) if args.out else None,
        format=args.format,
        dry_run=bool(args.dry_run),
        headful=bool(args.headful),
        max_per_site=args.max_per_site,
        since_days=args.since_days,
        allow_login=bool(args.allow_login),
        no_artifacts=bool(args.no_artifacts),
        verbose=bool(args.verbose),
        list_sites=bool(args.list_sites),
        validate_only=bool(args.validate),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from helper_scripts.utils.logger.logger import setup_logger

    levels = ["INFO", "ERROR", "CRITICAL"]
    if args.verbose:
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    setup_logger(name="opp-finder-v2", console_levels=levels)

    options = options_from_args(args)
    try:
        catalog = load_sites(options.config_path)
        if options.list_sites:
            print(format_site_table(catalog))
            return 0
        if options.validate_only:
            load_criteria(options.criteria_path)
            print(f"valid: {options.config_path}")
            print(f"valid: {options.criteria_path}")
            return 0
        load_criteria(options.criteria_path)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        return run(options, catalog=catalog)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
