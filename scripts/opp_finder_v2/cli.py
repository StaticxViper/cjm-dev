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
from opp_finder_v2.menu import load_skills, run_menu
from opp_finder_v2.models import RunOptions
from opp_finder_v2.pipeline import run
from opp_finder_v2.presets import find_preset, load_presets, setup_from_preset
from opp_finder_v2.search_setup import EMPLOYMENT_TYPES, apply_setup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opp_finder_v2",
        description="Find job listings from configured boards. With no flags, opens a menu.",
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
    parser.add_argument("--menu", action="store_true", help="Open the search menu")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Search immediately with criteria.json and upload matches to the CRM",
    )
    parser.add_argument("--preset", default=None, help="Run a saved preset by name or id")
    parser.add_argument(
        "--employment",
        choices=tuple(EMPLOYMENT_TYPES),
        default=None,
        help="part_time, full_time, contract, or any",
    )
    parser.add_argument("--remote-only", action="store_true", help="Keep remote listings only")
    parser.add_argument("--no-remote", action="store_true", help="Keep remote and on-site listings")
    parser.add_argument("--any-keyword", action="store_true", help="Do not filter on keywords")
    parser.add_argument(
        "--no-crm",
        action="store_true",
        help="Do not upload matches to the CRM MCP server",
    )
    parser.add_argument(
        "--crm-venture",
        default="Side Job Leads",
        help="CRM venture name, slug, or id for the upload",
    )
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
        keywords=[] if args.any_keyword else _split_csv(args.keywords),
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
        upload_crm=not args.dry_run and not args.no_crm,
        crm_venture=args.crm_venture,
        employment_types=list(EMPLOYMENT_TYPES[args.employment]) if args.employment else None,
        remote_only=False if args.no_remote else (True if args.remote_only else None),
        min_relevance=15 if args.any_keyword else None,
    )


def _explicit_search(args: argparse.Namespace) -> bool:
    return any(
        [
            args.keywords,
            args.sites,
            args.dry_run,
            args.out,
            args.preset,
            args.run,
            args.employment,
            args.any_keyword,
            args.no_remote,
            args.remote_only,
            args.no_crm,
            args.list_sites,
            args.validate,
            args.max_per_site is not None,
            args.since_days is not None,
        ]
    )


def _open_menu(args: argparse.Namespace) -> bool:
    if args.list_sites or args.validate:
        return False
    if args.menu:
        return True
    if _explicit_search(args):
        return False
    return sys.stdin.isatty()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from helper_scripts.utils.logger.logger import setup_logger

    levels = ["INFO", "ERROR", "CRITICAL"]
    if args.verbose:
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    setup_logger(name="opp-finder-v2", console_levels=levels)

    options = options_from_args(args)
    setup = None
    criteria = None
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
        criteria = load_criteria(options.criteria_path)
        if _open_menu(args):
            setup = run_menu()
            if setup is None:
                return 0
        elif args.preset:
            setup = setup_from_preset(find_preset(load_presets(), args.preset))
        if setup is not None:
            if setup.keyword_mode == "skills" and not setup.skill_ids:
                print("No skills are turned on. Toggle skills in the menu, or type keywords.")
                return 2
            apply_setup(criteria, setup, load_skills())
            options.batch_label = setup.name
            options.upload_crm = options.upload_crm and setup.upload_crm
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        return run(options, catalog=catalog, criteria=criteria)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
