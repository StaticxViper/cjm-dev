"""
Unit tests for scripts/lead_automation/leadgen.py

Run from repo root:
    python -m unittest unitetests.lead_automation.test_leadgen
"""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"


def _import_leadgen():
    """Load leadgen; it reads keywords.json / coords.json relative to CWD."""
    _prev = os.getcwd()
    try:
        os.chdir(_LEADGEN_DIR)
        if str(_LEADGEN_DIR) not in sys.path:
            sys.path.insert(0, str(_LEADGEN_DIR))
        return importlib.import_module("leadgen")
    finally:
        os.chdir(_prev)


def _get_leadgen_or_skip():
    try:
        return _import_leadgen(), None
    except Exception as e:
        return None, e


LEADGEN, _LEADGEN_IMPORT_ERR = _get_leadgen_or_skip()
SKIP = unittest.skipIf(
    LEADGEN is None,
    f"leadgen import failed (install project deps, e.g. requirements/requirements.txt): {_LEADGEN_IMPORT_ERR!r}",
)


@SKIP
class TestScoreLead(unittest.TestCase):
    def test_no_website_returns_ten(self):
        self.assertEqual(
            LEADGEN.score_lead(
                has_website=False,
                https=False,
                has_viewport=False,
                html_length=0,
                emails=[],
                has_cta=False,
                rating=5.0,
                user_ratings_total=100,
            ),
            10,
        )

    def test_ideal_lead_zero_score(self):
        self.assertEqual(
            LEADGEN.score_lead(
                has_website=True,
                https=True,
                has_viewport=True,
                html_length=5000,
                emails=["a@b.com"],
                has_cta=True,
                rating=5.0,
                user_ratings_total=20,
            ),
            0,
        )

    def test_adds_for_http_no_viewport_short_html(self):
        score = LEADGEN.score_lead(
            has_website=True,
            https=False,
            has_viewport=False,
            html_length=1000,
            emails=["x@y.com"],
            has_cta=True,
            rating=5.0,
            user_ratings_total=20,
        )
        self.assertEqual(score, 5 + 3 + 3)


@SKIP
class TestGetPlaces(unittest.TestCase):
    @patch("leadgen.time.sleep", return_value=None)
    @patch("leadgen.requests.get")
    def test_get_places_parses_results_and_stops(self, mock_get, _sleep):
        body = {
            "status": "OK",
            "results": [
                {
                    "place_id": "ChIJ1",
                    "name": "Test Biz",
                    "rating": 4.2,
                    "user_ratings_total": 10,
                    "vicinity": "123 Main",
                }
            ],
        }
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = body
        mock_get.return_value = resp

        places = LEADGEN.get_places(
            "39.0,-75.0",
            1000,
            ["landscaping"],
            "fake-key",
        )
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0]["place_id"], "ChIJ1")
        self.assertEqual(places[0]["category"], "landscaping")
        self.assertIn("place_id", places[0])


@SKIP
class TestSaveResults(unittest.TestCase):
    def test_save_results_new_file(self):
        rows = [
            {
                "business_name": "A",
                "address": "1 St",
                "phone_google": "555",
                "phone_website": None,
                "email": "a@a.com",
                "website": "https://a.com",
                "rating": 4.0,
                "user_ratings_total": 10,
                "https": True,
                "has_viewport": True,
                "html_length": 5000,
                "lead_score": 0,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "leads_out.csv")
            LEADGEN.save_results(rows, path)
            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("business_name", content)
            self.assertIn("A", content)


@SKIP
class TestAnalyzeWebsite(unittest.TestCase):
    @patch("leadgen.requests.get")
    def test_empty_url_no_request(self, mock_get):
        out = LEADGEN.analyze_website("")
        self.assertEqual(out["emails"], [])
        mock_get.assert_not_called()

    @patch("leadgen.requests.get")
    def test_parses_email_and_cta(self, mock_get):
        html = b"""<!doctype html><html><head><title>T</title>
        <meta name="viewport" content="width=device-width">
        </head><body>Contact us at support@example.com for a quote.
        </body></html>"""
        resp = MagicMock()
        resp.text = html.decode("utf-8")
        mock_get.return_value = resp

        out = LEADGEN.analyze_website("https://example.com")
        self.assertIn("support@example.com", out["emails"])
        self.assertTrue(out["has_cta"])


if __name__ == "__main__":
    unittest.main()
