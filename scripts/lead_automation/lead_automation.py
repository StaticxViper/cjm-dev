import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from helper_scripts.utilities.logger import setup_logger
from leadfilter import (
    dedupe_against_existing,
    extract_real_email,
    filter_by_score,
    match_leads_to_csv,
)
from leads_api import (
    classify_response,
    count_batch_results,
    fetch_existing_leads,
    post_lead,
    post_leads_batch,
)

logger = setup_logger(
    name="lead-automation",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)

KEYWORDS = json.load(open("keywords.json"))
DEFAULT_CSV = "leads_output.csv"


def read_csv_rows(csv_path: str) -> list:
    with open(csv_path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def _niche_category(row: dict) -> str:
    niche_key = row.get("niche_key", "")
    return KEYWORDS.get(niche_key, niche_key)


def row_to_ingest_payload(row: dict, *, for_update: bool = False) -> dict:
    email_addr = extract_real_email(row.get("email", ""))
    phone = row.get("phone_google") or row.get("phone") or ""
    payload = {
        "business_name": row.get("business_name", ""),
        "address": row.get("address", ""),
        "phone": phone,
        "email": email_addr,
        "website": row.get("website") or "",
        "rating": float(row["rating"]) if row.get("rating") not in (None, "") else 0.0,
        "user_ratings_total": int(row["user_ratings_total"])
        if row.get("user_ratings_total") not in (None, "")
        else 0,
        "category": _niche_category(row),
        "tags": ["lead_automation", "google-places-api"],
        "score": int(row.get("lead_score", 0) or 0),
    }
    if row.get("id") not in (None, ""):
        payload["id"] = row["id"]
    if not for_update:
        pipeline_group = row.get("pipeline_group")
        if pipeline_group:
            payload["pipeline_group"] = pipeline_group
    else:
        payload.pop("pipeline", None)
        payload.pop("position", None)
    return payload


def log_summary(created: int, updated: int, skipped: int) -> None:
    logger.critical(
        "Run complete — created: %d, updated: %d, skipped: %d",
        created,
        updated,
        skipped,
    )


def pipeline_add(csv_path: str) -> None:
    rows = read_csv_rows(csv_path)
    total_read = len(rows)

    scored = filter_by_score(rows)
    score_skipped = total_read - len(scored)
    logger.info("Score filter: kept %d, removed %d", len(scored), score_skipped)

    existing = fetch_existing_leads()
    logger.info("Fetched %d existing leads from API", len(existing))

    new_rows, dup_skipped = dedupe_against_existing(scored, existing)
    logger.info("Dedupe: %d new, %d already in API", len(new_rows), dup_skipped)

    if not new_rows:
        log_summary(0, 0, score_skipped + dup_skipped)
        return

    payloads = [row_to_ingest_payload(row, for_update=False) for row in new_rows]
    response = post_leads_batch(payloads)
    api_counts = count_batch_results(response, len(payloads))

    skipped = score_skipped + dup_skipped + api_counts["skipped"]
    log_summary(api_counts["created"], api_counts["updated"], skipped)


def pipeline_update(csv_path: str, group: Optional[str]) -> None:
    existing = fetch_existing_leads(group=group)
    logger.info(
        "Fetched %d existing leads%s",
        len(existing),
        f" for group={group!r}" if group else "",
    )

    csv_rows = read_csv_rows(csv_path)
    matched, unmatched = match_leads_to_csv(existing, csv_rows)
    logger.info("Matched %d leads, %d unmatched", len(matched), unmatched)

    created = 0
    updated = 0
    skipped = unmatched

    for record in matched:
        payload = row_to_ingest_payload(record, for_update=True)
        payload.pop("pipeline", None)
        payload.pop("position", None)
        try:
            resp = post_lead(payload)
            outcome = classify_response(resp)
            if outcome == "created":
                created += 1
            elif outcome == "updated":
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error("POST failed for %s: %s", payload.get("email"), e)
            skipped += 1

    log_summary(created, updated, skipped)


def main():
    parser = argparse.ArgumentParser(description="Lead automation pipelines")
    subparsers = parser.add_subparsers(dest="pipeline", required=True)

    add_parser = subparsers.add_parser("add", help="Pipeline A: ingest new leads")
    add_parser.add_argument("--csv", default=DEFAULT_CSV, help="Input CSV path")

    update_parser = subparsers.add_parser("update", help="Pipeline B: update existing leads")
    update_parser.add_argument("--csv", default=DEFAULT_CSV, help="Input CSV path")
    update_parser.add_argument("--group", default=None, help="Filter GET by pipeline group")

    args = parser.parse_args()
    logger.critical("Starting lead automation (%s)...", args.pipeline)

    if args.pipeline == "add":
        pipeline_add(args.csv)
    elif args.pipeline == "update":
        pipeline_update(args.csv, args.group)


if __name__ == "__main__":
    main()
