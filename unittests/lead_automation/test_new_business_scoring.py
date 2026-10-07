"""New-business score: additive, clamped, and explained."""
import sys
import unittest
from datetime import date
from pathlib import Path

_LEADGEN_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lead_automation"
if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))

from new_business_scoring import load_score_rules, score_new_business

TODAY = date(2026, 10, 5)


def _score(row, **overrides):
    rules = load_score_rules()
    rules.update(overrides)
    return score_new_business(row, rules, today=TODAY)


class TestWorkedExamples(unittest.TestCase):
    def test_registered_45_days_no_website_email_phone_category_is_95(self):
        score, reasons, breakdown = _score({
            "registration_date": "2026-08-21",
            "website_status": "no_website",
            "email": "smithlandscapingnj@gmail.com",
            "email_confidence": "medium",
            "phone": "(856) 555-0100",
            "category": "landscaping",
            "business_status": "active",
        })
        self.assertEqual(score, 95)
        self.assertEqual(reasons, [
            "new_business_registered_90d",
            "no_website",
            "business_email_found",
            "local_service_category",
            "public_phone_found",
        ])
        self.assertEqual(sum(breakdown.values()), 95)

    def test_registered_200_days_phone_only_is_70(self):
        score, _reasons, breakdown = _score({
            "formation_date": "2026-03-19",
            "website_status": "no_website",
            "phone": "(856) 555-0100",
            "category": "landscaping",
            "business_status": "active",
        })
        self.assertEqual(score, 70)
        self.assertEqual(breakdown["new_business_registered"], 25)
        self.assertNotIn("business_email_found", breakdown)

    def test_soft_signal_poor_site_is_45(self):
        score, _reasons, breakdown = _score({
            "newness_evidence": [{"type": "grand_opening", "date": None}],
            "website_status": "poor_website",
            "website_issues": ["no_viewport"],
            "website_quality_score": 55,
            "phone": "(856) 555-0100",
            "category": "landscaping",
            "business_status": "active",
        })
        self.assertEqual(score, 45)
        self.assertEqual(breakdown["recently_opened_signal"], 15)
        self.assertEqual(breakdown["poor_website"], 15)


class TestScoreRules(unittest.TestCase):
    def test_unknowns_add_zero(self):
        score, reasons, breakdown = _score({
            "business_name": "Mystery Co",
            "website_status": "unknown",
            "business_status": "active",
        })
        self.assertEqual(score, 0)
        self.assertEqual(reasons, [])
        self.assertEqual(breakdown, {})

    def test_no_website_outranks_broken_and_poor(self):
        none_score, _, _ = _score({"website_status": "no_website", "phone": "(856) 555-0100"})
        broken_score, _, _ = _score({
            "website_status": "poor_website",
            "website_issues": ["placeholder_content"],
            "phone": "(856) 555-0100",
        })
        poor_score, _, _ = _score({
            "website_status": "poor_website",
            "website_issues": ["no_viewport"],
            "website_quality_score": 55,
            "phone": "(856) 555-0100",
        })
        self.assertGreater(none_score, broken_score)
        self.assertGreater(broken_score, poor_score)

    def test_established_and_good_website_penalties(self):
        _score_value, _reasons, breakdown = _score({
            "formation_date": "2020-01-01",
            "website_status": "good_website",
            "website_quality_score": 20,
            "phone": "(856) 555-0100",
            "business_status": "active",
        })
        self.assertEqual(breakdown["established_business"], -25)
        self.assertEqual(breakdown["good_website"], -15)

    def test_score_equals_clamped_breakdown_sum(self):
        row = {
            "registration_date": "2026-08-21",
            "website_status": "no_website",
            "email": "a@b.com",
            "email_confidence": "high",
            "phone": "(856) 555-0100",
            "category": "landscaping",
            "user_ratings_total": 80,
        }
        score, reasons, breakdown = _score(row)
        self.assertEqual(score, max(0, min(100, sum(breakdown.values()))))
        self.assertEqual(reasons, [key for key, _pts in sorted(breakdown.items(), key=lambda item: (-item[1], item[0]))])


if __name__ == "__main__":
    unittest.main()
