"""Source adapters parse fixtures and honor access status."""
import sys
import unittest
from pathlib import Path

_LEADGEN_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lead_automation"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "new_business"
if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))

from new_business_sources import load_adapters, select_adapters
from new_business_sources.base import classify_access_html, load_fixture_json, resolve_fixture_dates, robots_allowed


def _adapters():
    return {adapter.id: adapter for adapter in load_adapters()}


class TestAdapterParsing(unittest.TestCase):
    def test_open_data_fixtures(self):
        adapters = _adapters()
        for source_id, expected_name in (
            ("pa_registered_businesses", "Smith Landscaping LLC"),
            ("ny_active_corporations", "Example Reid LLC"),
            ("co_business_entities", "Example Services LLC"),
            ("phl_business_licenses", "Example Cafe LLC"),
        ):
            payload = resolve_fixture_dates(load_fixture_json(source_id))
            records = adapters[source_id].parse_payload(payload)
            self.assertTrue(records, source_id)
            self.assertEqual(records[0].business_name, expected_name)
            self.assertTrue(records[0].newness_evidence, source_id)
            self.assertTrue(records[0].newness_evidence[0]["date"], source_id)

    def test_http_table_fixture(self):
        html = (_FIXTURES / "example_public_table" / "page.html").read_text(encoding="utf-8")
        records = _adapters()["example_public_table"].parse_html(html)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].business_name, "Smith Landscaping LLC")
        self.assertEqual(records[0].filing_date, "2026-09-01")
        self.assertEqual(records[0].city, "Cinnaminson")

    def test_google_search_fixture(self):
        html = (_FIXTURES / "google_search" / "page.html").read_text(encoding="utf-8")
        records = _adapters()["google_search"].parse_html(html, city="Philadelphia", state="PA")
        self.assertTrue(records)
        self.assertEqual(records[0].newness_evidence[0]["type"], "grand_opening")

    def test_google_maps_verify_fixture_does_not_add_newness(self):
        rows = [{"business_name": "Smith Landscaping LLC", "city": "Philadelphia", "state": "PA"}]
        updated, info = _adapters()["google_maps"].verify(rows, dry_run=True)
        self.assertTrue(info["checked"])
        self.assertEqual(updated[0]["place_id"], "EXAMPLE")
        self.assertFalse(updated[0].get("newness_evidence"))


class TestAccess(unittest.TestCase):
    def test_block_login_and_robots_fixtures(self):
        block = (_FIXTURES / "access" / "block.html").read_text(encoding="utf-8")
        login = (_FIXTURES / "access" / "login.html").read_text(encoding="utf-8")
        robots = (_FIXTURES / "access" / "robots.txt").read_text(encoding="utf-8")
        self.assertEqual(classify_access_html(block, "https://www.google.com/sorry/"), "blocked")
        self.assertEqual(classify_access_html(login), "login_required")
        self.assertFalse(robots_allowed(robots, "https://www.google.com/search?q=new+business"))
        self.assertTrue(robots_allowed(robots, "https://www.google.com/maps/search/landscaping"))
        search = _adapters()["google_search"]
        self.assertEqual(
            search.check_access(robots_txt=robots, target_url="https://www.google.com/search?q=new+business"),
            "robots_disallowed",
        )

    def test_disabled_and_candidate_sources_are_not_selected(self):
        selected = {adapter.id for adapter in select_adapters()}
        self.assertIn("ny_active_corporations", selected)
        self.assertIn("pa_registered_businesses", selected)
        self.assertIn("google_maps", selected)
        self.assertNotIn("google_search", selected)
        self.assertNotIn("example_public_table", selected)
        self.assertNotIn("nj_dores", selected)
        self.assertNotIn("nj_open_data", selected)
        self.assertNotIn("de_division_of_corporations", selected)


if __name__ == "__main__":
    unittest.main()
