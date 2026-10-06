"""Email enrichment order, confidence, and cache for new-business leads."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_LEADGEN_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lead_automation"
if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))

from email_discovery import NEW_BUSINESS_EMAIL_TEMPLATES, EmailDiscoverySession, build_google_queries
from new_business_email import enrich_new_business_lead


class _FakeSession:
    def __init__(self):
        self.searches = []
        self.google_blocked = False
        self.cache = {}
        self.persistent = {}
        self.results = []

    def search(self, query):
        self.searches.append(query)
        return list(self.results)

    def persistent_result(self, lead, city=None, state=None):
        return None

    def remember_result(self, lead, city=None, state=None):
        self.cache["saved"] = dict(lead)
        return lead


class TestEmailEnrichment(unittest.TestCase):
    def test_source_record_email_is_used_first(self):
        session = _FakeSession()
        session.results = [{
            "url": "https://example.com",
            "snippet": "other@example.com",
            "emails": ["other@example.net"],
            "title": "Smith",
        }]
        lead = {
            "business_name": "Smith Landscaping LLC",
            "city": "Cinnaminson",
            "state": "NJ",
            "phone": "(856) 555-0100",
            "phone_google": "(856) 555-0100",
            "address": "123 Example Rd, Cinnaminson, NJ 08077",
            "email": "smithlandscapingnj@gmail.com",
            "source_record_url": "https://example.gov/records/EXAMPLE123",
            "website": "https://smithlandscaping.example",
        }
        enrich_new_business_lead(lead, session=session, inspect_fn=lambda url: {"emails": ["site@smithlandscaping.example"]})
        self.assertEqual(lead["email"], "smithlandscapingnj@gmail.com")
        self.assertEqual(lead["email_source"], "source_record")
        self.assertEqual(lead["email_source_url"], "https://example.gov/records/EXAMPLE123")
        self.assertIn(lead["email_confidence"], ("high", "medium"))
        self.assertEqual(session.searches, [])

    def test_google_fallback_only_when_no_email(self):
        session = _FakeSession()
        session.results = [{
            "url": "https://example.com/contact",
            "title": "Smith Landscaping Cinnaminson NJ",
            "snippet": "Contact Smith Landscaping in Cinnaminson NJ at smithlandscapingnj@gmail.com (856) 555-0100",
            "emails": ["smithlandscapingnj@gmail.com"],
        }]
        lead = {
            "business_name": "Smith Landscaping LLC",
            "city": "Cinnaminson",
            "state": "NJ",
            "phone": "(856) 555-0100",
            "phone_google": "(856) 555-0100",
            "address": "123 Example Rd, Cinnaminson, NJ 08077",
        }
        enrich_new_business_lead(
            lead,
            session=session,
            inspect_fn=lambda url: {"emails": [], "page_text": "", "page_url": url},
        )
        self.assertTrue(session.searches)
        self.assertEqual(lead["email"], "smithlandscapingnj@gmail.com")
        self.assertEqual(lead["email_source"], "google_result")
        self.assertTrue(lead["email_source_url"])

    def test_guessed_emails_are_not_produced(self):
        session = _FakeSession()
        lead = {
            "business_name": "Smith Landscaping LLC",
            "website": "https://smithlandscaping.example",
            "city": "Cinnaminson",
            "state": "NJ",
        }
        enrich_new_business_lead(
            lead,
            session=session,
            inspect_fn=lambda url: {"emails": [], "page_text": "Welcome", "page_url": url},
        )
        self.assertFalse(lead.get("email"))
        self.assertNotIn("info@smithlandscaping.example", str(lead))

    def test_low_confidence_email_rejected(self):
        session = _FakeSession()
        lead = {
            "business_name": "Smith Landscaping LLC",
            "email": "randomperson@gmail.com",
            "source_record_url": "https://example.gov/records/1",
        }
        enrich_new_business_lead(lead, session=session, allow_google=False)
        self.assertFalse(lead.get("email"))

    def test_templates_are_priority_capped(self):
        queries = build_google_queries(
            {"business_name": "Smith Landscaping", "phone": "(856) 555-0100"},
            city="Cinnaminson",
            state="NJ",
            templates=NEW_BUSINESS_EMAIL_TEMPLATES,
        )
        self.assertLessEqual(len(queries), 5)
        self.assertIn("email", queries[0])
        self.assertIn("Smith Landscaping", queries[0])

    def test_enrichment_cache_skips_second_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            session = EmailDiscoverySession(cache_path=str(path), ttl_days=30)
            lead = {
                "lead_id": "reg:NJ:EXAMPLE123",
                "business_name": "Smith Landscaping LLC",
                "city": "Cinnaminson",
                "state": "NJ",
                "email": "smithlandscapingnj@gmail.com",
                "email_confidence": "medium",
                "email_source": "source_record",
                "email_source_url": "https://example.gov/records/EXAMPLE123",
            }
            session.remember_result(lead, city="Cinnaminson", state="NJ")
            session.close()
            again = EmailDiscoverySession(cache_path=str(path), ttl_days=30)
            calls = []

            class Counting(_FakeSession):
                def search(self, query):
                    calls.append(query)
                    return []

                def persistent_result(self, lead, city=None, state=None):
                    return again.persistent_result(lead, city, state)

                def remember_result(self, lead, city=None, state=None):
                    return lead

            fresh = {
                "lead_id": "reg:NJ:EXAMPLE123",
                "business_name": "Smith Landscaping LLC",
                "city": "Cinnaminson",
                "state": "NJ",
            }
            enrich_new_business_lead(fresh, session=Counting(), allow_google=True)
            self.assertEqual(fresh["email"], "smithlandscapingnj@gmail.com")
            self.assertEqual(calls, [])
            again.close()


if __name__ == "__main__":
    unittest.main()
