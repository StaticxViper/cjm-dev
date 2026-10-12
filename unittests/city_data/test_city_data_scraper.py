"""
Unit tests for scripts/city_data/city_data_scraper.py

Run from repo root:
    python -m unittest unittests.city_data.test_city_data_scraper
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_DIR = _REPO_ROOT / "scripts" / "city_data"
_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _import_scraper():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    if "city_data_scraper" in sys.modules:
        return importlib.reload(sys.modules["city_data_scraper"])
    return importlib.import_module("city_data_scraper")


def _get_scraper_or_skip():
    previous = os.getcwd()
    try:
        os.chdir(_SCRIPT_DIR)
        if str(_SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPT_DIR))
        return _import_scraper(), None
    except Exception as exc:
        return None, exc
    finally:
        os.chdir(previous)


SCRAPER, _IMPORT_ERR = _get_scraper_or_skip()
SKIP = unittest.skipIf(
    SCRAPER is None,
    f"city_data_scraper import failed (install project deps): {_IMPORT_ERR!r}",
)


def _fixture(name):
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []
        self.closed = False

    def fetch(self, url, wait_for=None):
        self.fetched.append(url)
        status, html, error = self.pages.get(url, (404, "<html>Oops, Page Not Found!</html>", "HTTP 404"))
        return status, html, error

    def close(self):
        self.closed = True


@SKIP
class TestSlugsAndUrls(unittest.TestCase):
    def test_city_slug_from_abbr(self):
        self.assertEqual(
            SCRAPER.city_slug("Cherry Hill", "NJ"),
            "Cherry-Hill-New-Jersey",
        )

    def test_city_slug_from_full_state(self):
        self.assertEqual(
            SCRAPER.city_slug("Chicago", "Illinois"),
            "Chicago-Illinois",
        )

    def test_slug_override(self):
        self.assertEqual(
            SCRAPER.city_slug("Cherry Hill", "NJ", slug="Cherry-Hill-Mall"),
            "Cherry-Hill-Mall",
        )

    def test_district_of_columbia_keeps_small_word(self):
        self.assertEqual(
            SCRAPER.slugify_name("District of Columbia"),
            "District-of-Columbia",
        )

    def test_urls(self):
        self.assertEqual(
            SCRAPER.build_city_url("Clementon", "NJ"),
            "https://www.city-data.com/city/Clementon-New-Jersey.html",
        )
        self.assertEqual(
            SCRAPER.build_crime_url("Clementon", "NJ"),
            "https://www.city-data.com/crime/crime-Clementon-New-Jersey.html",
        )

    def test_unknown_state_rejected(self):
        with self.assertRaises(ValueError):
            SCRAPER.normalize_state("Narnia")


@SKIP
class TestNormalizeConfig(unittest.TestCase):
    def test_accepts_default_config(self):
        result = SCRAPER.normalize_config(dict(SCRAPER.DEFAULT_CONFIG))
        self.assertEqual(result["cities"][0]["city"], "Cherry Hill")
        self.assertEqual(result["cities"][0]["state"], "NJ")
        self.assertIn("crime", result["fields"])

    def test_accepts_city_string(self):
        result = SCRAPER.normalize_config({"cities": ["Chicago,IL"]})
        self.assertEqual(result["cities"], [{"city": "Chicago", "state": "IL"}])

    def test_rejects_empty_cities(self):
        with self.assertRaises(ValueError):
            SCRAPER.normalize_config({"cities": []})

    def test_rejects_unknown_field(self):
        with self.assertRaises(ValueError):
            SCRAPER.normalize_config({
                "cities": [{"city": "Chicago", "state": "IL"}],
                "fields": ["weather"],
            })

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            SCRAPER.normalize_config([{"city": "Chicago", "state": "IL"}])

    def test_parse_city_arg(self):
        self.assertEqual(
            SCRAPER.parse_city_arg("Cherry Hill, NJ"),
            {"city": "Cherry Hill", "state": "NJ"},
        )


@SKIP
class TestCityParsers(unittest.TestCase):
    def test_parses_curated_city_fields(self):
        html = _fixture("city_profile.html")
        parsed = SCRAPER.parse_city_html(html, list(SCRAPER.FIELD_GROUPS))
        self.assertEqual(parsed["population"]["year"], 2024)
        self.assertEqual(parsed["population"]["total"], 5600)
        self.assertEqual(parsed["population"]["urban_pct"], 100.0)
        self.assertEqual(parsed["population"]["change_since_2000_pct"], 12.3)
        self.assertEqual(parsed["population"]["median_age"], 38.1)
        self.assertEqual(parsed["population"]["males"], 2700)
        self.assertEqual(parsed["income"]["median_household"], 65754)
        self.assertEqual(parsed["income"]["per_capita"], 30725)
        self.assertEqual(parsed["income"]["poverty_rate"], 16.8)
        self.assertEqual(parsed["housing"]["median_home_value"], 260711)
        self.assertEqual(parsed["housing"]["median_gross_rent"], 1194)
        self.assertEqual(parsed["housing"]["renter_pct"], 36.0)
        self.assertEqual(parsed["cost_of_living"]["index"], 101.4)
        self.assertEqual(parsed["cost_of_living"]["year"], 2024)
        self.assertEqual(parsed["education"]["hs_or_higher_pct"], 85.2)
        self.assertEqual(parsed["education"]["bachelors_or_higher_pct"], 18.4)

    def test_omits_unrequested_groups(self):
        html = _fixture("city_profile.html")
        parsed = SCRAPER.parse_city_html(html, ["population"])
        self.assertIn("population", parsed)
        self.assertNotIn("income", parsed)


@SKIP
class TestCrimeParsers(unittest.TestCase):
    def test_parses_crime_page(self):
        html = _fixture("crime_profile.html")
        parsed = SCRAPER.parse_crime_html(html)
        self.assertEqual(parsed["index"], 315)
        self.assertEqual(parsed["index_year"], 2025)
        self.assertEqual(parsed["vs_us_average"], "1.4 times higher")
        self.assertEqual(parsed["yoy_change_pct"], -19.0)
        self.assertEqual(parsed["homicides"], 346)
        self.assertEqual(parsed["violent_crime_rate"], 259.7)
        self.assertEqual(parsed["property_crime_rate"], 247.7)
        self.assertEqual(parsed["officers_per_1000"], 4.25)
        self.assertEqual(parsed["by_year"][0]["year"], 2025)
        self.assertEqual(parsed["by_year"][0]["murders"], 346)
        self.assertEqual(parsed["by_year"][0]["thefts"], 40000)
        self.assertEqual(parsed["by_year"][0]["auto_thefts"], 5000)
        self.assertEqual(parsed["by_year"][0]["crime_index"], 315)
        self.assertEqual(parsed["by_year"][1]["year"], 2024)
        self.assertEqual(parsed["by_year"][1]["murders"], 461)
        self.assertNotIn("sex_offenders", parsed)
        self.assertNotIn(4182, parsed.values())

    def test_city_page_fallback_table(self):
        html = _fixture("city_profile.html")
        parsed = SCRAPER.parse_crime_html(html)
        self.assertEqual(parsed["by_year"][0]["year"], 2024)
        self.assertEqual(parsed["by_year"][0]["crime_index"], 120.5)
        self.assertEqual(parsed["index"], 120.5)


@SKIP
class TestLoadAndSave(unittest.TestCase):
    def test_load_config_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(
                json.dumps({"cities": [{"city": "Chicago", "state": "IL"}], "fields": ["population"]}),
                encoding="utf-8",
            )
            result = SCRAPER.load_config(path)
            self.assertEqual(result["cities"], [{"city": "Chicago", "state": "IL"}])
            self.assertEqual(result["fields"], ["population"])

    def test_save_output_is_atomic(self):
        payload = {"scraped_at": "2026-01-01T00:00:00+00:00", "results": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out" / "city_data_output.json"
            SCRAPER.save_output(payload, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)
            self.assertFalse(path.with_name("city_data_output.json.tmp").exists())


@SKIP
class TestResolveConfig(unittest.TestCase):
    def test_cli_overrides_file_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps(SCRAPER.DEFAULT_CONFIG), encoding="utf-8")
            args = SCRAPER.parse_args([
                "--input", str(path),
                "--cities", "Chicago,IL",
                "--fields", "population", "crime",
                "--delay", "2.5",
            ])
            result = SCRAPER.resolve_config(args)
            self.assertEqual(result["cities"], [{"city": "Chicago", "state": "IL"}])
            self.assertEqual(result["fields"], ["population", "crime"])
            self.assertEqual(result["delay_seconds"], 2.5)


@SKIP
class TestScrapeCities(unittest.TestCase):
    def test_writes_profiles_from_session(self):
        city_html = _fixture("city_profile.html")
        crime_html = _fixture("crime_profile.html")
        city_url = SCRAPER.build_city_url("Clementon", "NJ")
        crime_url = SCRAPER.build_crime_url("Clementon", "NJ")
        session = FakeSession({
            city_url: (200, city_html, None),
            crime_url: (200, crime_html, None),
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "city_data_output.json"
            payload = SCRAPER.scrape_cities(
                {"cities": [{"city": "Clementon", "state": "NJ"}]},
                path,
                session=session,
            )
        self.assertTrue(payload["results"][0]["ok"])
        self.assertEqual(payload["results"][0]["population"]["total"], 5600)
        self.assertEqual(payload["results"][0]["crime"]["index"], 315)
        self.assertEqual(session.fetched, [city_url, crime_url])
        self.assertFalse(session.closed)

    def test_crime_404_falls_back_to_city_page(self):
        city_html = _fixture("city_profile.html")
        city_url = SCRAPER.build_city_url("Clementon", "NJ")
        crime_url = SCRAPER.build_crime_url("Clementon", "NJ")
        session = FakeSession({
            city_url: (200, city_html, None),
            crime_url: (404, "<html>Oops, Page Not Found!</html>", "HTTP 404"),
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "city_data_output.json"
            payload = SCRAPER.scrape_cities(
                {"cities": [{"city": "Clementon", "state": "NJ"}]},
                path,
                session=session,
            )
        crime = payload["results"][0]["crime"]
        self.assertEqual(crime["by_year"][0]["crime_index"], 120.5)
        self.assertNotIn("error", crime)

    def test_missing_city_page_sets_error(self):
        session = FakeSession({})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "city_data_output.json"
            payload = SCRAPER.scrape_cities(
                {
                    "cities": [{"city": "Nowhere", "state": "NJ"}],
                    "fields": ["population"],
                },
                path,
                session=session,
            )
        self.assertFalse(payload["results"][0]["ok"])
        self.assertEqual(payload["results"][0]["error"], "City page not found")

    def test_skips_crime_fetch_when_not_requested(self):
        city_html = _fixture("city_profile.html")
        city_url = SCRAPER.build_city_url("Clementon", "NJ")
        session = FakeSession({city_url: (200, city_html, None)})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "city_data_output.json"
            payload = SCRAPER.scrape_cities(
                {
                    "cities": [{"city": "Clementon", "state": "NJ"}],
                    "fields": ["population"],
                },
                path,
                session=session,
            )
        self.assertEqual(session.fetched, [city_url])
        self.assertNotIn("crime", payload["results"][0])


@SKIP
class TestNotFound(unittest.TestCase):
    def test_detects_city_data_404_page(self):
        self.assertTrue(SCRAPER.is_not_found("<html><h1>Oops, Page Not Found!</h1></html>", 200))
        self.assertTrue(SCRAPER.is_not_found("", 404))
        self.assertFalse(SCRAPER.is_not_found("<html><title>Clementon</title></html>", 200))


if __name__ == "__main__":
    unittest.main()
