"""website_status classification for new-business leads."""
import os
import sys
import unittest
from datetime import date
from pathlib import Path

_LEADGEN_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lead_automation"
if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))

from new_business_website import classify_website

TODAY = date(2026, 10, 5)


class TestWebsiteStatus(unittest.TestCase):
    def test_missing_url_is_unknown_until_search_runs(self):
        before = classify_website(url="", search_ran=False, check_mode="deep", today=TODAY)
        self.assertEqual(before["website_status"], "unknown")
        after = classify_website(url="", search_ran=True, check_mode="deep", today=TODAY)
        self.assertEqual(after["website_status"], "no_website")
        self.assertEqual(after["website_quality_score"], 100)

    def test_social_only(self):
        result = classify_website(
            url="https://www.facebook.com/example",
            search_ran=True,
            check_mode="deep",
            today=TODAY,
        )
        self.assertEqual(result["website_status"], "no_website")
        self.assertIn("social_only", result["website_issues"])

    def test_placeholder_is_poor(self):
        html = "<html><body>lorem ipsum coming soon</body></html>"
        cheap = {
            "url": "https://example.com",
            "website_status": "ok",
            "reachable": True,
            "no_website": False,
            "website_broken": False,
            "_html": html,
        }
        result = classify_website(
            url="https://example.com",
            search_ran=True,
            check_mode="deep",
            cheap=cheap,
            html=html,
            today=TODAY,
        )
        self.assertEqual(result["website_status"], "poor_website")
        self.assertIn("placeholder_content", result["website_issues"])
        self.assertEqual(result["website_quality_score"], 90)

    def test_outdated_copyright(self):
        html = (
            "<html><head><title>Shop</title>"
            "<meta name='viewport' content='width=device-width'></head>"
            "<body>Call us for a quote. © 2020 Smith Landscaping "
            "<a href='tel:2155550100'>(215) 555-0100</a>"
            "<form action='/contact'><input name='email'></form></body></html>"
        )
        cheap = {
            "url": "https://example.com",
            "website_status": "ok",
            "reachable": True,
            "https": True,
            "no_website": False,
            "website_broken": False,
            "_html": html,
            "_headers": {},
            "_final_url": "https://example.com",
        }
        result = classify_website(
            url="https://example.com",
            search_ran=True,
            check_mode="deep",
            cheap=cheap,
            html=html,
            today=TODAY,
        )
        self.assertIn("outdated_copyright", result["website_issues"])

    def test_domain_or_hosting_error(self):
        cheap = {
            "url": "https://expired.example",
            "website_status": "error",
            "error": "getaddrinfo failed: Name or service not known",
            "website_broken": True,
            "no_website": False,
        }
        result = classify_website(
            url="https://expired.example",
            search_ran=True,
            check_mode="deep",
            cheap=cheap,
            today=TODAY,
        )
        self.assertEqual(result["website_status"], "poor_website")
        self.assertIn("domain_or_hosting_error", result["website_issues"])

    def test_check_mode_none_is_unknown(self):
        result = classify_website(
            url="https://example.com",
            search_ran=True,
            check_mode="none",
            today=TODAY,
        )
        self.assertEqual(result["website_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
