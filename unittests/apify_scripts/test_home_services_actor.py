"""
Unit tests for scripts/apify-scripts/home-services matching, enrichment, and charges.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_home_services_actor

No live Google or website requests.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "scripts" / "apify-scripts" / "home-services" / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "home_services"


def _load(name):
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    spec = importlib.util.spec_from_file_location(f"home_services_actor_{name}", _SRC / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mapping = _load("mapping")

MAPS_ROBOTS = (_FIXTURES / "robots_allow_maps.txt").read_text(encoding="utf-8")
SITE_BLOCK = (_FIXTURES / "robots_disallow_site.txt").read_text(encoding="utf-8")
DATASET = json.loads((_FIXTURES / "maps_dataset.json").read_text(encoding="utf-8"))


def _flags_off():
    return {
        "includeEmail": False,
        "includeWebsiteQuality": False,
        "includeScore": False,
    }


class FakeMaps:
    def __init__(self, listings=None, blocked=False):
        self.google_blocked = False
        self.listings = listings or []
        self.blocked = blocked
        self.calls = []
        self.closed = False

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

    def close(self):
        self.closed = True


class TestHomeServicesInput(unittest.TestCase):
    def test_city_state_area_and_caps(self):
        settings = mapping.read_settings({
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            "maxItems": 25,
            "maxSearches": 2,
            "maxResults": 3,
            **_flags_off(),
        })
        self.assertEqual(settings["niche"]["id"], "pool_specialists")
        self.assertEqual(settings["area"]["city"], "Rochester")
        self.assertEqual(settings["area"]["state"], "NY")
        self.assertEqual(settings["max_items"], 25)
        self.assertEqual(len(settings["searches"]), 2)
        self.assertEqual(settings["searches"][0]["city"], "Rochester")
        self.assertEqual(settings["searches"][0]["state"], "NY")
        self.assertNotIn("near", settings["searches"][0]["name"])
        self.assertFalse(settings["flags"]["email"])
        county = mapping.read_settings({
            "niche": "pool_specialists",
            "area": "Monroe County, NY",
            "maxSearches": 1,
            **_flags_off(),
        })
        self.assertEqual(county["area"]["county"], "Monroe")
        self.assertIsNone(county["area"]["city"])
        self.assertEqual(county["searches"][0]["county"], "Monroe")
        self.assertIsNone(county["searches"][0]["city"])

    def test_region_name_and_explicit_city(self):
        regions = {
            "finger_lakes": {
                "state": "NY",
                "cities": ["Rochester", "Canandaigua"],
                "counties": ["Monroe"],
                "zips": [],
            }
        }
        with patch.object(mapping, "load_regions", return_value=regions):
            settings = mapping.read_settings({
                "niche": "Pool Leak Detection / Pool Tile / Pool-Equipment Repair Specialists",
                "area": "finger_lakes",
                "mapsDataset": [],
            })
        self.assertEqual(settings["area"]["region"], "finger_lakes")
        self.assertEqual(settings["area"]["state"], "NY")
        self.assertEqual(settings["area"]["cities"], ["Rochester", "Canandaigua"])
        self.assertEqual(settings["area"]["county"], "Monroe")
        self.assertEqual(settings["listings"], [])

    def test_unknown_niche_and_over_cap_are_rejected(self):
        with self.assertRaises(ValueError):
            mapping.read_settings({"niche": "not_a_niche", "area": "Rochester, NY"})
        with self.assertRaises(ValueError):
            mapping.read_settings({"niche": "pool_specialists", "area": "Rochester, NY", "maxItems": 26})
        with self.assertRaises(ValueError):
            mapping.read_settings({"niche": "pool_specialists"})

    def test_schema_events_and_limits(self):
        actor_dir = _SRC.parent
        actor = json.loads((actor_dir / ".actor" / "actor.json").read_text(encoding="utf-8"))
        self.assertEqual(actor["defaultRunOptions"]["timeoutSecs"], 900)
        form = json.loads((actor_dir / ".actor" / "input_schema.json").read_text(encoding="utf-8"))
        self.assertIn("pool_specialists", form["properties"]["niche"]["enum"])
        self.assertEqual(form["properties"]["maxItems"]["maximum"], 25)
        self.assertNotIn("proxy", form["properties"])
        self.assertIn("headless", form["properties"])
        dataset = json.loads((actor_dir / ".actor" / "dataset_schema.json").read_text(encoding="utf-8"))
        for key in ("business", "phone", "website", "rating", "review_count", "email", "website_quality", "lead_score", "intent_signals"):
            self.assertIn(key, dataset["fields"]["fields"])
        self.assertIn("detail", dataset["views"])
        pricing = json.loads((actor_dir / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        self.assertEqual(set(pricing["actorChargeEvents"]), {"place", "email-found", "score"})
        self.assertTrue(pricing["actorChargeEvents"]["place"]["isPrimaryEvent"])
        self.assertGreater(pricing["actorChargeEvents"]["email-found"]["eventPriceUsd"], 0)
        self.assertGreater(pricing["actorChargeEvents"]["score"]["eventPriceUsd"], 0)

    def test_source_does_not_call_places_or_web_search(self):
        text = "\n".join(path.read_text(encoding="utf-8") for path in _SRC.glob("*.py"))
        self.assertNotIn("maps.googleapis", text)
        self.assertNotIn("places.googleapis", text)
        self.assertNotIn("google.com/search", text)
        self.assertNotIn("enrich_lead_with_email", text)
        self.assertNotIn("ProxyConfiguration", text)
        self.assertIn("score_query", text)
        self.assertIn("collect_listings", text)
        self.assertIn("score_intent_lead", text)


class TestHomeServicesDataset(unittest.TestCase):
    def _run(self, extra=None, **hooks):
        payload = {
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            "mapsDataset": DATASET,
            "maxItems": 10,
            **_flags_off(),
            "includeScore": True,
        }
        if extra:
            payload.update(extra)
        return mapping.run_sync(payload, session_factory=self._no_session, **hooks)

    def _no_session(self, _settings):
        raise AssertionError("Maps session should not start for a dataset")

    def test_accepts_city_match_and_rejects_the_others(self):
        rows, summary = self._run()
        self.assertEqual([row["decision"] for row in rows], ["accepted", "rejected", "rejected"])
        accepted = rows[0]
        self.assertEqual(accepted["business"], "Aqua Leak Pros")
        self.assertGreaterEqual(accepted["match_score"], 80)
        self.assertEqual(accepted["review_count"], 32)
        self.assertEqual(accepted["rating"], 4.8)
        self.assertIsInstance(accepted["lead_score"], int)
        self.assertTrue(accepted["intent_signals"])
        self.assertNotIn("Williamsville", json.dumps(accepted))
        self.assertNotIn("Leslie", json.dumps(accepted))
        self.assertEqual(rows[1]["hardRejects"], ["city_mismatch"])
        self.assertEqual(rows[1]["business"], "Aqua Leak Pros")
        self.assertIn("williamsville", (rows[1]["website"] or "").lower())
        self.assertEqual(rows[2]["hardRejects"], ["negative_keyword"])
        self.assertEqual(summary["accepted"], 1)
        self.assertEqual(summary["rejected"], 2)
        self.assertEqual(summary["blocked"], 0)
        self.assertEqual(mapping.billable_events(accepted), ["place", "score"])
        self.assertEqual(mapping.billable_events(rows[1]), [])
        self.assertEqual(mapping.billable_events(rows[2]), [])

    def test_closed_and_directory_are_not_billed(self):
        listings = [
            {
                "business_name": "Aqua Leak Pros",
                "address": "10 East Ave, Rochester, NY 14604",
                "phone": "(212) 555-0100",
                "website": "https://aqualeakpros.com/",
                "business_status": "CLOSED_PERMANENTLY",
                "place_id": "place-closed",
            },
            {
                "business_name": "Harbor Pool Tile",
                "address": "12 East Ave, Rochester, NY 14604",
                "phone": "(212) 555-0111",
                "website": "https://www.yelp.com/biz/harbor-pool-tile",
                "place_id": "place-yelp",
            },
        ]
        rows, summary = mapping.run_sync({
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            "mapsDataset": listings,
            **_flags_off(),
        }, session_factory=self._no_session)
        self.assertEqual(rows[0]["decision"], "rejected")
        self.assertIn("permanently_closed", rows[0]["hardRejects"])
        self.assertEqual(rows[1]["decision"], "rejected")
        self.assertIn("website_is_directory", rows[1]["hardRejects"])
        self.assertEqual(summary["accepted"], 0)
        self.assertEqual(summary["rejected"], 2)
        self.assertEqual(mapping.billable_events(rows[0]), [])
        self.assertEqual(mapping.billable_events(rows[1]), [])

    def test_max_items_stops_before_later_listings(self):
        ordered = [DATASET[1], DATASET[0], DATASET[2]]
        rows, summary = self._run({"mapsDataset": ordered, "maxItems": 1, "includeScore": False})
        self.assertEqual([row["decision"] for row in rows], ["rejected", "accepted"])
        self.assertEqual(summary["accepted"], 1)
        self.assertEqual(summary["rejected"], 1)
        self.assertIsNone(rows[1]["lead_score"])
        self.assertIsNone(rows[1]["email"])
        self.assertEqual(mapping.billable_events(rows[1]), ["place"])
        self.assertNotIn("Leslie", json.dumps(rows))

    def test_dataset_without_area_uses_the_listing_address(self):
        rows, _summary = mapping.run_sync({
            "niche": "pool_specialists",
            "mapsDataset": [DATASET[0], DATASET[1]],
            **_flags_off(),
        }, session_factory=self._no_session)
        self.assertEqual([row["decision"] for row in rows], ["accepted", "accepted"])

    def test_state_only_does_not_copy_the_card_city(self):
        rows, summary = mapping.run_sync({
            "niche": "pool_specialists",
            "state": "NY",
            "mapsDataset": [DATASET[0]],
            **_flags_off(),
        }, session_factory=self._no_session)
        self.assertEqual(rows[0]["decision"], "rejected")
        self.assertEqual(summary["accepted"], 0)
        self.assertEqual(mapping.billable_events(rows[0]), [])


class TestHomeServicesEnrichment(unittest.TestCase):
    def test_email_and_score_bill_only_when_produced(self):
        calls = []

        def fetch(url):
            calls.append(("fetch", url))
            if "aqualeakpros.com" in url:
                return "User-agent: *\nAllow: /\n"
            return SITE_BLOCK

        def quality(url):
            calls.append(("quality", url))
            return {
                "website_quality_score": 70,
                "website_label": "Poor",
                "website_status": "ok",
                "website_issues": ["thin_copy"],
                "website_analysis": {"title": "Aqua Leak Pros", "has_contact_form": True},
            }

        def email(lead, website):
            calls.append(("email", website))
            return [{"email": "owner@aqualeakpros.com", "confidence": "HIGH"}]

        rows, summary = mapping.run_sync({
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            "mapsDataset": DATASET,
            "includeEmail": True,
            "includeWebsiteQuality": True,
            "includeScore": True,
        }, session_factory=self._no_session, fetch_text_fn=fetch, email_fn=email, quality_fn=quality)
        accepted = rows[0]
        self.assertEqual(accepted["email"], "owner@aqualeakpros.com")
        self.assertEqual(accepted["website_quality"], 70)
        self.assertEqual(accepted["website_label"], "Poor")
        self.assertIsInstance(accepted["lead_score"], int)
        self.assertEqual(mapping.billable_events(accepted), ["place", "email-found", "score"])
        self.assertEqual(summary["emailsFound"], 1)
        self.assertEqual(summary["scoresProduced"], 1)
        self.assertEqual([kind for kind, _url in calls if kind in {"quality", "email"}], ["quality", "email"])
        self.assertTrue(any("aqualeakpros.com/robots.txt" in url for _kind, url in calls if _kind == "fetch"))
        self.assertFalse(any("williamsville" in url or "leslies" in url for _kind, url in calls if _kind == "fetch"))

    def test_robots_disallow_skips_the_site_and_the_email_charge(self):
        def fetch(_url):
            return SITE_BLOCK

        def banned(*_args, **_kwargs):
            raise AssertionError("site fetch after robots disallow")

        rows, _summary = mapping.run_sync({
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            "mapsDataset": [DATASET[0]],
            "includeEmail": True,
            "includeWebsiteQuality": True,
            "includeScore": True,
        }, session_factory=self._no_session, fetch_text_fn=fetch, email_fn=banned, quality_fn=banned)
        row = rows[0]
        self.assertEqual(row["decision"], "accepted")
        self.assertEqual(row["website_status"], "robots_disallowed")
        self.assertIsNone(row["email"])
        self.assertIsNone(row["website_quality"])
        self.assertIsInstance(row["lead_score"], int)
        self.assertNotIn("no_conversion_path", [item["key"] for item in row["intent_signals"]])
        self.assertEqual(mapping.billable_events(row), ["place", "score"])

    def test_rejected_row_does_not_bill_even_if_fields_are_filled(self):
        self.assertEqual(mapping.billable_events({
            "decision": "rejected",
            "email": "owner@aqualeakpros.com",
            "lead_score": 10,
        }), [])
        self.assertEqual(mapping.billable_events({
            "decision": "accepted",
            "email": None,
            "lead_score": 0,
        }), ["place", "score"])
        self.assertEqual(mapping.billable_events({
            "decision": "blocked",
        }), [])

    def _no_session(self, _settings):
        raise AssertionError("Maps session should not start for a dataset")


class TestHomeServicesMaps(unittest.TestCase):
    def test_block_stops_before_the_next_search(self):
        session = FakeMaps(blocked=True)
        fetched = []

        def fetch(url):
            fetched.append(url)
            return MAPS_ROBOTS

        rows, summary = mapping.run_sync({
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            "maxSearches": 2,
            "maxItems": 5,
            **_flags_off(),
        }, session_factory=lambda _settings: session, fetch_text_fn=fetch)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "blocked")
        self.assertEqual(rows[0]["sourceStatus"], "blocked")
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(summary["accepted"], 0)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual([call[0] for call in session.calls], ["search"])
        self.assertNotIn("near", session.calls[0][1])
        self.assertEqual(session.calls[0][2], "Rochester")
        self.assertEqual(session.calls[0][3], "NY")
        self.assertTrue(session.closed)
        self.assertTrue(any("google.com/robots.txt" in url for url in fetched))
        self.assertFalse(any("google.com/search" in url for url in fetched))
        self.assertEqual(mapping.billable_events(rows[0]), [])

    def test_robots_disallow_does_not_open_maps(self):
        def factory(_settings):
            raise AssertionError("session started")

        rows, summary = mapping.run_sync({
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            **_flags_off(),
        }, session_factory=factory, fetch_text_fn=lambda _url: SITE_BLOCK)
        self.assertEqual(rows[0]["decision"], "error")
        self.assertEqual(rows[0]["sourceStatus"], "robots_disallowed")
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["accepted"], 0)
        self.assertIn("accepted", summary)
        self.assertIn("rejected", summary)
        self.assertIn("blocked", summary)

    def test_duplicate_place_is_kept_once_and_max_items_skips_later_searches(self):
        listing = {
            "business_name": "Aqua Leak Pros",
            "address": "10 East Ave, Rochester, NY 14604",
            "phone": "(212) 555-0100",
            "place_id": "place-aqua",
            "category": "Pool leak detection",
        }
        first = FakeMaps(listings=[listing])
        rows, summary = mapping.run_sync({
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            "maxSearches": 2,
            "maxItems": 5,
            **_flags_off(),
        }, session_factory=lambda _settings: first, fetch_text_fn=lambda _url: MAPS_ROBOTS)
        self.assertEqual(summary["accepted"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual([call[0] for call in first.calls].count("search"), 2)

        second = FakeMaps(listings=[listing, dict(listing, business_name="Tile Line Pool Repair", place_id="place-tile", address="20 East Ave, Rochester, NY 14604")])
        capped, capped_summary = mapping.run_sync({
            "niche": "pool_specialists",
            "area": "Rochester, NY",
            "maxSearches": 2,
            "maxItems": 1,
            **_flags_off(),
        }, session_factory=lambda _settings: second, fetch_text_fn=lambda _url: MAPS_ROBOTS)
        self.assertEqual(capped_summary["accepted"], 1)
        self.assertEqual(len(capped), 1)
        self.assertEqual([call[0] for call in second.calls].count("search"), 1)

    def test_error_summary_has_the_counters(self):
        _rows, summary = mapping.error_bundle(ValueError("bad niche"))
        self.assertEqual(summary["accepted"], 0)
        self.assertEqual(summary["rejected"], 0)
        self.assertEqual(summary["blocked"], 0)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["status"], "error")
