"""
Unit tests for scripts/apify-scripts/google-business matching and dataset rows.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_google_business_actor

No live Google requests.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
            "name": "Wegmans Food Markets",
            "city": "Rochester",
            "county": "Monroe County",
            "state": "NY",
            "maxResults": 3,
        }, settings)
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["state"], "NY")
        self.assertEqual(queries[0]["county"], "Monroe")
        self.assertEqual(queries[0]["maxResults"], 3)
        self.assertEqual(settings["min_confidence"], 80)
        self.assertEqual(settings["low_floor"], 60)
        self.assertFalse(settings["include_emails"])
        url = mapping.maps_query_url("Wegmans Food Markets Rochester NY")
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
        self.assertNotIn("proxyConfiguration", text)
        self.assertNotIn("unused_proxy_note", (_SRC / "runtime.py").read_text(encoding="utf-8"))
        actor = json.loads((_SRC.parent / ".actor" / "actor.json").read_text(encoding="utf-8"))
        self.assertEqual(actor["defaultRunOptions"]["timeoutSecs"], 900)
        form = json.loads((_SRC.parent / ".actor" / "input_schema.json").read_text(encoding="utf-8"))
        self.assertNotIn("proxyConfiguration", form["properties"])
        self.assertEqual(form["properties"]["queries"]["prefill"][0]["name"], "Wegmans Food Markets")
        dataset = json.loads((_SRC.parent / ".actor" / "dataset_schema.json").read_text(encoding="utf-8"))
        for key in ("query", "decision", "score", "breakdown", "hardRejects", "candidate", "emails"):
            self.assertIn(key, dataset["fields"]["fields"])
        self.assertIn("detail", dataset["views"])
        pricing = json.loads((_SRC.parent / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        event = pricing["actorChargeEvents"]["result"]
        self.assertTrue(event["isPrimaryEvent"])
        self.assertGreater(event["eventPriceUsd"], 0)


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
        self.assertIsNone(row["candidate"])
        self.assertNotIn("Staker", json.dumps(row))
        self.assertEqual(selection["decision"], "no_match")
        self.assertFalse(mapping.billable_row(row))
        for key in ("query", "decision", "score", "breakdown", "hardRejects", "candidate", "sourceStatus", "scrapedAt"):
            self.assertIn(key, row)

    def test_basecamp_is_not_a_match(self):
        query = {"name": BASECAMP["business_name"], "city": "Denver", "state": "CO"}
        row, selection = self._row(BASECAMP, [GOLDEN], query)
        self.assertEqual(row["decision"], "no_match")
        self.assertIsNone(selection["winner"])
        self.assertIn("address_mismatch", row["hardRejects"])
        self.assertIsNone(row["candidate"])
        self.assertNotIn("Golden", json.dumps(row))

    def test_empty_listings_are_no_match(self):
        settings = mapping.read_run_settings({"includeEmails": False, "maxSearches": 1})
        query = mapping.queries_from_input({
            "name": "Wegmans Food Markets",
            "state": "NY",
            "city": "Rochester",
        }, settings)[0]
        row = mapping.score_query(query, [], settings, {}, {})
        self.assertEqual(row["decision"], "no_match")
        self.assertIsNone(row["candidate"])
        self.assertNotIn("emails", row)
        self.assertEqual(row["sourceStatus"], "ok")

    def test_block_stops_before_enrich(self):
        session = FakeMaps(blocked=True)
        query = {
            "name": "Wegmans Food Markets",
            "city": "Rochester",
            "county": "Monroe",
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
        session = FakeMaps(listings=[{"business_name": "Wegmans Food Markets", "profile_url": "https://www.google.com/maps/place/x"}])
        query = {
            "name": "Wegmans Food Markets",
            "city": "Rochester",
            "state": "NY",
            "maxResults": 3,
        }
        listings, blocked = mapping.collect_listings(session, query)
        self.assertFalse(blocked)
        self.assertEqual(listings[0]["business_name"], "Wegmans Food Markets")
        self.assertEqual([call[0] for call in session.calls], ["search", "enrich"])


WEGMANS_ROCHESTER = {
    "business_name": "Wegmans Food Markets",
    "address": "1750 East Ave, Rochester, NY 14610",
    "category": "Grocery store",
    "profile_url": "https://www.google.com/maps/place/Wegmans+Food+Markets/",
}
WEGMANS_CARD = {
    "business_name": "Wegmans",
    "address": "1750 East Ave, Rochester, NY 14610",
    "category": "Grocery store",
}
WHOLE_FOODS = {
    "business_name": "Whole Foods Market",
    "address": "800 Jefferson Rd, Rochester, NY 14623",
    "category": "Grocery store",
}
WEGMANS_WILLIAMSVILLE = {
    "business_name": "Wegmans",
    "address": "5275 Main St, Williamsville, NY 14221",
    "category": "Grocery store",
}


class _Locator:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count

    def first(self):
        return self

    def is_visible(self):
        return False


class _PlacePage:
    def __init__(self, url, h1, feed=0):
        self.url = url
        self.h1 = h1
        self.feed = feed
        self.scripts = []

    def goto(self, *args, **kwargs):
        return None

    def content(self):
        return "<html><body>maps place</body></html>"

    def locator(self, selector):
        count = self.feed if 'role="feed"' in selector else 0
        return _Locator(count)

    def evaluate(self, script, *args):
        self.scripts.append(script)
        if "h1" not in script:
            raise AssertionError(script)
        return {"name": self.h1, "url": self.url}


class TestWegmansMatch(unittest.TestCase):
    def setUp(self):
        self.zips = crm_match.load_zip_county()
        self.npas = crm_match.load_npa_state()
        self.settings = mapping.read_run_settings({"includeEmails": False, "maxSearches": 1})
        self.query = mapping.queries_from_input({
            "name": "Wegmans Food Markets",
            "city": "Rochester",
            "county": "Monroe",
            "state": "NY",
            "maxResults": 5,
        }, self.settings)[0]

    def _score(self, listings):
        return mapping.score_query(self.query, listings, self.settings, self.zips, self.npas)

    def test_full_place_name_matches_the_rochester_store(self):
        row = self._score([WHOLE_FOODS, WEGMANS_ROCHESTER])
        self.assertEqual(row["decision"], "match")
        self.assertGreaterEqual(row["score"], 80)
        self.assertEqual(row["candidate"]["business_name"], "Wegmans Food Markets")
        self.assertIn("1750 East Ave", row["candidate"]["address"])
        self.assertNotIn("Whole Foods", json.dumps(row))
        self.assertTrue(mapping.billable_row(row))

    def test_short_card_is_kept_when_whole_foods_scores_higher(self):
        row = self._score([WHOLE_FOODS, WEGMANS_CARD])
        self.assertEqual(row["decision"], "match")
        self.assertGreaterEqual(row["score"], 80)
        self.assertEqual(row["candidate"]["business_name"], "Wegmans")
        self.assertIn("Rochester", row["candidate"]["address"])
        self.assertNotIn("Whole Foods", json.dumps(row))
        self.assertTrue(mapping.billable_row(row))

    def test_whole_foods_alone_is_omitted(self):
        row = self._score([WHOLE_FOODS])
        self.assertEqual(row["decision"], "no_match")
        self.assertIsNone(row["candidate"])
        self.assertIsNone(row["score"])
        self.assertIn("brand_token_missing", row["hardRejects"])
        self.assertNotIn("Whole Foods", json.dumps(row))
        self.assertFalse(mapping.billable_row(row))

    def test_chain_keeps_rochester_and_drops_williamsville(self):
        row = self._score([WEGMANS_WILLIAMSVILLE, WHOLE_FOODS, WEGMANS_ROCHESTER])
        self.assertEqual(row["decision"], "match")
        self.assertIn("Rochester", row["candidate"]["address"])
        self.assertNotIn("Williamsville", json.dumps(row))
        self.assertNotIn("Whole Foods", json.dumps(row))

    def test_wrong_city_chain_store_is_not_a_candidate(self):
        row = self._score([WEGMANS_WILLIAMSVILLE])
        self.assertEqual(row["decision"], "no_match")
        self.assertIsNone(row["candidate"])
        self.assertIsNone(row["score"])
        self.assertEqual(row["hardRejects"], ["city_mismatch"])
        self.assertNotIn("Williamsville", json.dumps(row))


class TestDirectPlace(unittest.TestCase):
    def test_place_redirect_uses_the_heading_only(self):
        import playwright_discovery as discovery

        page = _PlacePage(
            "https://www.google.com/maps/place/Wegmans+Food+Markets/@43.1,-77.5,17z",
            "Wegmans Food Markets",
            feed=0,
        )
        session = discovery.BusinessDiscoverySession()
        session._page = page
        with patch.object(discovery.time, "sleep"):
            found = session.search_listings(
                "Wegmans Food Markets",
                "Rochester",
                "NY",
                max_pages=1,
                max_results=5,
            )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["business_name"], "Wegmans Food Markets")
        self.assertIn("/maps/place/", found[0]["profile_url"])
        self.assertTrue(all("h1" in script for script in page.scripts))

    def test_results_feed_is_not_replaced_by_the_heading(self):
        import playwright_discovery as discovery

        page = _PlacePage(
            "https://www.google.com/maps/search/Wegmans",
            "Wegmans Food Markets",
            feed=3,
        )
        session = discovery.BusinessDiscoverySession()
        self.assertIsNone(session._direct_place_listing(page))
        place = _PlacePage(
            "https://www.google.com/maps/place/Wegmans/@43.1,-77.5,17z",
            "",
            feed=0,
        )
        self.assertIsNone(session._direct_place_listing(place))
