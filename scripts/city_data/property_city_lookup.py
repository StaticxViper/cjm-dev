#!/usr/bin/env python3
"""
property_city_lookup.py

Resolve a US property address to city/state, scrape city-data.com demographics
and crime via city_data_scraper, and emit a single-address API envelope.

Run: python property_city_lookup.py --address "123 Main St, Clementon, NJ 08021"
"""
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import argparse
import json
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

from helper_scripts.utils.logger.logger import setup_logger
from scripts.city_data.city_data_scraper import FIELD_GROUPS, scrape_cities

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "property_city_data_output.json"
SCHEMA_VERSION = "1.0"
SOURCE = "city-data.com"
DEMOGRAPHIC_GROUPS = (
    "population",
    "income",
    "housing",
    "cost_of_living",
    "education",
)
DEFAULT_INGEST_BASE_URL = (
    "https://project--b0a20b71-38d1-47e5-9069-be4eabcd8b2a.lovable.app"
)
DEFAULT_INGEST_ENDPOINT = "/api/public/city-data"
INGEST_API_NAME = "City Data Ingest"

ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
STATE_RE = re.compile(r"\b([A-Z]{2})\b")

logger = setup_logger(
    name="property-city-lookup",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)


def _chunk_is_state_or_zip(chunk: str) -> bool:
    """True when a comma chunk is only a state and/or ZIP (no city name)."""
    tokens = chunk.split()
    if not tokens:
        return False
    if STATE_RE.fullmatch(tokens[0]):
        rest = tokens[1:]
        return not rest or all(ZIP_RE.fullmatch(token) for token in rest)
    return bool(ZIP_RE.fullmatch(tokens[0])) and len(tokens) == 1


def parse_address_parts(address: str) -> Dict[str, Optional[str]]:
    """Best-effort US address split: street, city, state, zip.

    Supports both full addresses ("123 Main St, Clementon, NJ 08021") and
    city/state only ("Clementon, NJ").
    """
    parts: Dict[str, Optional[str]] = {
        "street": None,
        "city": None,
        "state": None,
        "zip": None,
    }
    if not address or not str(address).strip():
        return parts
    text = str(address).strip()
    zip_match = ZIP_RE.search(text)
    if zip_match:
        parts["zip"] = zip_match.group(1)
    chunks = [c.strip() for c in text.split(",") if c.strip()]
    if not chunks:
        return parts

    if len(chunks) == 1:
        # "Clementon NJ 08021" without commas — take leading words before state.
        state_match = STATE_RE.search(chunks[0])
        if state_match:
            parts["state"] = state_match.group(1)
            before = chunks[0][: state_match.start()].strip(" ,")
            parts["city"] = before or None
        else:
            parts["city"] = chunks[0]
    elif len(chunks) == 2 and _chunk_is_state_or_zip(chunks[1]):
        parts["city"] = chunks[0]
        state_match = STATE_RE.search(chunks[1])
        if state_match:
            parts["state"] = state_match.group(1)
    else:
        parts["street"] = chunks[0]
        if not parts["city"]:
            maybe_city = chunks[1]
            first_token = maybe_city.split()[0] if maybe_city else ""
            if not STATE_RE.fullmatch(first_token):
                cleaned = re.sub(r"\s+[A-Z]{2}\s+\d{5}.*$", "", maybe_city).strip()
                parts["city"] = cleaned or maybe_city
        for chunk in chunks[1:]:
            state_match = STATE_RE.search(chunk)
            if state_match and not parts["state"]:
                parts["state"] = state_match.group(1)
                break

    if not parts["state"]:
        state_match = STATE_RE.search(text)
        if state_match:
            parts["state"] = state_match.group(1)
    return parts


def parse_fields_csv(raw: Optional[str]) -> List[str]:
    """Parse optional comma/space-separated field allowlist."""
    if not raw or not str(raw).strip():
        return list(FIELD_GROUPS)
    tokens = []
    for part in re.split(r"[\s,]+", str(raw).strip()):
        if part:
            tokens.append(part)
    unknown = [name for name in tokens if name not in FIELD_GROUPS]
    if unknown:
        raise ValueError(
            f"Unknown field group(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(FIELD_GROUPS)}"
        )
    return tokens


