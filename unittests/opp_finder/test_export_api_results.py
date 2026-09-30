"""Tests for opp_finder API JSON export helper."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPP_DIR = REPO_ROOT / "scripts" / "opp_finder"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(OPP_DIR))

from export_api_results import build_payload, write_github_output  # noqa: E402
from utils.constants import ALL_JOBS_COLUMNS, QUALIFIED_COLUMNS, SEARCH_HISTORY_COLUMNS  # noqa: E402


class ExportApiResultsTests(unittest.TestCase):
    def test_build_payload_from_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            all_path = tmp_path / "all_jobs.csv"
            qual_path = tmp_path / "qualified.csv"
            hist_path = tmp_path / "history.csv"

            with open(all_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=ALL_JOBS_COLUMNS)
                writer.writeheader()
                row = {k: "" for k in ALL_JOBS_COLUMNS}
                row.update(
                    {
                        "job_title": "Data Entry Clerk",
                        "company_name": "Acme",
                        "opportunity_score": "80",
                        "automation_score": "75",
                    }
                )
                writer.writerow(row)

            with open(qual_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=QUALIFIED_COLUMNS)
                writer.writeheader()
                row = {k: "" for k in QUALIFIED_COLUMNS}
                row.update(
                    {
                        "job_title": "Data Entry Clerk",
                        "company_name": "Acme",
                        "opportunity_score": "80",
                        "outreach_subject": "Potential automation opportunity for your Data Entry Clerk workflow",
                    }
                )
                writer.writerow(row)

            with open(hist_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=SEARCH_HISTORY_COLUMNS)
                writer.writeheader()
                writer.writerow(
                    {
                        "run_id": "abc",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "source": "craigslist",
                        "query": "1 keywords",
                        "results_count": "1",
                        "status": "ok",
                        "notes": "",
                    }
                )

            payload = build_payload(
                all_jobs_path=all_path,
                qualified_path=qual_path,
                history_path=hist_path,
            )
            self.assertEqual(payload["summary"]["all_jobs_count"], 1)
            self.assertEqual(payload["summary"]["qualified_count"], 1)
            self.assertEqual(payload["qualified_opportunities"][0]["job_title"], "Data Entry Clerk")
            self.assertEqual(payload["all_jobs_preview"][0]["company_name"], "Acme")

            gh_out = tmp_path / "github_output.txt"
            os.environ["GITHUB_OUTPUT"] = str(gh_out)
            try:
                write_github_output(payload)
            finally:
                os.environ.pop("GITHUB_OUTPUT", None)

            text = gh_out.read_text(encoding="utf-8")
            self.assertIn("all_jobs_count=1", text)
            self.assertIn("qualified_count=1", text)
            self.assertIn("results_json<<OPP_FINDER_JSON_EOF", text)
            start = text.index("results_json<<OPP_FINDER_JSON_EOF\n") + len(
                "results_json<<OPP_FINDER_JSON_EOF\n"
            )
            end = text.index("\nOPP_FINDER_JSON_EOF\n", start)
            parsed = json.loads(text[start:end])
            self.assertEqual(parsed["summary"]["qualified_count"], 1)
            self.assertEqual(parsed["qualified_opportunities"][0]["job_title"], "Data Entry Clerk")


if __name__ == "__main__":
    unittest.main()
