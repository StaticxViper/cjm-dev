"""
Unit tests for scripts/city_data/property_city_lookup.py

Run from repo root:
    python -m unittest unittests.city_data.test_property_city_lookup
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _import_lookup():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    if "scripts.city_data.property_city_lookup" in sys.modules:
        return importlib.reload(sys.modules["scripts.city_data.property_city_lookup"])
    return importlib.import_module("scripts.city_data.property_city_lookup")


def _get_lookup_or_skip():
    try:
        return _import_lookup(), None
    except Exception as exc:
        return None, exc


LOOKUP, _IMPORT_ERR = _get_lookup_or_skip()
SKIP = unittest.skipIf(
    LOOKUP is None,
    f"property_city_lookup import failed (install project deps): {_IMPORT_ERR!r}",
)


@SKIP
class TestParseAddressParts(unittest.TestCase):
    def test_full_us_address(self):
        parts = LOOKUP.parse_address_parts("123 Main St, Clementon, NJ 08021")
        self.assertEqual(parts["street"], "123 Main St")
        self.assertEqual(parts["city"], "Clementon")
        self.assertEqual(parts["state"], "NJ")
        self.assertEqual(parts["zip"], "08021")

    def test_city_state_only(self):
        parts = LOOKUP.parse_address_parts("Cherry Hill, NJ")
        self.assertIsNone(parts["street"])
        self.assertEqual(parts["city"], "Cherry Hill")
        self.assertEqual(parts["state"], "NJ")

    def test_city_state_zip(self):
        parts = LOOKUP.parse_address_parts("Clementon, NJ 08021")
        self.assertIsNone(parts["street"])
        self.assertEqual(parts["city"], "Clementon")
        self.assertEqual(parts["state"], "NJ")
        self.assertEqual(parts["zip"], "08021")

    def test_lowercase_state_in_city_chunk(self):
        parts = LOOKUP.parse_address_parts("132 la Cascata, Clementon nj, 08021")
        self.assertEqual(parts["street"], "132 la Cascata")
        self.assertEqual(parts["city"], "Clementon")
        self.assertEqual(parts["state"], "NJ")
        self.assertEqual(parts["zip"], "08021")

    def test_empty_address(self):
        parts = LOOKUP.parse_address_parts("")
        self.assertIsNone(parts["city"])
        self.assertIsNone(parts["state"])


@SKIP
class TestParseFieldsCsv(unittest.TestCase):
    def test_default_all_groups(self):
        self.assertEqual(LOOKUP.parse_fields_csv(None), list(LOOKUP.FIELD_GROUPS))

    def test_comma_separated(self):
        self.assertEqual(
            LOOKUP.parse_fields_csv("population, crime"),
            ["population", "crime"],
        )

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            LOOKUP.parse_fields_csv("population,not_a_field")


@SKIP
class TestBuildEnvelope(unittest.TestCase):
    def test_shapes_scrape_result(self):
        scrape_payload = {
            "scraped_at": "2026-09-05T19:00:00+00:00",
            "results": [
                {
                    "city": "Clementon",
                    "state": "NJ",
                    "urls": {
                        "city": "https://www.city-data.com/city/Clementon-New-Jersey.html",
                        "crime": "https://www.city-data.com/crime/crime-Clementon-New-Jersey.html",
                    },
                    "ok": True,
                    "population": {"year": 2024, "total": 5600},
                    "income": {"median_household": 65754},
                    "crime": {"index": 315, "index_year": 2025},
                }
            ],
        }
        query = {
            "street": "123 Main St",
            "city": "Clementon",
            "state": "NJ",
            "zip": "08021",
        }
        envelope = LOOKUP.build_envelope(
            "123 Main St, Clementon, NJ 08021",
            query,
            scrape_payload,
        )
        self.assertEqual(envelope["schema_version"], "1.0")
        self.assertEqual(envelope["source"], "city-data.com")
        self.assertTrue(envelope["ok"])
        self.assertIsNone(envelope["error"])
        self.assertEqual(envelope["query"]["city"], "Clementon")
        self.assertEqual(envelope["demographics"]["population"]["total"], 5600)
        self.assertEqual(envelope["demographics"]["income"]["median_household"], 65754)
        self.assertNotIn("crime", envelope["demographics"])
        self.assertEqual(envelope["crime"]["index"], 315)
        self.assertIn("crime", envelope["urls"])

    def test_parse_failure_envelope(self):
        envelope = LOOKUP.build_envelope(
            "not-an-address",
            {"street": "not-an-address", "city": None, "state": None, "zip": None},
            error="Could not parse city and state from address",
        )
        self.assertFalse(envelope["ok"])
        self.assertIn("parse", envelope["error"].lower())
        self.assertEqual(envelope["demographics"], {})
        self.assertEqual(envelope["crime"], {})

    def test_scrape_failure_propagates(self):
        scrape_payload = {
            "scraped_at": "2026-09-05T19:00:00+00:00",
            "results": [
                {
                    "city": "Nowhere",
                    "state": "NJ",
                    "urls": {"city": "https://example.com"},
                    "ok": False,
                    "error": "City page not found",
                }
            ],
        }
        envelope = LOOKUP.build_envelope(
            "1 Fake St, Nowhere, NJ 00000",
            {"street": "1 Fake St", "city": "Nowhere", "state": "NJ", "zip": "00000"},
            scrape_payload,
        )
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"], "City page not found")


@SKIP
class TestLookupAddress(unittest.TestCase):
    def test_lookup_calls_scraper_and_skips_ingest(self):
        scrape_payload = {
            "scraped_at": "2026-09-05T19:00:00+00:00",
            "results": [
                {
                    "city": "Clementon",
                    "state": "NJ",
                    "urls": {"city": "https://example.com/city", "crime": "https://example.com/crime"},
                    "ok": True,
                    "population": {"total": 5600},
                    "crime": {"index": 100},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out.json"
            with mock.patch.object(LOOKUP, "scrape_cities", return_value=scrape_payload) as scrape:
                with mock.patch.dict(os.environ, {"CITY_DATA_INGEST_SKIP": "1"}, clear=False):
                    envelope = LOOKUP.lookup_address(
                        "123 Main St, Clementon, NJ 08021",
                        output_path=out,
                    )
            scrape.assert_called_once()
            config = scrape.call_args[0][0]
            self.assertEqual(config["cities"][0]["city"], "Clementon")
            self.assertEqual(config["cities"][0]["state"], "NJ")
            self.assertTrue(out.exists())
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(saved["demographics"]["population"]["total"], 5600)
            self.assertEqual(envelope["crime"]["index"], 100)

    def test_lookup_bad_address_writes_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out.json"
            with mock.patch.object(LOOKUP, "scrape_cities") as scrape:
                with mock.patch.dict(os.environ, {"CITY_DATA_INGEST_SKIP": "1"}, clear=False):
                    envelope = LOOKUP.lookup_address("incomplete", output_path=out)
            scrape.assert_not_called()
            self.assertFalse(envelope["ok"])
            self.assertTrue(out.exists())

    def test_maybe_ingest_posts_to_lovable_endpoint(self):
        payload = {"ok": True, "schema_version": "1.0"}
        with mock.patch.dict(
            os.environ,
            {
                "CITY_DATA_INGEST_KEY": "test-key",
                "CITY_DATA_INGEST_SKIP": "",
            },
            clear=False,
        ):
            os.environ.pop("CITY_DATA_INGEST_SKIP", None)
            with mock.patch(
                "helper_scripts.api_manager.api_manager.APIManager"
            ) as mock_mgr:
                instance = mock_mgr.return_value
                LOOKUP.maybe_ingest(payload)
                instance.build_request.assert_called_once()
                kwargs = instance.build_request.call_args.kwargs
                self.assertEqual(
                    kwargs["base_url"],
                    "https://project--b0a20b71-38d1-47e5-9069-be4eabcd8b2a.lovable.app",
                )
                self.assertEqual(kwargs["endpoint"], "/api/public/city-data")
                self.assertEqual(kwargs["api"], "City Data Ingest")
                self.assertEqual(kwargs["json_body"], payload)
                self.assertEqual(kwargs["method"], "POST")

    def test_maybe_ingest_requires_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CITY_DATA_INGEST_KEY", None)
            os.environ.pop("CITY_DATA_INGEST_SKIP", None)
            with self.assertRaises(RuntimeError):
                LOOKUP.maybe_ingest({"ok": True})


if __name__ == "__main__":
    unittest.main()
