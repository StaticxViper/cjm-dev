#!/usr/bin/env python3
"""
property_listing_gen.py

Zillow Property Listing Generator

Runs the Apify Zillow ZIP Code Search actor for one or more ZIP codes and
writes a JSON array of property listing URLs.

Run: python property_listing_gen.py
"""
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import argparse
import json
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from helper_scripts.api_manager import APIManager
from helper_scripts.utils.logger.logger import setup_logger

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_PATH = SCRIPT_DIR / "search_settings.json"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "property_urls.json"

APIFY_API_KEY = os.getenv("APIFY_API_KEY")
ZILLOW_ACTOR = "Zillow ZIP Search"  # maxcopell/zillow-zip-search

DEFAULT_SEARCH_INPUT = {
    "zipCodes": ["14010", "07306"],
    "priceMin": 100000,
    "priceMax": 400000,
    "daysOnZillow": "2",
    "forSaleByAgent": True,
    "forSaleByOwner": False,
    "forRent": False,
    "sold": False,
    "resultsLimit": 10,
}

URL_KEYS = ("propertyUrl", "detailUrl", "hdpUrl", "url")

logger = setup_logger(
    name="property-listing-gen",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)


def _apify_key_missing():
    if APIFY_API_KEY:
        return False
    logger.error("Please set APIFY_API_KEY in .env before running.")
    return True


def _iter_items(items):
    if items is None:
        return
    if isinstance(items, dict):
        nested = items.get("items")
        if isinstance(nested, list):
            items = nested
        else:
            items = [items]
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict):
            yield item


def _is_zillow_listing_url(url):
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host == "zillow.com" or host.endswith(".zillow.com")


def _first_url(item):
    for key in URL_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            url = value.strip()
            if url and _is_zillow_listing_url(url):
                return url
    return None


def extract_property_urls(items):
    """Return unique Zillow listing URLs in first-seen order."""
    urls = []
    seen = set()
    for item in _iter_items(items):
        url = _first_url(item)
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def normalize_search_input(data):
    """Validate actor input and coerce zipCodes to non-empty strings."""
    if not isinstance(data, dict):
        raise ValueError("Search input must be a JSON object.")

    out = dict(data)
    zip_codes = out.get("zipCodes")
    if isinstance(zip_codes, str):
        zip_codes = [zip_codes]
    if not isinstance(zip_codes, list) or not zip_codes:
        raise ValueError("zipCodes is required and must be a non-empty list.")

    cleaned = []
    for zip_code in zip_codes:
        text = str(zip_code).strip()
        if text:
            cleaned.append(text)
    if not cleaned:
        raise ValueError("zipCodes is required and must be a non-empty list.")

    out["zipCodes"] = cleaned
    return out


def load_search_input(path):
    """Load and validate actor input JSON from disk."""
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return normalize_search_input(data)


def save_property_urls(urls, json_path):
    """Write listing URLs atomically so a failed run cannot truncate the file."""
    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)
    logger.critical("Saved %d property URLs to %s", len(urls), path)


def resolve_search_input(args):
    """Build actor input from the settings file, then apply CLI overrides."""
    input_path = Path(args.input) if args.input else DEFAULT_INPUT_PATH
    if input_path.is_file():
        base = load_search_input(input_path)
        logger.info("Loaded search input from %s", input_path)
    else:
        if args.input:
            raise FileNotFoundError(f"Search input file not found: {input_path}")
        logger.info("No search settings file found; using built-in defaults.")
        base = dict(DEFAULT_SEARCH_INPUT)

    if args.zip_codes:
        base["zipCodes"] = args.zip_codes
    if args.price_min is not None:
        base["priceMin"] = args.price_min
    if args.price_max is not None:
        base["priceMax"] = args.price_max
    if args.days_on_zillow is not None:
        base["daysOnZillow"] = args.days_on_zillow
    if args.results_limit is not None:
        base["resultsLimit"] = args.results_limit
    if args.for_sale_by_agent is not None:
        base["forSaleByAgent"] = args.for_sale_by_agent
    if args.for_sale_by_owner is not None:
        base["forSaleByOwner"] = args.for_sale_by_owner
    if args.for_rent is not None:
        base["forRent"] = args.for_rent
    if args.sold is not None:
        base["sold"] = args.sold

    return normalize_search_input(base)


def run_search(search_input, api=None):
    """Run the Zillow ZIP Search actor and return listing URLs."""
    client = api or APIManager()
    logger.critical(
        "Starting Zillow ZIP search for %d zip code(s)",
        len(search_input["zipCodes"]),
    )
    items = client.run_apify(actor=ZILLOW_ACTOR, input=search_input) or []
    urls = extract_property_urls(items)
    logger.critical("Found %d property URLs", len(urls))
    return urls


def generate_listings(search_input, output_path, api=None):
    """Run a search and write the URL list. Returns the URLs written."""
    if api is None and _apify_key_missing():
        return []
    search_input = normalize_search_input(search_input)
    urls = run_search(search_input, api=api)
    save_property_urls(urls, output_path)
    return urls


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Search Zillow by ZIP code via Apify and write a JSON list of property URLs",
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_PATH),
        help=f"Actor input JSON (default {DEFAULT_INPUT_PATH.name})",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Where to write the URL list (default {DEFAULT_OUTPUT_PATH.name})",
    )
    parser.add_argument(
        "--zip-codes",
        nargs="+",
        help="ZIP codes to search (overrides --input)",
    )
    parser.add_argument("--price-min", type=int, help="Minimum listing price")
    parser.add_argument("--price-max", type=int, help="Maximum listing price")
    parser.add_argument(
        "--days-on-zillow",
        help="Max days listed (or days since sold when searching sold listings)",
    )
    parser.add_argument(
        "--results-limit",
        type=int,
        help="Maximum properties per ZIP code",
    )
    parser.add_argument(
        "--for-sale-by-agent",
        dest="for_sale_by_agent",
        action="store_true",
        help="Include agent listings",
    )
    parser.add_argument(
        "--no-for-sale-by-agent",
        dest="for_sale_by_agent",
        action="store_false",
        help="Exclude agent listings",
    )
    parser.add_argument(
        "--for-sale-by-owner",
        dest="for_sale_by_owner",
        action="store_true",
        help="Include owner listings",
    )
    parser.add_argument(
        "--no-for-sale-by-owner",
        dest="for_sale_by_owner",
        action="store_false",
        help="Exclude owner listings",
    )
    parser.add_argument(
        "--for-rent",
        dest="for_rent",
        action="store_true",
        help="Include rentals",
    )
    parser.add_argument(
        "--no-for-rent",
        dest="for_rent",
        action="store_false",
        help="Exclude rentals",
    )
    parser.add_argument(
        "--sold",
        dest="sold",
        action="store_true",
        help="Include recently sold listings",
    )
    parser.add_argument(
        "--no-sold",
        dest="sold",
        action="store_false",
        help="Exclude recently sold listings",
    )
    parser.set_defaults(
        for_sale_by_agent=None,
        for_sale_by_owner=None,
        for_rent=None,
        sold=None,
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if _apify_key_missing():
        return 1
    try:
        search_input = resolve_search_input(args)
        generate_listings(search_input, args.output_path)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        logger.error("%s", e)
        return 1
    except Exception as e:
        logger.error("Zillow ZIP search failed: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
