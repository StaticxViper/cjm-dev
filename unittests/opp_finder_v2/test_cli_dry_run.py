"""End-to-end dry-run CLI, exit codes, and per-site failure isolation."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from opp_finder_v2.cli import main  # noqa: E402
from opp_finder_v2.config import load_sites, validate_instance  # noqa: E402
from opp_finder_v2.models import RunOptions, SiteConfig  # noqa: E402
from opp_finder_v2.pipeline import gate_status, run  # noqa: E402


class TestCliDryRun(unittest.TestCase):
    def test_dry_run_writes_schema_valid_json_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            code = main(
                [
                    "--dry-run",
                    "--format",
                    "both",
                    "--sites",
                    "remotive,remoteok,weworkremotely",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            document = json.loads(out.read_text(encoding="utf-8"))
            errors = validate_instance(document, "output.schema.json")
            self.assertEqual(errors, [])
            self.assertTrue(document["run"]["dry_run"])
            csv_path = out.with_suffix(".csv")
            self.assertTrue(csv_path.is_file())
            header = csv_path.read_text(encoding="utf-8").splitlines()[0]
            self.assertTrue(header.startswith("opp_id,title,company,"))

    def test_unknown_site_exits_2(self):
        code = main(["--dry-run", "--sites", "not_a_board", "--out", "unused.json"])
        self.assertEqual(code, 2)

    def test_validate_and_list_sites(self):
        self.assertEqual(main(["--validate"]), 0)
        self.assertEqual(main(["--list-sites"]), 0)

    def test_forced_exception_keeps_earlier_site(self):
        from opp_finder_v2 import pipeline as pipeline_module

        real_fetch = pipeline_module.fetch_site

        def wrapped(site, query, criteria, options, browser=None):
            if site.id == "remoteok":
                self.assertTrue(options.out.is_file())
                earlier = json.loads(options.out.read_text(encoding="utf-8"))
                ids = [item["id"] for item in earlier["run"]["sites"]]
                self.assertIn("remotive", ids)
                raise RuntimeError("forced failure")
            return real_fetch(site, query, criteria, options, browser=browser)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            with patch.object(pipeline_module, "fetch_site", wrapped):
                code = main(
                    [
                        "--dry-run",
                        "--sites",
                        "remotive,remoteok",
                        "--out",
                        str(out),
                    ]
                )
            self.assertEqual(code, 0)
            document = json.loads(out.read_text(encoding="utf-8"))
            by_id = {item["id"]: item for item in document["run"]["sites"]}
            self.assertEqual(by_id["remotive"]["status"], "ok")
            self.assertGreaterEqual(by_id["remotive"]["fetched"], 1)
            self.assertEqual(by_id["remoteok"]["status"], "error")
            self.assertIn("forced failure", by_id["remoteok"]["error"])

    def test_captcha_fixture_stops_one_site_and_keeps_the_other(self):
        catalog = load_sites()
        catalog.sites.append(
            SiteConfig(
                id="sample_captcha",
                name="Captcha fixture",
                enabled=True,
                base_url="https://example.com",
                mode="playwright",
                access="guest",
                results={"list": [{"css": "li.job"}], "fields": {"title": [{"css": "a"}]}},
                pagination={"type": "none", "max_pages": 1, "stop_when_no_new": 2},
                rate_limit={"min_delay_s": 0, "max_delay_s": 0, "max_results": 5, "max_requests": 2},
                auth={"type": "none"},
            )
        )
        package = ROOT / "scripts" / "opp_finder_v2"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            artifacts = Path(tmp) / "artifacts"
            options = RunOptions(
                config_path=package / "sites.json",
                criteria_path=package / "criteria.json",
                sites=["remotive", "sample_captcha"],
                out=out,
                dry_run=True,
                format="json",
                artifacts_root=artifacts,
            )
            code = run(options, catalog=catalog)
            document = json.loads(out.read_text(encoding="utf-8"))
            by_id = {item["id"]: item for item in document["run"]["sites"]}
            self.assertEqual(code, 0)
            self.assertEqual(by_id["remotive"]["status"], "ok")
            self.assertGreaterEqual(by_id["remotive"]["fetched"], 1)
            self.assertEqual(by_id["sample_captcha"]["status"], "skipped_captcha")
            self.assertTrue(by_id["sample_captcha"].get("artifacts"))
            artifact_dir = Path(by_id["sample_captcha"]["artifacts"])
            self.assertTrue(artifact_dir.is_dir())
            self.assertTrue(list(artifact_dir.glob("*.html")))
            self.assertTrue((artifact_dir / "meta.json").is_file())

    def test_login_gate(self):
        site = next(item for item in load_sites().sites if item.id == "linkedin_auth")
        package = ROOT / "scripts" / "opp_finder_v2"
        options = RunOptions(
            config_path=package / "sites.json",
            criteria_path=package / "criteria.json",
            allow_login=False,
        )
        self.assertEqual(gate_status(site, options), "skipped_auth_disabled")
        options.allow_login = True
        self.assertEqual(gate_status(site, options), "skipped_auth_disabled")
        site.enabled = True
        self.assertEqual(gate_status(site, options), "skipped_auth_disabled")
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text("{}", encoding="utf-8")
            os.environ["LINKEDIN_STORAGE_STATE"] = str(state)
            try:
                self.assertIsNone(gate_status(site, options))
            finally:
                os.environ.pop("LINKEDIN_STORAGE_STATE", None)
        toptal = next(item for item in load_sites().sites if item.id == "toptal")
        self.assertEqual(gate_status(toptal, options), "skipped_manual")


if __name__ == "__main__":
    unittest.main()
