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
            ("ny_sla_pending_licenses", "Example Tavern"),
            ("co_liquor_recently_approved", "Example Brew Pub"),
            ("nyc_restaurant_inspections", "EXAMPLE NOODLE BAR"),
        ):
            payload = resolve_fixture_dates(load_fixture_json(source_id))
            records = adapters[source_id].parse_payload(payload)
            self.assertTrue(records, source_id)
            self.assertEqual(records[0].business_name, expected_name)
            self.assertTrue(records[0].newness_evidence, source_id)
            self.assertTrue(records[0].newness_evidence[0]["date"], source_id)

    def test_liquor_application_prefers_dba_and_keeps_legal_name_as_contact(self):
        payload = resolve_fixture_dates(load_fixture_json("ny_sla_pending_licenses"))
        records = _adapters()["ny_sla_pending_licenses"].parse_payload(payload)
        tavern, market = records
        self.assertEqual(tavern.business_name, "Example Tavern")
        self.assertEqual(tavern.public_contacts[0]["name"], "Example Tavern Holdings LLC")
        self.assertEqual(tavern.public_contacts[0]["role"], "license_applicant")
        self.assertEqual(market.business_name, "Example Corner Market Inc")
        self.assertEqual(tavern.category, "Restaurant")
        self.assertEqual(tavern.business_status, "Under Review")
        self.assertEqual(tavern.state, "NY")
        self.assertEqual(tavern.newness_evidence[0]["type"], "license_date")
        self.assertIsNone(tavern.formation_date)
        self.assertTrue(tavern.source_record_url.endswith("application_id=NA-0340-26-900001"))

    def test_inspection_maps_borough_to_county_and_collapses_spaces(self):
        payload = resolve_fixture_dates(load_fixture_json("nyc_restaurant_inspections"))
        records = _adapters()["nyc_restaurant_inspections"].parse_payload(payload)
        first = records[0]
        self.assertEqual(first.county, "Kings")
        self.assertEqual(first.city, "Brooklyn")
        self.assertEqual(first.address, "675 EXAMPLE AVENUE, Brooklyn, NY, 11225")
        self.assertEqual(first.business_status, "Grade A")
        self.assertEqual(first.description, "Chinese")
        self.assertEqual(first.opening_date, first.newness_evidence[0]["date"])
        self.assertEqual(records[2].county, "New York")
        self.assertEqual(records[2].business_status, "Not yet graded")

    def test_new_opening_queries_filter_on_the_server(self):
        adapters = _adapters()
        nyc = adapters["nyc_restaurant_inspections"]._page_url("2026-10-01", 200, 0)
        self.assertIn("$select=distinct%20camis,", nyc)
        self.assertIn("Initial%20Inspection", nyc)
        co = adapters["co_liquor_recently_approved"]._page_url("2026-10-01", 200, 0)
        self.assertIn("issue_date%20%3E%3D%20%272026-10-01T00%3A00%3A00.000%27", co)
        self.assertIn("NOT%20LIKE%20%27%25Permit%25%27", co)
        ny = adapters["ny_sla_pending_licenses"]._page_url("2026-10-01", 200, 0)
        self.assertIn("Direct%20Shipper%20Wine", ny)

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
        self.assertIn("ny_sla_pending_licenses", selected)
        self.assertIn("nyc_restaurant_inspections", selected)
        self.assertNotIn("boulder_restaurant_inspections", selected)
        self.assertNotIn("google_search", selected)
        self.assertNotIn("example_public_table", selected)
        self.assertNotIn("nj_dores", selected)
        self.assertNotIn("nj_open_data", selected)
        self.assertNotIn("de_division_of_corporations", selected)


if __name__ == "__main__":
    unittest.main()
