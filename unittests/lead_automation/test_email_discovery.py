"""
Unit tests for scripts/lead_automation/email_discovery.py

Run from repo root:
    python -m unittest unittests.lead_automation.test_email_discovery
"""
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"


def _import_module(name):
    prev = os.getcwd()
    try:
        os.chdir(_LEADGEN_DIR)
        if str(_LEADGEN_DIR) not in sys.path:
            sys.path.insert(0, str(_LEADGEN_DIR))
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        if name in sys.modules:
            return importlib.reload(sys.modules[name])
        return importlib.import_module(name)
    finally:
        os.chdir(prev)


def _get_or_skip(name):
    try:
        return _import_module(name), None
    except Exception as exc:
        return None, exc


DISCOVERY, _IMPORT_ERR = _get_or_skip("email_discovery")
SKIP = unittest.skipIf(
    DISCOVERY is None,
    f"email_discovery import failed: {_IMPORT_ERR!r}",
)


def _lead(**overrides):
    base = {
        "business_name": "Joe's Plumbing",
        "address": "123 Main St, Maple Shade, NJ 08052, USA",
        "phone_google": "(856) 555-1234",
        "phone_website": None,
        "email": "",
        "website": None,
    }
    base.update(overrides)
    return base


@SKIP
class TestExtractEmails(unittest.TestCase):
    def test_plain_text_email(self):
        html = "<html><body>Email us at info@joesplumbing.com today</body></html>"
        self.assertEqual(
            DISCOVERY.extract_emails_from_html(html),
            ["info@joesplumbing.com"],
        )

    def test_mailto_link(self):
        html = '<a href="mailto:Contact@JoesPlumbing.com?subject=Hi">mail</a>'
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(
            DISCOVERY.extract_emails_from_html(html, soup=soup),
            ["contact@joesplumbing.com"],
        )

    def test_multiple_and_duplicate_emails(self):
        html = (
            "info@joesplumbing.com sales@joesplumbing.com "
            "INFO@joesplumbing.com"
        )
        emails = DISCOVERY.extract_emails_from_html(html)
        self.assertEqual(emails, ["info@joesplumbing.com", "sales@joesplumbing.com"])

    def test_malformed_email_like_text_ignored(self):
        html = "reach us at not-an-email@ or owner@@company or photo@site.com.png"
        self.assertEqual(DISCOVERY.extract_emails_from_html(html), [])

    def test_false_positives_filtered(self):
        html = (
            "example@example.com test@test.com email@example.com "
            "yourname@domain.com noreply@joesplumbing.com no-reply@joesplumbing.com "
            "info@joesplumbing.com"
        )
        self.assertEqual(
            DISCOVERY.extract_emails_from_html(html),
            ["info@joesplumbing.com"],
        )

    def test_schema_json_ld_email(self):
        html = """
        <script type="application/ld+json">
        {"@type": "LocalBusiness", "email": "office@joesplumbing.com"}
        </script>
        """
        self.assertIn("office@joesplumbing.com", DISCOVERY.extract_emails_from_html(html))

    def test_validate_email_rejects_junk(self):
        self.assertEqual(DISCOVERY.validate_email("example@example.com"), "")
        self.assertEqual(DISCOVERY.validate_email("noreply@biz.com"), "")
        self.assertEqual(DISCOVERY.validate_email("info@joesplumbing.com"), "info@joesplumbing.com")


@SKIP
class TestQueriesAndConfidence(unittest.TestCase):
    def test_build_google_queries_uses_location(self):
        queries = DISCOVERY.build_google_queries(
            _lead(),
            city="Maple Shade",
            state="NJ",
        )
        self.assertTrue(queries)
        self.assertTrue(any("Maple Shade" in q and "email" in q for q in queries))
        self.assertTrue(any("123 Main St" in q for q in queries))
        self.assertLessEqual(len(queries), DISCOVERY.MAX_GOOGLE_SEARCHES_PER_LEAD)

    def test_high_confidence_domain_match(self):
        confidence = DISCOVERY.score_email_confidence(
            "contact@joesplumbing.com",
            _lead(website="https://joesplumbing.com"),
            page_url="https://joesplumbing.com/contact",
            page_text="Joe's Plumbing Maple Shade NJ contact us",
            website="https://joesplumbing.com",
        )
        self.assertEqual(confidence, DISCOVERY.CONFIDENCE_HIGH)

    def test_gmail_without_corroboration_is_low(self):
        confidence = DISCOVERY.score_email_confidence(
            "abcroofing@gmail.com",
            _lead(business_name="ABC Roofing", website=None, phone_google=None),
            page_url="https://randomblog.com",
            page_text="email us",
        )
        self.assertEqual(confidence, DISCOVERY.CONFIDENCE_LOW)

    def test_gmail_with_name_and_city_is_medium(self):
        confidence = DISCOVERY.score_email_confidence(
            "joe@gmail.com",
            _lead(),
            page_url="https://facebook.com/joesplumbing",
            page_text="Joe's Plumbing serving Maple Shade, NJ. Call (856) 555-1234",
        )
        self.assertEqual(confidence, DISCOVERY.CONFIDENCE_MEDIUM)


