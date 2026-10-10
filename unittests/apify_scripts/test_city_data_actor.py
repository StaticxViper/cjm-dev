"""
Unit tests for scripts/apify-scripts/city-data input mapping and dataset rows.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_city_data_actor
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "scripts" / "apify-scripts" / "city-data" / "src"


def _load(name):
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    spec = importlib.util.spec_from_file_location(f"city_data_actor_{name}", _SRC / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mapping = _load("mapping")


class FakeSession:
    def __init__(self, status=200, html="<html><body>City</body></html>", error=None):
        self.fetched = []
        self.status = status
        self.html = html
        self.error = error

    def fetch(self, url, wait_for=None):
        self.fetched.append(url)
        return self.status, self.html, self.error


class TestCityInput(unittest.TestCase):
    def test_single_city_matches_clementon_url(self):
        config = mapping.actor_input_to_config({
            "city": "Clementon",
            "state": "NJ",
            "fields": ["population", "crime"],
            "maxCities": 1,
        })
        self.assertEqual(config["cities"], [{"city": "Clementon", "state": "NJ"}])
        self.assertEqual(config["delay_seconds"], 1.5)
        self.assertEqual(config["timeout_ms"], 30000)
        self.assertTrue(config["headless"])
        scraper = mapping._scraper()
        self.assertEqual(
            scraper.build_city_url("Clementon", "NJ"),
            "https://www.city-data.com/city/Clementon-New-Jersey.html",
        )

    def test_max_cities_slices_list(self):
        config = mapping.actor_input_to_config({
            "cities": [
                {"city": "Clementon", "state": "NJ"},
                {"city": "Chicago", "state": "IL"},
            ],
            "fields": ["population"],
            "maxCities": 1,
        })
        self.assertEqual(len(config["cities"]), 1)
        self.assertEqual(config["cities"][0]["city"], "Clementon")

    def test_rejects_unknown_field(self):
        with self.assertRaises(ValueError):
            mapping.actor_input_to_config({
                "city": "Clementon",
                "state": "NJ",
                "fields": ["weather"],
            })


class TestCityDataset(unittest.TestCase):
    def test_allowed_city_is_fetched_and_shaped(self):
        config = mapping.actor_input_to_config({
            "city": "Clementon",
            "state": "NJ",
            "fields": ["population"],
        })
        session = FakeSession()
        robots = "User-agent: *\nDisallow:\n"
        rows = mapping.scrape_config(config, session, robots)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["city"], "Clementon")
        self.assertEqual(row["state"], "NJ")
        self.assertTrue(row["ok"])
        self.assertEqual(row["sourceStatus"], "ok")
        self.assertIn("scrapedAt", row)
        self.assertIn("/city/Clementon-New-Jersey.html", row["urls"]["city"])
        self.assertEqual(session.fetched, [row["urls"]["city"]])
        summary = mapping.summarize(rows)
        self.assertEqual(summary["pushed"], 1)
        self.assertEqual(summary["blocked"], 0)

    def test_disallowed_path_skips_the_request(self):
        config = mapping.actor_input_to_config({
            "city": "Clementon",
            "state": "NJ",
            "fields": ["population", "crime"],
        })
        session = FakeSession()
        robots = "User-agent: *\nDisallow: /city/\nDisallow: /crime/\n"
        rows = mapping.scrape_config(config, session, robots)
        self.assertEqual(session.fetched, [])
        self.assertFalse(rows[0]["ok"])
        self.assertEqual(rows[0]["sourceStatus"], "robots_disallowed")
        self.assertEqual(rows[0]["error"], "robots_disallowed")

    def test_longer_allow_beats_city_disallow(self):
        config = mapping.actor_input_to_config({
            "city": "Clementon",
            "state": "NJ",
            "fields": ["population", "crime"],
        })
        session = FakeSession()
        robots = (
            "User-agent: *\n"
            "Disallow: /city/\n"
            "Allow: /city/Clementon-New-Jersey.html\n"
            "Disallow: /crime/\n"
        )
        rows = mapping.scrape_config(config, session, robots)
        self.assertEqual(len(session.fetched), 1)
        self.assertIn("/city/Clementon-New-Jersey.html", session.fetched[0])
        self.assertNotIn("crime", session.fetched[0])
        self.assertEqual(rows[0]["crime"]["error"], "robots_disallowed")
        self.assertEqual(rows[0]["sourceStatus"], "ok")
