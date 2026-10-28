"""Start the Zillow agents Actor through the Apify API and save the dataset.

Script Manager runs this. It uses APIFY_TOKEN. It does not launch a browser.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parent
_ACTOR = _SRC.parent
_REPO = _ACTOR.parents[2]
for _entry in (
    _REPO,
    _REPO / "scripts",
    _REPO / "scripts" / "lead_automation",
    _REPO / "scripts" / "zillow_automation",
    _SRC,
):
    _text = str(_entry)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from apify_client import ApifyClient  # noqa: E402

import zillow_agents  # noqa: E402
from zillow_parse import (  # noqa: E402
    AGENT_CSV_FIELDS,
    LISTING_CSV_FIELDS,
    agent_csv_row,
    listing_csv_row,
    output_paths,
)


def actor_id_from_env(env=None):
    env = os.environ if env is None else env
    explicit = str(env.get("ZILLOW_ACTOR_ID") or "").strip()
    if explicit:
        return explicit
    user = str(env.get("APIFY_USER_ID") or "").strip()
    if not user:
        raise RuntimeError("Set ZILLOW_ACTOR_ID or APIFY_USER_ID.")
    return f"{user}~zillow-agents"


def build_actor_input(zip_codes, max_listings, max_agents):
    codes = [str(code).strip() for code in (zip_codes or []) if str(code).strip()]
    if not codes:
        raise ValueError("At least one ZIP code is required.")
    return {
        "zip_codes": codes,
        "max_listings": int(max_listings),
        "max_agents": int(max_agents),
    }


def _field(obj, *names):
    if obj is None:
        return None
    if isinstance(obj, dict):
        for name in names:
            value = obj.get(name)
            if value:
                return value
        return None
    for name in names:
        value = getattr(obj, name, None)
        if value:
            return value
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        data = dump()
        if isinstance(data, dict):
            for name in names:
                value = data.get(name)
                if value:
                    return value
    return None


def dataset_id_from_run(run):
    dataset_id = _field(run, "defaultDatasetId", "default_dataset_id")
    if not dataset_id:
        raise RuntimeError("Apify actor run did not return a dataset id.")
    return str(dataset_id)


def run_status(run):
    status = _field(run, "status")
    return str(status or "")


def fetch_dataset_items(client, dataset_id):
    page = client.dataset(str(dataset_id)).list_items()
    items = getattr(page, "items", None)
    if items is None and isinstance(page, dict):
        items = page.get("items") or []
    return list(items or [])


def fetch_record(client, store_id, key):
    if not store_id:
        return None
    record = client.key_value_store(str(store_id)).get_record(key)
    if record is None:
        return None
    if isinstance(record, dict):
        return record.get("value", record)
    value = getattr(record, "value", None)
    return record if value is None else value


def write_download(items, listings_doc, output_dir, zip_codes, run_date=None):
    """Dated CSV and JSON, same names as a local pipeline run."""
    stamp = run_date or datetime.now().strftime("%Y-%m-%d")
    paths = output_paths(output_dir, stamp, zip_codes)
    agents = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        addresses = row.get("listing_addresses") or []
        if isinstance(addresses, str):
            addresses = [part.strip() for part in addresses.split(";") if part.strip()]
        row["listing_addresses"] = list(addresses)
        row.setdefault("listing_ids", row.get("listing_ids") or [])
        agents.append(row)
    listings = []
    run = {}
    if isinstance(listings_doc, dict):
        listings = list(listings_doc.get("listings") or [])
        run = listings_doc.get("run") if isinstance(listings_doc.get("run"), dict) else {}
    if not run:
        run = {"agents_found": len(agents), "listings_found": len(listings)}
    zillow_agents.save_json_atomic(paths["agents_json"], {"run": run, "agents": agents})
    zillow_agents.save_json_atomic(paths["listings_json"], {"run": run, "listings": listings})
    zillow_agents._save_csv_atomic(
        paths["agents_csv"],
        AGENT_CSV_FIELDS,
        [agent_csv_row(agent) for agent in agents],
    )
    zillow_agents._save_csv_atomic(
        paths["listings_csv"],
        LISTING_CSV_FIELDS,
        [listing_csv_row(listing) for listing in listings],
    )
    return paths


def start_and_download(client, actor_id, actor_input, output_dir, run_date=None):
    run = client.actor(actor_id).call(run_input=actor_input)
    status = run_status(run)
    if status and status.upper() != "SUCCEEDED":
        raise RuntimeError(f"Apify actor run finished with status {status}.")
    dataset_id = dataset_id_from_run(run)
    items = fetch_dataset_items(client, dataset_id)
    store_id = _field(run, "defaultKeyValueStoreId", "default_key_value_store_id")
    listings_doc = fetch_record(client, store_id, "LISTINGS")
    summary = fetch_record(client, store_id, "SUMMARY")
    paths = write_download(
        items,
        listings_doc if isinstance(listings_doc, dict) else {"listings": [], "run": summary or {}},
        output_dir,
        actor_input["zip_codes"],
        run_date=run_date,
    )
    return {
        "ok": True,
        "actor_id": actor_id,
        "dataset_id": dataset_id,
        "agents": len(items),
        "summary": summary if isinstance(summary, dict) else {},
        "paths": {key: str(path) for key, path in paths.items()},
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Start the Zillow agents Actor on Apify and download the dataset",
    )
    parser.add_argument("--zip-codes", nargs="+", required=True, help="ZIP codes to search")
    parser.add_argument("--max-listings", type=int, default=100, help="Total listings across all ZIPs")
    parser.add_argument("--max-agents", type=int, default=50, help="Total unique agents to return")
    parser.add_argument(
        "--output-dir",
        default=str(_REPO / "scripts" / "zillow_automation"),
        help="Directory for the dated CSV and JSON files",
    )
    parser.add_argument("--run-date", help="Date stamp for output file names (YYYY-MM-DD)")
    return parser.parse_args(argv)


def main(argv=None, client=None, env=None):
    args = parse_args(argv)
    try:
        actor_input = build_actor_input(args.zip_codes, args.max_listings, args.max_agents)
        actor_id = actor_id_from_env(env)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    token = str((env or os.environ).get("APIFY_TOKEN") or "").strip()
    if not token:
        print("APIFY_TOKEN is required.", file=sys.stderr)
        return 1
    if client is None:
        client = ApifyClient(token)
    try:
        report = start_and_download(
            client,
            actor_id,
            actor_input,
            args.output_dir,
            run_date=args.run_date,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report))
    return 0
