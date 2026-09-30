"""Unit tests for opp_finder geo, dedupe, scoring, and CSV columns."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPP_DIR = REPO_ROOT / "scripts" / "opp_finder"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(OPP_DIR))

from analysis.outreach import generate_outreach  # noqa: E402
from analysis.scoring import score_automation  # noqa: E402
from analysis.workflow import extract_workflow  # noqa: E402
from pipeline import dedupe_jobs, passes_qualification, stage1_analyze  # noqa: E402
from utils.constants import ALL_JOBS_COLUMNS, QUALIFIED_COLUMNS  # noqa: E402
from utils.csv_utils import read_csv_rows, upsert_csv_row  # noqa: E402
from utils.geo import detect_remote_status, matches_target_geography  # noqa: E402
from utils.jobs import RawJob  # noqa: E402
from utils.normalization import job_fingerprint, normalize_company, normalize_url  # noqa: E402


CONFIG = {
    "include_remote": True,
    "location": {
        "state": "NJ",
        "counties": ["Camden", "Burlington", "Gloucester"],
        "place_hints": ["Cherry Hill", "South Jersey"],
    },
    "qualification": {
        "minimum_automation_score": 55,
        "minimum_opportunity_score": 60,
    },
}


class NormalizationTests(unittest.TestCase):
    def test_normalize_company_strips_suffix(self):
        self.assertEqual(normalize_company("Acme Property LLC"), "acme property")

    def test_normalize_url_strips_utm(self):
        url = "https://Example.com/jobs/1/?utm_source=google&x=1"
        self.assertEqual(normalize_url(url), "https://example.com/jobs/1?x=1")

    def test_fingerprint_stable(self):
        a = job_fingerprint("Acme LLC", "Data Entry", "Cherry Hill, NJ", "https://x.com/a?utm_source=1")
        b = job_fingerprint("Acme", "data entry", "cherry hill nj", "https://x.com/a")
        self.assertEqual(a, b)


class GeoTests(unittest.TestCase):
    def test_remote_detection(self):
        self.assertEqual(detect_remote_status("Remote, US", ""), "remote")
        self.assertEqual(detect_remote_status("Hybrid - Cherry Hill, NJ", ""), "hybrid")
        self.assertEqual(
            detect_remote_status("Cherry Hill, NJ", "This is not a remote position."),
            "on-site",
        )

    def test_south_jersey_match(self):
        self.assertTrue(
            matches_target_geography("Cherry Hill, NJ", "office assistant", CONFIG)
        )

    def test_out_of_state_onsite_rejected(self):
        self.assertFalse(
            matches_target_geography("Austin, TX", "on-site data entry", CONFIG)
        )

    def test_remote_allowed(self):
        self.assertTrue(
            matches_target_geography("Remote", "fully remote data entry US", CONFIG)
        )


class WorkflowScoringTests(unittest.TestCase):
    def test_extract_workflow_tasks(self):
        job = {
            "job_title": "Property Research Assistant",
            "job_description": (
                "Research property records online, enter results into Excel spreadsheets, "
                "and verify property details before generating weekly reports."
            ),
        }
        wf = extract_workflow(job)
        self.assertTrue(wf["workflow_tasks"])
        self.assertTrue(any("property" in t.lower() or "research" in t.lower() for t in wf["workflow_tasks"]))
        self.assertTrue(wf["workflow_evidence"])

    def test_high_automation_score_for_research_entry(self):
        job = {
            "job_title": "Data Entry / Web Research Specialist",
            "job_description": (
                "Perform repetitive web research, data entry into spreadsheets and CRM, "
                "verify records, and generate recurring reports."
            ),
            "location": "Remote",
            "workflow_tasks": (
                "Research information online | Enter data into systems or spreadsheets | "
                "Update CRM records | Generate recurring reports"
            ),
        }
        analysis = score_automation(job)
        self.assertGreaterEqual(analysis["automation_score"], 55)
        self.assertIn(
            analysis["automation_percentage_estimate"],
            {"0–20%", "20–40%", "40–60%", "60–80%", "80%+"},
        )
        self.assertIn("Python", analysis["possible_technology"])

    def test_physical_job_scores_low(self):
        job = {
            "job_title": "Warehouse Associate",
            "job_description": "Forklift operation, lifting boxes, loading trucks on-site.",
            "location": "Camden, NJ",
            "workflow_tasks": "",
        }
        analysis = score_automation(job)
        self.assertLess(analysis["automation_score"], 55)


class DedupeCsvTests(unittest.TestCase):
    def test_dedupe_same_url(self):
        a = RawJob(
            job_title="Data Entry Clerk",
            company_name="Acme",
            location="Cherry Hill, NJ",
            source="google",
            source_url="https://example.com/job/1?utm_source=x",
            job_description="data entry",
        )
        b = RawJob(
            job_title="Data Entry Clerk",
            company_name="Acme LLC",
            location="Cherry Hill, NJ",
            source="indeed",
            source_url="https://example.com/job/1",
            job_description="data entry spreadsheet research",
        )
        merged = dedupe_jobs([a, b])
        self.assertEqual(len(merged), 1)
        self.assertIn("indeed", merged[0]["sources_found"])
        self.assertIn("google", merged[0]["sources_found"])

    def test_csv_upsert_and_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "all_jobs.csv"
            row = {col: "" for col in ALL_JOBS_COLUMNS}
            row.update(
                {
                    "job_id": "abc123",
                    "job_title": "Research Assistant",
                    "company_name": "Test Co",
                    "automation_score": "70",
                }
            )
            upsert_csv_row(path, row, ALL_JOBS_COLUMNS, ["job_id"])
            row["automation_score"] = "80"
            upsert_csv_row(path, row, ALL_JOBS_COLUMNS, ["job_id"])
            rows = read_csv_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["automation_score"], "80")
            self.assertEqual(list(rows[0].keys()), ALL_JOBS_COLUMNS)

    def test_qualified_column_stability(self):
        self.assertIn("outreach_message", QUALIFIED_COLUMNS)
        self.assertIn("opportunity_score", QUALIFIED_COLUMNS)
        self.assertIn("demo_concept", QUALIFIED_COLUMNS)


class OutreachTests(unittest.TestCase):
    def test_outreach_references_job_title(self):
        job = stage1_analyze(
            {
                "job_title": "Listing Coordinator",
                "company_name": "Shore Properties",
                "location": "Ocean City, NJ",
                "job_description": (
                    "Upload listings, enter property data into spreadsheets, "
                    "and research property details online."
                ),
                "source": "google",
                "source_url": "https://example.com/jobs/listing",
            }
        )
        self.assertTrue(passes_qualification(job, CONFIG) or int(job["automation_score"]) >= 40)
        draft = generate_outreach(job, {"outreach": {"sender_name": "CJ"}})
        self.assertIn("Listing Coordinator", draft["outreach_subject"])
        self.assertIn("Listing Coordinator", draft["outreach_message"])
        self.assertIn("CJ", draft["outreach_message"])
        self.assertTrue(draft["demo_concept"])


if __name__ == "__main__":
    unittest.main()
