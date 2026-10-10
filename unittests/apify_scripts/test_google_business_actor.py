"""
Unit tests for scripts/apify-scripts/google-business matching and dataset rows.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_google_business_actor

No live Google requests.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "scripts" / "apify-scripts" / "google-business" / "src"

from unittests.lead_automation.test_crm_enrich_match import (  # noqa: E402
    BASECAMP,
    GOLDEN,
    STAKER,
    STRIKER,
    match as crm_match,
)


def _load(name):
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    spec = importlib.util.spec_from_file_location(f"google_business_actor_{name}", _SRC / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mapping = _load("mapping")


class FakeMaps:
    def __init__(self, listings=None, blocked=False):
        self.google_blocked = False
        self.listings = listings or []
        self.blocked = blocked
        self.calls = []

    def search_location(self, keyword, city, state, max_pages=1, max_results=5):
        self.calls.append(("search", keyword, city, state, max_pages, max_results))
        if self.blocked:
            self.google_blocked = True
            return []
        return list(self.listings)

    def enrich_listing(self, listing):
        self.calls.append(("enrich", listing.get("business_name")))
        if self.google_blocked:
            raise AssertionError("enrich_listing called after a block")
        return dict(listing)


class TestGoogleInput(unittest.TestCase):
    def test_query_requires_state_and_stays_on_maps(self):
        settings = mapping.read_run_settings({"maxSearches": 1, "includeEmails": False})
        queries = mapping.queries_from_input({
            "name": "Northwind Customs LLC",
            "city": "Olean",
            "county": "Cattaraugus County",
            "state": "NY",
            "maxResults": 3,
        }, settings)
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["state"], "NY")
        self.assertEqual(queries[0]["county"], "Cattaraugus")
        self.assertEqual(queries[0]["maxResults"], 3)
        self.assertEqual(settings["min_confidence"], 80)
        self.assertEqual(settings["low_floor"], 60)
        self.assertFalse(settings["include_emails"])
        url = mapping.maps_query_url("Northwind Customs Olean NY")
        self.assertIn("/maps/search/", url)
        self.assertNotIn("google.com/search?", url)

    def test_missing_state_is_rejected(self):
        settings = mapping.read_run_settings({})
        with self.assertRaises(ValueError):
            mapping.queries_from_input({"name": "Acme"}, settings)

    def test_source_does_not_call_web_search_or_first_result_fallback(self):
        text = "\n".join(
            (_SRC / name).read_text(encoding="utf-8")
            for name in ("mapping.py", "main.py")
        )
        self.assertNotIn("https://www.google.com/search", text)
        self.assertNotIn("leadenrich_playwright", text)
        self.assertNotIn("_best_listing", text)
        self.assertIn("search_location", text)
        self.assertIn("enrich_listing", text)
        self.assertIn("select_match", text)


class TestGoogleDataset(unittest.TestCase):
    def setUp(self):
        self.zips = crm_match.load_zip_county()
        self.npas = crm_match.load_npa_state()

    def _row(self, lead, listings, query):
        selection = mapping.score_candidates(
            lead,
            listings,
            zip_county=self.zips,
            npa_state=self.npas,
        )
        self.assertIsNone(selection["winner"])
        return mapping.dataset_from_selection(query, selection), selection

    def test_striker_is_not_a_match(self):
        query = {"name": STRIKER["business_name"], "state": "NY", "county": "Cattaraugus"}
        row, selection = self._row(STRIKER, [STAKER], query)
        self.assertEqual(row["decision"], "no_match")
        self.assertNotEqual(row["decision"], "match")
        self.assertIn("distinctive_token_missing", row["hardRejects"])
        self.assertEqual(row["candidate"]["business_name"], "C. Staker Remodeling")
        self.assertEqual(selection["decision"], "no_match")
        for key in ("query", "decision", "score", "breakdown", "hardRejects", "candidate", "sourceStatus", "scrapedAt"):
            self.assertIn(key, row)

    def test_basecamp_is_not_a_match(self):
        query = {"name": BASECAMP["business_name"], "city": "Denver", "state": "CO"}
        row, selection = self._row(BASECAMP, [GOLDEN], query)
        self.assertEqual(row["decision"], "no_match")
        self.assertIsNone(selection["winner"])
        self.assertIn("address_mismatch", row["hardRejects"])
        self.assertEqual(row["candidate"]["business_name"], "Base Camp at Golden Gate Canyon")

    def test_first_listing_is_not_used_when_a_later_one_matches(self):
        lead = {
            "business_name": "NORTHWIND CUSTOMS LLC",
            "address": "NY",
            "business_description": "state=NY; county=Cattaraugus; city=;",
            "tags": ["ny"],
        }
        good = {
            "business_name": "Northwind Customs",
            "address": "1 Main St, Olean, NY 14760",
            "phone": "(716) 555-0100",
        }
        selection = mapping.score_candidates(
            lead,
            [STAKER, good],
            zip_county=self.zips,
            npa_state=self.npas,
        )
        row = mapping.dataset_from_selection({"name": lead["business_name"], "state": "NY"}, selection)
        self.assertEqual(row["decision"], "match")
        self.assertEqual(selection["winner"]["name"], "Northwind Customs")
        self.assertEqual(row["candidate"]["business_name"], "Northwind Customs")
        self.assertNotEqual(row["candidate"]["business_name"], STAKER["business_name"])

    def test_empty_listings_are_no_match(self):
        settings = mapping.read_run_settings({"includeEmails": False, "maxSearches": 1})
        query = mapping.queries_from_input({
            "name": "Northwind Customs LLC",
            "state": "NY",
            "city": "Olean",
        }, settings)[0]
        row = mapping.score_query(query, [], settings, {}, {})
        self.assertEqual(row["decision"], "no_match")
        self.assertIsNone(row["candidate"])
        self.assertNotIn("emails", row)
        self.assertEqual(row["sourceStatus"], "ok")

    def test_block_stops_before_enrich(self):
        session = FakeMaps(blocked=True)
        query = {
            "name": "Northwind Customs LLC",
            "city": "Olean",
            "county": "Cattaraugus",
            "state": "NY",
            "maxResults": 3,
        }
        listings, blocked = mapping.collect_listings(session, query)
        self.assertTrue(blocked)
        self.assertEqual(listings, [])
        self.assertEqual(session.calls[0][0], "search")
        self.assertNotIn("near", session.calls[0][1])
        self.assertEqual([call[0] for call in session.calls], ["search"])

    def test_collect_enriches_maps_listings(self):
        session = FakeMaps(listings=[{"business_name": "Northwind Customs", "profile_url": "https://www.google.com/maps/place/x"}])
        query = {
            "name": "Northwind Customs LLC",
            "city": "Olean",
            "state": "NY",
            "maxResults": 3,
        }
        listings, blocked = mapping.collect_listings(session, query)
        self.assertFalse(blocked)
        self.assertEqual(listings[0]["business_name"], "Northwind Customs")
        self.assertEqual([call[0] for call in session.calls], ["search", "enrich"])