@SKIP
class TestGoogleParsingAndBlocks(unittest.TestCase):
    def test_parse_google_results(self):
        html = """
        <div id="search">
          <div class="g">
            <a href="https://joesplumbing.com/">
              <h3>Joe's Plumbing</h3>
            </a>
            <div class="VwiC3b">Official site for Joe's Plumbing in Maple Shade</div>
          </div>
        </div>
        """
        results = DISCOVERY.parse_google_results(html)
        self.assertEqual(results[0]["url"], "https://joesplumbing.com/")
        self.assertIn("Joe's Plumbing", results[0]["title"])

    def test_captcha_page_detected(self):
        self.assertTrue(
            DISCOVERY.is_google_block_page(
                "Our systems have detected unusual traffic from your computer",
                "https://www.google.com/sorry/index",
            )
        )
        self.assertFalse(DISCOVERY.is_google_block_page("<html>results</html>", "https://www.google.com/search"))

    def test_discover_official_website(self):
        results = [
            {"title": "Yelp", "url": "https://www.yelp.com/biz/joes", "snippet": "Joe's"},
            {
                "title": "Joe's Plumbing",
                "url": "https://joesplumbing.com",
                "snippet": "Maple Shade plumber",
            },
        ]
        url = DISCOVERY.discover_business_website(results, _lead())
        self.assertEqual(url, "https://joesplumbing.com")


@SKIP
class TestEnrichmentFlow(unittest.TestCase):
    def test_skips_google_when_email_and_phone_present(self):
        session = DISCOVERY.EmailDiscoverySession(delay=0)
        session.search = MagicMock(return_value=[])
        lead = _lead(email="info@joesplumbing.com")
        DISCOVERY.enrich_lead_with_email(lead, city="Maple Shade", state="NJ", session=session)
        session.search.assert_not_called()
        self.assertEqual(lead["email"], "info@joesplumbing.com")

    def test_cache_skips_repeat_search(self):
        session = DISCOVERY.EmailDiscoverySession(delay=0)
        session.search = MagicMock(return_value=[])
        first = _lead(website=None, email="")
        with patch.object(DISCOVERY, "inspect_website", return_value={"emails": [], "phones": [], "page_text": "", "page_url": "", "error": "x"}):
            DISCOVERY.enrich_lead_with_email(first, city="Maple Shade", state="NJ", session=session)
            first_searches = session.search.call_count
            self.assertGreaterEqual(first_searches, 1)
            second = _lead(website=None, email="")
            DISCOVERY.enrich_lead_with_email(second, city="Maple Shade", state="NJ", session=session)
        self.assertEqual(session.search.call_count, first_searches)

    def test_captcha_does_not_raise(self):
        session = DISCOVERY.EmailDiscoverySession(delay=0)
        session.google_blocked = True
        lead = _lead(email="")
        out = DISCOVERY.enrich_lead_with_email(
            lead, city="Maple Shade", state="NJ", session=session
        )
        self.assertEqual(out.get("email") or "", "")

    def test_accepts_domain_matching_website_email(self):
        session = DISCOVERY.EmailDiscoverySession(delay=0)
        session.search = MagicMock(
            return_value=[{
                "title": "Joe's Plumbing",
                "url": "https://joesplumbing.com/contact",
                "snippet": "Joe's Plumbing Maple Shade",
            }]
        )
        inspected = {
            "emails": ["info@joesplumbing.com"],
            "phones": ["(+1) 856-555-1234"],
            "https": True,
            "has_viewport": True,
            "html_length": 4000,
            "has_cta": True,
            "page_text": "Joe's Plumbing Maple Shade NJ contact",
            "page_url": "https://joesplumbing.com/contact",
            "error": None,
        }
        lead = _lead(website=None, email="")
        with patch.object(DISCOVERY, "inspect_website", return_value=inspected):
            DISCOVERY.enrich_lead_with_email(lead, city="Maple Shade", state="NJ", session=session)
        self.assertEqual(lead["email"], "info@joesplumbing.com")
        self.assertEqual(lead["email_confidence"], DISCOVERY.CONFIDENCE_HIGH)
        self.assertEqual(lead["email_source"], DISCOVERY.SOURCE_GOOGLE)

    def test_rejects_bare_gmail_without_corroboration(self):
        session = DISCOVERY.EmailDiscoverySession(delay=0)
        session.search = MagicMock(
            return_value=[{
                "title": "Random",
                "url": "https://unrelated.com",
                "snippet": "abcroofing@gmail.com",
                "emails": ["abcroofing@gmail.com"],
            }]
        )
        lead = _lead(
            business_name="ABC Roofing",
            address="Philadelphia, PA",
            phone_google=None,
            website=None,
            email="",
        )
        with patch.object(
            DISCOVERY,
            "inspect_website",
            return_value={"emails": [], "phones": [], "page_text": "", "page_url": "", "error": None},
        ):
            DISCOVERY.enrich_lead_with_email(lead, city="Philadelphia", state="PA", session=session)
        self.assertFalse(lead.get("has_email"))


if __name__ == "__main__":
    unittest.main()
