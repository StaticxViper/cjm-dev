#!/usr/bin/env python3
"""Build a JSON payload from opp_finder CSV outputs for GitHub Actions / API callers."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.config import load_config, resolve_path  # noqa: E402

# Keep GitHub Actions job outputs under the ~1MB limit.
MAX_OUTPUT_CHARS = 900_000
PREVIEW_FIELDS = [
    "job_title",
    "company_name",
    "location",
    "remote_status",
    "source",
    "source_url",
    "automation_score",
    "opportunity_score",
    "workflow_tasks",
    "outreach_status",
    "contact_email",
    "recommended_contact_role",
    "automation_opportunity",
    "demo_concept",
    "outreach_subject",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _preview_rows(rows: list[dict[str, str]], limit: int | None = None) -> list[dict[str, str]]:
    selected = rows if limit is None else rows[:limit]
    preview: list[dict[str, str]] = []
    for row in selected:
        preview.append({key: row.get(key, "") for key in PREVIEW_FIELDS})
    return preview


def build_payload(
    *,
    all_jobs_path: Path,
    qualified_path: Path,
    history_path: Path,
    all_jobs_preview_limit: int = 50,
) -> dict:
    all_jobs = _read_csv(all_jobs_path)
    qualified = _read_csv(qualified_path)
    history = _read_csv(history_path)

    # Sort qualified / all by opportunity score descending when present.
    def score_key(row: dict[str, str]) -> int:
        try:
            return int(float(row.get("opportunity_score") or 0))
        except ValueError:
            return 0

    all_jobs_sorted = sorted(all_jobs, key=score_key, reverse=True)
    qualified_sorted = sorted(qualified, key=score_key, reverse=True)

    return {
        "summary": {
            "all_jobs_count": len(all_jobs),
            "qualified_count": len(qualified),
            "search_history_count": len(history),
            "all_jobs_path": str(all_jobs_path),
            "qualified_path": str(qualified_path),
            "search_history_path": str(history_path),
        },
        "qualified_opportunities": qualified_sorted,
        "all_jobs_preview": _preview_rows(all_jobs_sorted, all_jobs_preview_limit),
        "search_history": history,
    }


def write_github_output(payload: dict) -> None:
    """Write summary fields + JSON blob for workflow job outputs."""
    out_file = os.environ.get("GITHUB_OUTPUT")
    if not out_file:
        return

    summary = payload.get("summary") or {}
    compact = {
        "summary": summary,
        "qualified_opportunities": payload.get("qualified_opportunities") or [],
        "all_jobs_preview": payload.get("all_jobs_preview") or [],
    }
    results_json = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    truncated = False
    if len(results_json) > MAX_OUTPUT_CHARS:
        truncated = True
        compact = {
            "summary": summary,
            "qualified_opportunities": _preview_rows(payload.get("qualified_opportunities") or []),
            "all_jobs_preview": payload.get("all_jobs_preview") or [],
            "truncated": True,
            "note": "Full CSV/JSON available in the opp-finder-results artifact.",
        }
        results_json = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(results_json) > MAX_OUTPUT_CHARS:
            compact = {
                "summary": summary,
                "qualified_opportunities": _preview_rows(
                    payload.get("qualified_opportunities") or [],
                    20,
                ),
                "truncated": True,
                "note": "Output truncated; download the opp-finder-results artifact for full CSV data.",
            }
            results_json = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    with open(out_file, "a", encoding="utf-8") as handle:
        handle.write(f"all_jobs_count={summary.get('all_jobs_count', 0)}\n")
        handle.write(f"qualified_count={summary.get('qualified_count', 0)}\n")
        handle.write(f"truncated={'true' if truncated else 'false'}\n")
        handle.write("results_json<<OPP_FINDER_JSON_EOF\n")
        handle.write(results_json)
        handle.write("\nOPP_FINDER_JSON_EOF\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export opp_finder CSV data as API JSON")
    parser.add_argument(
        "--config",
        default=str(SCRIPT_DIR / "config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Write full JSON payload to this path (default: output/api_results.json)",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Also write summary/results_json to $GITHUB_OUTPUT",
    )
    parser.add_argument(
        "--all-jobs-preview-limit",
        type=int,
        default=50,
        help="Max all_jobs rows to include in preview section",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    all_jobs_path = resolve_path(config, "all_jobs")
    qualified_path = resolve_path(config, "qualified")
    history_path = resolve_path(config, "search_history")

    payload = build_payload(
        all_jobs_path=all_jobs_path,
        qualified_path=qualified_path,
        history_path=history_path,
        all_jobs_preview_limit=max(0, int(args.all_jobs_preview_limit)),
    )

    output_path = Path(args.output) if args.output else (SCRIPT_DIR / "output" / "api_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_path} ({payload['summary']})")

    if args.github_output:
        write_github_output(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