def build_envelope(
    address: str,
    query_parts: Dict[str, Optional[str]],
    scrape_payload: Optional[Dict[str, Any]] = None,
    *,
    slug: Optional[str] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Shape scraper output (or a parse failure) into the API envelope."""
    envelope: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "scraped_at": (scrape_payload or {}).get("scraped_at"),
        "query": {
            "address": address,
            "street": query_parts.get("street"),
            "city": query_parts.get("city"),
            "state": query_parts.get("state"),
            "zip": query_parts.get("zip"),
            "slug": slug,
        },
        "ok": False,
        "error": error,
        "urls": {},
        "demographics": {},
        "crime": {},
    }

    if error:
        return envelope

    results = (scrape_payload or {}).get("results") or []
    if not results:
        envelope["error"] = "Scraper returned no results"
        return envelope

    result = results[0]
    envelope["ok"] = bool(result.get("ok"))
    envelope["error"] = result.get("error")
    envelope["urls"] = result.get("urls") or {}

    demographics = {}
    for group in DEMOGRAPHIC_GROUPS:
        if group in result and result[group]:
            demographics[group] = result[group]
    envelope["demographics"] = demographics

    crime = result.get("crime")
    if crime:
        envelope["crime"] = crime

    return envelope


def save_envelope(payload: Dict[str, Any], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(output_path.parent),
        prefix=output_path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, output_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def maybe_ingest(payload: Dict[str, Any]) -> None:
    """POST envelope to the Lovable city-data public API via APIManager.

    Defaults to the project public endpoint. Auth uses CITY_DATA_INGEST_KEY
    (X-API-Key). Set CITY_DATA_INGEST_SKIP=1 to skip the POST (tests/local).
    """
    if os.getenv("CITY_DATA_INGEST_SKIP", "").strip() in {"1", "true", "TRUE", "yes"}:
        logger.info("CITY_DATA_INGEST_SKIP set; skipping ingest")
        return

    base_url = (
        os.getenv("CITY_DATA_INGEST_BASE_URL", "").strip() or DEFAULT_INGEST_BASE_URL
    )
    endpoint = (
        os.getenv("CITY_DATA_INGEST_ENDPOINT", "").strip() or DEFAULT_INGEST_ENDPOINT
    )
    api_name = os.getenv("CITY_DATA_INGEST_API", "").strip() or INGEST_API_NAME

    if not os.getenv("CITY_DATA_INGEST_KEY", "").strip():
        raise RuntimeError(
            "CITY_DATA_INGEST_KEY is required to POST city-data results. "
            "Add it as a GitHub Actions secret (or in .env), or set "
            "CITY_DATA_INGEST_SKIP=1 to skip ingest."
        )

    logger.critical("Posting city-data payload to %s%s", base_url, endpoint)

    from helper_scripts.api_manager.api_manager import APIManager

    APIManager().build_request(
        base_url=base_url,
        endpoint=endpoint,
        method="POST",
        api=api_name,
        json_body=payload,
        timeout=30.0,
    )


def lookup_address(
    address: str,
    *,
    slug: Optional[str] = None,
    fields: Optional[List[str]] = None,
    output_path: Optional[Path] = None,
    delay_seconds: float = 1.5,
    timeout_ms: int = 30000,
    headless: bool = True,
) -> Dict[str, Any]:
    """Parse address, scrape city-data, write envelope, optionally ingest."""
    address = (address or "").strip()
    if not address:
        raise ValueError("Address is required")

    parts = parse_address_parts(address)
    if not parts.get("city") or not parts.get("state"):
        envelope = build_envelope(
            address,
            parts,
            slug=slug,
            error="Could not parse city and state from address; "
            'expected a US address like "123 Main St, Clementon, NJ 08021"',
        )
        path = Path(output_path or DEFAULT_OUTPUT_PATH)
        save_envelope(envelope, path)
        print(json.dumps(envelope, indent=2, ensure_ascii=False))
        maybe_ingest(envelope)
        return envelope

    field_list = list(fields) if fields else list(FIELD_GROUPS)
    city_entry: Dict[str, Any] = {
        "city": parts["city"],
        "state": parts["state"],
    }
    if slug:
        city_entry["slug"] = slug

    config = {
        "delay_seconds": delay_seconds,
        "headless": headless,
        "timeout_ms": timeout_ms,
        "cities": [city_entry],
        "fields": field_list,
    }

    # Scraper writes its own multi-city payload; we reshape into the API envelope.
    with tempfile.TemporaryDirectory(prefix="property-city-lookup-") as tmpdir:
        scrape_path = Path(tmpdir) / "scrape.json"
        scrape_payload = scrape_cities(config, scrape_path)

    envelope = build_envelope(address, parts, scrape_payload, slug=slug)
    path = Path(output_path or DEFAULT_OUTPUT_PATH)
    save_envelope(envelope, path)
    logger.critical("Wrote property city-data envelope to %s", path)
    print(json.dumps(envelope, indent=2, ensure_ascii=False))
    maybe_ingest(envelope)
    return envelope


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Look up city-data.com demographics and crime for a property address"
        ),
    )
    parser.add_argument(
        "--address",
        required=True,
        help='Full US address, e.g. "123 Main St, Clementon, NJ 08021"',
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="Optional city-data URL slug override (e.g. Cherry-Hill-Mall)",
    )
    parser.add_argument(
        "--fields",
        default=None,
        help=(
            "Comma-separated field groups "
            f"(default: {','.join(FIELD_GROUPS)})"
        ),
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Where to write the envelope (default {DEFAULT_OUTPUT_PATH.name})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Seconds to wait between HTTP requests",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Playwright navigation timeout in milliseconds",
    )
    headless = parser.add_mutually_exclusive_group()
    headless.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="Run Chromium headless (default)",
    )
    headless.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Show the browser window",
    )
    parser.set_defaults(headless=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        fields = parse_fields_csv(args.fields)
        envelope = lookup_address(
            args.address,
            slug=args.slug,
            fields=fields,
            output_path=Path(args.output_path),
            delay_seconds=args.delay,
            timeout_ms=args.timeout_ms,
            headless=args.headless,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.error("Property city lookup failed: %s", exc)
        return 1

    if not envelope.get("ok") and envelope.get("error"):
        # Parse failures and scrape failures still emit JSON; non-zero helps CI.
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
