"""CLI wiring for new-business mode, including an offline dry run."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_LEADGEN = _REPO / "scripts" / "lead_automation" / "leadgen.py"
_LEADGEN_DIR = _LEADGEN.parent
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "new_business" / "standard_mode_score.json"
if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))

import leadgen
from new_business_pipeline import refuse_dashboard
from new_business_sources import select_adapters


class TestStandardModeUnchanged(unittest.TestCase):
    def test_default_mode_and_documented_lead_score(self):
        self.assertEqual(leadgen.LeadgenConfig().discovery_mode, "standard")
        expected = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        score = leadgen.score_lead(
            expected["has_website"],
            expected["https"],
            expected["has_viewport"],
            expected["html_length"],
            expected["has_email"],
            expected["has_cta"],
            expected["rating"],
            expected["user_ratings_total"],
            expected["business_status"],
        )
        self.assertEqual(score, expected["lead_score"])
        self.assertEqual(score, 96)


class TestNewBusinessCli(unittest.TestCase):
    def test_dry_run_writes_json_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "new_business_leads.json"
            csv_path = Path(tmp) / "new_business_leads.csv"
            result = subprocess.run(
                [
                    sys.executable,
                    str(_LEADGEN),
                    "--mode", "new-business",
                    "--dry-run",
                    "--defaults",
                    "--state", "PA",
                    "--city", "Philadelphia",
                    "--output", "both",
                    "--json-path", str(json_path),
                    "--csv-path", str(csv_path),
                    "--website-check", "none",
                    "--min-new-business-score", "50",
                    "--max-age-days", "365",
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:] + result.stdout[-2000:])
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIsInstance(payload, list)
            self.assertTrue(payload)
            row = payload[0]
            self.assertTrue(row.get("lead_id"))
            self.assertIn("new_business_score", row)
            self.assertEqual(sum(row["score_breakdown"].values()), row["new_business_score"])
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertTrue(csv_text.startswith("lead_id,"))
            self.assertIn(row["lead_id"], csv_text)

    def test_dashboard_output_is_refused(self):
        config = leadgen.LeadgenConfig(discovery_mode="new-business", output_mode="dashboard")
        refused = refuse_dashboard(config)
        self.assertTrue(refused)
        self.assertEqual(config.output_mode, "both")

    def test_unknown_source_lists_valid_ids(self):
        with self.assertRaises(ValueError) as caught:
            select_adapters(["not-a-real-source"])
        message = str(caught.exception)
        self.assertIn("not-a-real-source", message)
        self.assertIn("ny_active_corporations", message)
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(_LEADGEN),
                    "--mode", "new-business",
                    "--dry-run",
                    "--defaults",
                    "--sources", "not-a-real-source",
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertIn("not-a-real-source", combined)
            self.assertIn("ny_active_corporations", combined)


if __name__ == "__main__":
    unittest.main()
