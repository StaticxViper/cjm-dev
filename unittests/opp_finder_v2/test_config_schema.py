"""Schema checks for the shipped site catalogue and criteria."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from opp_finder_v2.config import (  # noqa: E402
    load_criteria,
    load_json,
    load_sites,
    validate_criteria_document,
    validate_sites_document,
)


def _sites_document():
    return load_json(ROOT / "scripts" / "opp_finder_v2" / "sites.json")


class TestShippedConfig(unittest.TestCase):
    def test_shipped_files_validate(self):
        catalog = load_sites()
        criteria = load_criteria()
        ids = [site.id for site in catalog.sites]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("remotive", ids)
        self.assertIn("toptal", ids)
        self.assertIn("supercruiter", ids)
        self.assertGreaterEqual(criteria.min_relevance, 0)

    def test_missing_id_reports_a_path(self):
        document = _sites_document()
        document["sites"][0].pop("id")
        errors = validate_sites_document(document)
        self.assertTrue(errors)
        self.assertTrue(any("id" in error for error in errors))

    def test_bad_mode_is_rejected(self):
        document = _sites_document()
        document["sites"][0]["mode"] = "serp"
        errors = validate_sites_document(document)
        self.assertTrue(any("mode" in error and "serp" in error for error in errors))

    def test_inline_secret_auth_is_rejected(self):
        document = _sites_document()
        document["sites"][0]["auth"] = {"type": "none", "cookie": "session=abc"}
        errors = validate_sites_document(document)
        joined = "\n".join(errors)
        self.assertIn("cookie", joined)

    def test_inline_storage_state_blob_is_rejected(self):
        document = _sites_document()
        document["sites"][0]["auth"] = {
            "type": "storage_state",
            "storage_state": {"cookies": [{"name": "li_at", "value": "secret"}]},
        }
        errors = validate_sites_document(document)
        joined = "\n".join(errors)
        self.assertIn("storage_state", joined)

    def test_duplicate_ids_are_rejected(self):
        document = _sites_document()
        duplicate = copy.deepcopy(document["sites"][0])
        document["sites"].append(duplicate)
        errors = validate_sites_document(document)
        self.assertTrue(any("duplicate site id" in error for error in errors))

    def test_bad_criteria_is_rejected(self):
        document = json.loads(
            (ROOT / "scripts" / "opp_finder_v2" / "criteria.json").read_text(encoding="utf-8")
        )
        document.pop("min_relevance")
        errors = validate_criteria_document(document)
        self.assertTrue(any("min_relevance" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
