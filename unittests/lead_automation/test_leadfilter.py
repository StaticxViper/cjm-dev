"""
Unit tests for scripts/lead_automation/leadfilter.py
"""
import importlib
import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEAD_DIR = _REPO_ROOT / "scripts" / "lead_automation"


def _import_leadfilter():
    if str(_LEAD_DIR) not in sys.path:
        sys.path.insert(0, str(_LEAD_DIR))
    return importlib.import_module("leadfilter")


LF = _import_leadfilter()


class TestNormalize(unittest.TestCase):
    def test_normalize_email_lowercase(self):
        self.assertEqual(LF.normalize_email("Foo@Bar.COM"), "foo@bar.com")

    def test_normalize_email_skips_junk(self):
        self.assertIsNone(LF.normalize_email("noreply@sentry.io"))

    def test_extract_real_email_from_list(self):
        self.assertEqual(
            LF.extract_real_email("junk@sentry.io;real@biz.com"),
            "real@biz.com",
        )

    def test_normalize_phone_ten_digits(self):
        self.assertEqual(LF.normalize_phone("(555) 123-4567"), "5551234567")

    def test_normalize_phone_strips_country_code(self):
        self.assertEqual(LF.normalize_phone("+1 555-123-4567"), "5551234567")


class TestFilterByScore(unittest.TestCase):
    def test_keeps_at_or_above_threshold(self):
        rows = [
            {"lead_score": "59"},
            {"lead_score": "60"},
            {"lead_score": "70"},
        ]
        out = LF.filter_by_score(rows, threshold=60)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["lead_score"], "60")


class TestDedupeAgainstExisting(unittest.TestCase):
    def test_skips_matching_email(self):
        existing = [{"email": "a@biz.com", "phone": "5551112222"}]
        csv_rows = [{"email": "a@biz.com", "phone_google": "5559998888"}]
        new_rows, skipped = LF.dedupe_against_existing(csv_rows, existing)
        self.assertEqual(new_rows, [])
        self.assertEqual(skipped, 1)

    def test_skips_matching_phone_when_no_email(self):
        existing = [{"email": "", "phone": "5551234567"}]
        csv_rows = [{"email": "", "phone_google": "(555) 123-4567"}]
        new_rows, skipped = LF.dedupe_against_existing(csv_rows, existing)
        self.assertEqual(new_rows, [])
        self.assertEqual(skipped, 1)

    def test_keeps_new_contact(self):
        existing = [{"email": "old@biz.com", "phone": "5551112222"}]
        csv_rows = [{"email": "new@biz.com", "phone_google": "5559998888"}]
        new_rows, skipped = LF.dedupe_against_existing(csv_rows, existing)
        self.assertEqual(len(new_rows), 1)
        self.assertEqual(skipped, 0)


class TestMatchLeadsToCsv(unittest.TestCase):
    def test_email_match_preferred(self):
        existing = [
            {"id": "1", "email": "match@biz.com", "phone": "5551112222", "pipeline": "x", "position": 1}
        ]
        csv_rows = [
            {"email": "match@biz.com", "business_name": "Updated Name", "lead_score": "65"}
        ]
        matched, unmatched = LF.match_leads_to_csv(existing, csv_rows)
        self.assertEqual(unmatched, 0)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["business_name"], "Updated Name")
        self.assertNotIn("pipeline", matched[0])
        self.assertNotIn("position", matched[0])

    def test_phone_match_when_email_missing(self):
        existing = [{"id": "2", "email": "", "phone": "5551234567"}]
        csv_rows = [{"email": "", "phone_google": "555-123-4567", "business_name": "Phone Match"}]
        matched, unmatched = LF.match_leads_to_csv(existing, csv_rows)
        self.assertEqual(unmatched, 0)
        self.assertEqual(matched[0]["business_name"], "Phone Match")

    def test_unmatched_count(self):
        existing = [{"id": "3", "email": "orphan@biz.com", "phone": "5550000001"}]
        csv_rows = [{"email": "other@biz.com", "phone_google": "5550000002"}]
        matched, unmatched = LF.match_leads_to_csv(existing, csv_rows)
        self.assertEqual(matched, [])
        self.assertEqual(unmatched, 1)


if __name__ == "__main__":
    unittest.main()
