"""
Unit tests for scripts/lead_automation/crm_enrich_robots.py

Run from repo root:
    python -m unittest unittests.lead_automation.test_crm_enrich_robots
"""
import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "crm_enrich" / "google_robots.txt"

if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.chdir(_LEADGEN_DIR)

from crm_enrich_robots import (  # noqa: E402
    ACCESS_ROBOTS,
    apply_robots_gate,
    robots_allowed,
)


class TestLongestMatch(unittest.TestCase):
    def setUp(self):
        self.robots = _FIXTURE.read_text(encoding="utf-8")

    def test_maps_allowed_and_search_disallowed(self):
        self.assertTrue(robots_allowed(self.robots, "https://www.google.com/maps/search/x"))
        self.assertTrue(robots_allowed(self.robots, "https://www.google.com/maps/place/x"))
        self.assertFalse(robots_allowed(self.robots, "https://www.google.com/search?q=x"))
        self.assertFalse(robots_allowed(self.robots, "https://www.google.com/maps/dir/"))

    def test_disallowed_source_is_disabled(self):
        blocked = self.robots.replace("Allow: /maps/search/", "Disallow: /maps/search/")
        blocked = blocked.replace("Allow: /maps/place/", "Disallow: /maps/place/")
        enabled, status = apply_robots_gate(blocked, ["maps_playwright", "website"])
        self.assertNotIn("maps_playwright", enabled)
        self.assertEqual(status["maps_playwright"], ACCESS_ROBOTS)
        self.assertEqual(status["google_web_search"], ACCESS_ROBOTS)
        self.assertIn("website", enabled)

    def test_real_excerpt_keeps_maps(self):
        enabled, status = apply_robots_gate(self.robots, ["maps_playwright", "website"])
        self.assertIn("maps_playwright", enabled)
        self.assertEqual(status["maps_playwright"], "ok")
        self.assertEqual(status["google_web_search"], ACCESS_ROBOTS)


if __name__ == "__main__":
    unittest.main()
