"""JSON and CSV writers. The JSON document is checked against output.schema.json."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from opp_finder_v2.config import ConfigError, validate_instance
from opp_finder_v2.models import Criteria, Opportunity, SiteResult

CSV_FIELDS = [
    "opp_id",
    "title",
    "company",
    "location",
    "remote",
    "url",
    "apply_url",
    "source_site",
    "sources",
    "posted_date",
    "snippet",
    "salary_text",
    "rate_min",
    "rate_max",
    "rate_unit",
    "currency",
    "employment_type",
    "tags",
    "matched_keywords",
    "relevance_score",
    "score_breakdown",
    "scraped_at",
]


def sort_opportunities(opportunities: list[Opportunity]) -> list[Opportunity]:
    return sorted(
        opportunities,
        key=lambda opp: (opp.relevance_score, opp.posted_date or ""),
        reverse=True,
    )


def build_document(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    dry_run: bool,
    criteria: Criteria,
    sites: list[SiteResult],
    opportunities: list[Opportunity],
    dropped: dict[str, int],
    merged: int,
    fetched: int,
) -> dict:
    ordered = sort_opportunities(opportunities)
    return {
        "schema_version": 1,
        "run": {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "dry_run": dry_run,
            "criteria": criteria.resolved_dict(),
            "sites": [site.to_dict() for site in sites],
            "totals": {
                "fetched": fetched,
                "after_filters": sum(site.matched for site in sites),
                "after_dedupe": len(ordered),
                "merged": merged,
                "dropped": dict(dropped),
            },
        },
        "opportunities": [opp.to_dict() for opp in ordered],
    }


def write_json(path: Path, document: dict) -> None:
    errors = validate_instance(document, "output.schema.json")
    if errors:
        preview = "\n".join(errors[:8])
        raise ConfigError([f"output does not match output.schema.json:\n{preview}"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return json.dumps(value, separators=(",", ":"))
        return " | ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def write_csv(path: Path, opportunities: list[Opportunity]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for opp in sort_opportunities(opportunities):
            row = opp.to_dict()
            writer.writerow({key: _cell(row.get(key)) for key in CSV_FIELDS})


def csv_path_for(json_path: Path) -> Path:
    return json_path.with_suffix(".csv")
