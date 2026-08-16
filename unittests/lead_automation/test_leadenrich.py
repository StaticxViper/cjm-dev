"""
Unit tests for scripts/lead_automation/leadenrich.py

Run from repo root:
    python -m unittest unittests.lead_automation.test_leadenrich
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"


def _import_leadenrich():
    """Load leadenrich; it imports leadgen, which reads its JSON config files."""
    _prev = os.getcwd()
    try:
        os.chdir(_LEADGEN_DIR)
        if str(_LEADGEN_DIR) not in sys.path:
            sys.path.insert(0, str(_LEADGEN_DIR))
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        if "leadenrich" in sys.modules:
            return importlib.reload(sys.modules["leadenrich"])
        return importlib.import_module("leadenrich")
    finally:
        os.chdir(_prev)


def _get_leadenrich_or_skip():
    try:
        return _import_leadenrich(), None
    except Exception as e:
        return None, e


LEADENRICH, _IMPORT_ERR = _get_leadenrich_or_skip()
SKIP = unittest.skipIf(
    LEADENRICH is None,
    f"leadenrich import failed (install project deps, e.g. requirements/requirements.txt): {_IMPORT_ERR!r}",
)


def _lead(**overrides):
    base = {
        "business_name": "Tomicic's Pressure Washing",
        "place_id": "pid1",
        "address": "450 N Brand Blvd, Glendale, CA 91203, USA",
        "phone_google": "(818) 396-3380",
        "email": "",
        "has_email": False,
        "website": "http://www.tpwandsweeping.com/",
        "lead_score": 87,
        "niche_key": "pressure washing",
    }
    base.update(overrides)
    return base


@SKIP
class TestNormalizeFacebookUrl(unittest.TestCase):
    def test_canonicalizes_vanity_url(self):
        self.assertEqual(
            LEADENRICH.normalize_facebook_url("https://m.facebook.com/CopperKettle/?ref=page_internal"),
            "https://www.facebook.com/CopperKettle",
        )

    def test_accepts_bare_host(self):
        self.assertEqual(
            LEADENRICH.normalize_facebook_url("facebook.com/CopperKettle"),
            "https://www.facebook.com/CopperKettle",
        )

    def test_keeps_numeric_profile_id(self):
        self.assertEqual(
            LEADENRICH.normalize_facebook_url("https://www.facebook.com/profile.php?id=61550123456789"),
            "https://www.facebook.com/profile.php?id=61550123456789",
        )

    def test_keeps_legacy_pages_path(self):
        self.assertEqual(
            LEADENRICH.normalize_facebook_url("https://www.facebook.com/pages/Joes-Plumbing/123456"),
            "https://www.facebook.com/pages/Joes-Plumbing/123456",
        )

    def test_unwraps_pg_prefix(self):
        self.assertEqual(
            LEADENRICH.normalize_facebook_url("https://www.facebook.com/pg/CopperKettle/about"),
            "https://www.facebook.com/CopperKettle",
        )

    def test_rejects_non_page_urls(self):
        self.assertIsNone(LEADENRICH.normalize_facebook_url("https://www.facebook.com/groups/123"))
        self.assertIsNone(LEADENRICH.normalize_facebook_url("https://www.facebook.com/"))
        self.assertIsNone(LEADENRICH.normalize_facebook_url("https://www.facebook.com/profile.php?id=abc"))

    def test_rejects_other_hosts_and_blanks(self):
        self.assertIsNone(LEADENRICH.normalize_facebook_url("https://www.tpwandsweeping.com/"))
        self.assertIsNone(LEADENRICH.normalize_facebook_url(""))
        self.assertIsNone(LEADENRICH.normalize_facebook_url(None))


@SKIP
class TestNameMatching(unittest.TestCase):
    def test_normalize_strips_legal_suffix_and_punctuation(self):
        self.assertEqual(
            LEADENRICH.normalize_business_name("Joe's Plumbing & Heating, LLC"),
            "joes plumbing heating",
        )

    def test_normalize_matches_curly_and_straight_apostrophes(self):
        self.assertEqual(
            LEADENRICH.normalize_business_name("Tomicic\u2019s Pressure Washing"),
            LEADENRICH.normalize_business_name("Tomicic's Pressure Washing"),
        )

    def test_identical_names_score_one(self):
        left = LEADENRICH.normalize_business_name("Alspach Landscaping")
        right = LEADENRICH.normalize_business_name("Alspach Landscaping LLC")
        self.assertEqual(LEADENRICH.name_similarity(left, right), 1.0)

    def test_page_name_with_extra_location_still_matches(self):
        left = LEADENRICH.normalize_business_name("Joe's Plumbing")
        right = LEADENRICH.normalize_business_name("Joes Plumbing - Cherry Hill NJ")
        self.assertGreaterEqual(LEADENRICH.name_similarity(left, right), 0.72)

    def test_unrelated_names_score_low(self):
        left = LEADENRICH.normalize_business_name("Alspach Landscaping")
        right = LEADENRICH.normalize_business_name("Dover Auto Body")
        self.assertLess(LEADENRICH.name_similarity(left, right), 0.72)

    def test_single_generic_token_does_not_get_containment_credit(self):
        left = LEADENRICH.normalize_business_name("Plumbing")
        right = LEADENRICH.normalize_business_name("Ace Plumbing Pros")
        self.assertLess(LEADENRICH.name_similarity(left, right), 0.72)

    def test_best_page_match_picks_closest_above_threshold(self):
        results = [
            {"name": "Cherry Hill Plumbing Supply", "url": "https://www.facebook.com/chplumbingsupply"},
            {"name": "Alspach Landscaping", "url": "https://www.facebook.com/alspachlandscaping"},
        ]
        url, score, name = LEADENRICH.best_page_match("Alspach Landscaping LLC", results, 0.72)
        self.assertEqual(url, "https://www.facebook.com/alspachlandscaping")
        self.assertEqual(name, "Alspach Landscaping")
        self.assertGreaterEqual(score, 0.72)

    def test_best_page_match_rejects_below_threshold(self):
        results = [{"title": "Dover Auto Body", "pageUrl": "https://www.facebook.com/doverautobody"}]
        url, score, _ = LEADENRICH.best_page_match("Alspach Landscaping", results, 0.72)
        self.assertIsNone(url)
        self.assertLess(score, 0.72)

    def test_best_page_match_skips_non_page_results(self):
        results = [{"name": "Alspach Landscaping", "url": "https://www.facebook.com/groups/123"}]
        url, _, _ = LEADENRICH.best_page_match("Alspach Landscaping", results, 0.72)
        self.assertIsNone(url)

    def test_best_page_match_handles_empty_results(self):
        self.assertEqual(LEADENRICH.best_page_match("Anything", [], 0.72), (None, 0.0, None))


@SKIP
class TestLocationHint(unittest.TestCase):
    def test_parses_city_and_country(self):
        self.assertEqual(
            LEADENRICH.location_hint("450 N Brand Blvd #600, Glendale, CA 91203, USA"),
            "Glendale, United States",
        )

    def test_returns_none_for_partial_address(self):
        self.assertIsNone(LEADENRICH.location_hint("Cherry Hill, NJ"))
        self.assertIsNone(LEADENRICH.location_hint(None))


@SKIP
class TestEmailExtraction(unittest.TestCase):
    def test_clean_emails_filters_junk(self):
        emails = LEADENRICH.clean_emails([
            "Contact: Owner@Example.ORG.",
            "page@facebook.com",
            "logo@2x.png",
            "Owner@example.org",
        ])
        self.assertEqual(emails, ["owner@example.org"])

    def test_extract_page_email_prefers_email_field(self):
        page = {"email": "hello@biz.example", "intro": "write to other@biz.example"}
        self.assertEqual(LEADENRICH.extract_page_email(page), "hello@biz.example")

    def test_extract_page_email_falls_back_to_about_and_info(self):
        page = {
            "info": ["Pressure washing in Glendale"],
            "about_me": {"text": "Estimates: quotes@biz.example", "urls": []},
        }
        self.assertEqual(LEADENRICH.extract_page_email(page), "quotes@biz.example")

    def test_extract_page_email_without_email(self):
        self.assertIsNone(LEADENRICH.extract_page_email({"info": ["No contact here"]}))
        self.assertIsNone(LEADENRICH.extract_page_email(None))


@SKIP
class TestCandidateSelection(unittest.TestCase):
    def test_lead_with_email_is_skipped(self):
        self.assertFalse(LEADENRICH.needs_enrichment(_lead(email="a@b.com", has_email=True)))

    def test_unchecked_lead_is_selected(self):
        self.assertTrue(LEADENRICH.needs_enrichment(_lead()))

    def test_previously_checked_lead_is_skipped(self):
        lead = _lead(enrichment={"source": "facebook", "status": LEADENRICH.STATUS_NO_EMAIL})
        self.assertFalse(LEADENRICH.needs_enrichment(lead))

    def test_failed_scrape_is_retried(self):
        lead = _lead(enrichment={"source": "facebook", "status": LEADENRICH.STATUS_SCRAPE_FAILED})
        self.assertTrue(LEADENRICH.needs_enrichment(lead))

    def test_retry_all_reselects_checked_lead(self):
        lead = _lead(enrichment={"source": "facebook", "status": LEADENRICH.STATUS_NO_PAGE})
        self.assertTrue(LEADENRICH.needs_enrichment(lead, retry_all=True))


@SKIP
class TestApplyEnrichment(unittest.TestCase):
    def test_email_is_written_to_lead(self):
        lead = _lead()
        status = LEADENRICH.apply_enrichment(
            lead,
            "https://www.facebook.com/biz",
            {"email": "hello@biz.example"},
            "search",
        )
        self.assertEqual(status, LEADENRICH.STATUS_ENRICHED)
        self.assertEqual(lead["email"], "hello@biz.example")
        self.assertTrue(lead["has_email"])
        self.assertEqual(lead["facebook_url"], "https://www.facebook.com/biz")
        self.assertEqual(lead["enrichment"]["url_source"], "search")

    def test_page_without_email_is_recorded(self):
        lead = _lead()
        status = LEADENRICH.apply_enrichment(lead, "https://www.facebook.com/biz", {}, "website")
        self.assertEqual(status, LEADENRICH.STATUS_NO_EMAIL)
        self.assertEqual(lead["email"], "")
        self.assertFalse(lead["has_email"])
        self.assertEqual(lead["facebook_url"], "https://www.facebook.com/biz")

    def test_unresolved_page_is_recorded(self):
        lead = _lead()
        status = LEADENRICH.apply_enrichment(lead, None, None, None)
        self.assertEqual(status, LEADENRICH.STATUS_NO_PAGE)
        self.assertNotIn("facebook_url", lead)

    def test_missing_page_result_is_retryable(self):
        lead = _lead()
        status = LEADENRICH.apply_enrichment(lead, "https://www.facebook.com/biz", None, "search")
        self.assertEqual(status, LEADENRICH.STATUS_SCRAPE_FAILED)
        self.assertIn(status, LEADENRICH.RETRYABLE_STATUSES)


@SKIP
class TestResolvePageUrls(unittest.TestCase):
    def test_facebook_website_skips_search(self):
        leads = [_lead(website="https://www.facebook.com/tpwandsweeping")]
        with patch.object(LEADENRICH, "search_facebook_page") as mock_search:
            resolved = LEADENRICH.resolve_page_urls(leads, LEADENRICH.EnrichConfig())
        self.assertEqual(resolved[0], ("https://www.facebook.com/tpwandsweeping", "website"))
        mock_search.assert_not_called()

    def test_search_used_for_non_facebook_website(self):
        leads = [_lead(business_name="Alspach Landscaping")]
        results = [{"name": "Alspach Landscaping", "url": "https://www.facebook.com/alspachlandscaping"}]
        with patch.object(LEADENRICH, "search_facebook_page", return_value=results) as mock_search:
            resolved = LEADENRICH.resolve_page_urls(leads, LEADENRICH.EnrichConfig(max_workers=1))
        self.assertEqual(resolved[0], ("https://www.facebook.com/alspachlandscaping", "search"))
        mock_search.assert_called_once()

    def test_unmatched_lead_is_left_unresolved(self):
        leads = [_lead(business_name="Alspach Landscaping")]
        results = [{"name": "Totally Different Co", "url": "https://www.facebook.com/different"}]
        with patch.object(LEADENRICH, "search_facebook_page", return_value=results):
            resolved = LEADENRICH.resolve_page_urls(leads, LEADENRICH.EnrichConfig(max_workers=1))
        self.assertEqual(resolved, {})


@SKIP
class TestScrapeFacebookPages(unittest.TestCase):
    def test_pages_indexed_by_every_url_variant(self):
        item = {
            "facebookUrl": "https://www.facebook.com/requested",
            "pageUrl": "https://www.facebook.com/canonical",
            "pageName": "canonical",
            "email": "hello@biz.example",
        }
        with patch.object(LEADENRICH, "APIManager") as mock_api_cls:
            mock_api_cls.return_value.run_apify.return_value = [item]
            pages = LEADENRICH.scrape_facebook_pages(["https://www.facebook.com/requested"])
        self.assertIs(pages["https://www.facebook.com/requested"], item)
        self.assertIs(pages["https://www.facebook.com/canonical"], item)

    def test_batches_requests(self):
        urls = [f"https://www.facebook.com/page{i}" for i in range(5)]
        with patch.object(LEADENRICH, "APIManager") as mock_api_cls:
            mock_api_cls.return_value.run_apify.return_value = []
            LEADENRICH.scrape_facebook_pages(urls, batch_size=2)
        self.assertEqual(mock_api_cls.return_value.run_apify.call_count, 3)

    def test_actor_failure_does_not_raise(self):
        with patch.object(LEADENRICH, "APIManager") as mock_api_cls:
            mock_api_cls.return_value.run_apify.side_effect = RuntimeError("boom")
            self.assertEqual(LEADENRICH.scrape_facebook_pages(["https://www.facebook.com/x"]), {})


@SKIP
class TestRunEnrichment(unittest.TestCase):
    def _write_leads(self, tmp, leads):
        path = os.path.join(tmp, "leads_output.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(leads, f)
        return path

    def test_end_to_end_updates_only_email_less_leads(self):
        leads = [
            _lead(place_id="pid1", business_name="Alspach Landscaping"),
            _lead(place_id="pid2", email="known@biz.example", has_email=True),
        ]
        search_results = [{"name": "Alspach Landscaping", "url": "https://www.facebook.com/alspachlandscaping"}]
        pages = {
            "https://www.facebook.com/alspachlandscaping": {"email": "office@alspach.example"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_leads(tmp, leads)
            with patch.object(LEADENRICH, "APIFY_API_KEY", "fake-key"), \
                    patch.object(LEADENRICH, "search_facebook_page", return_value=search_results), \
                    patch.object(LEADENRICH, "scrape_facebook_pages", return_value=pages), \
                    patch("leadgen.send_to_dashboard") as mock_dashboard:
                LEADENRICH.run_enrichment(LEADENRICH.EnrichConfig(json_path=path, max_workers=1))
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)

        self.assertEqual(saved[0]["email"], "office@alspach.example")
        self.assertTrue(saved[0]["has_email"])
        self.assertEqual(saved[0]["enrichment"]["status"], LEADENRICH.STATUS_ENRICHED)
        self.assertEqual(saved[1]["email"], "known@biz.example")
        self.assertNotIn("enrichment", saved[1])
        mock_dashboard.assert_not_called()

    def test_limit_caps_candidates(self):
        leads = [_lead(place_id=f"pid{i}") for i in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_leads(tmp, leads)
            with patch.object(LEADENRICH, "APIFY_API_KEY", "fake-key"), \
                    patch.object(LEADENRICH, "search_facebook_page", return_value=[]) as mock_search, \
                    patch.object(LEADENRICH, "scrape_facebook_pages", return_value={}):
                LEADENRICH.run_enrichment(
                    LEADENRICH.EnrichConfig(json_path=path, limit=1, max_workers=1)
                )
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)

        self.assertEqual(mock_search.call_count, 1)
        self.assertEqual(saved[0]["enrichment"]["status"], LEADENRICH.STATUS_NO_PAGE)
        self.assertNotIn("enrichment", saved[1])

    def test_dry_run_skips_scrape_and_write(self):
        leads = [_lead(website="https://www.facebook.com/biz")]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_leads(tmp, leads)
            with patch.object(LEADENRICH, "APIFY_API_KEY", "fake-key"), \
                    patch.object(LEADENRICH, "scrape_facebook_pages") as mock_scrape:
                LEADENRICH.run_enrichment(
                    LEADENRICH.EnrichConfig(json_path=path, dry_run=True, max_workers=1)
                )
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)

        mock_scrape.assert_not_called()
        self.assertNotIn("enrichment", saved[0])

    def test_dashboard_receives_only_enriched_leads(self):
        leads = [
            _lead(place_id="pid1", website="https://www.facebook.com/found"),
            _lead(place_id="pid2", website="https://www.facebook.com/empty"),
        ]
        pages = {"https://www.facebook.com/found": {"email": "office@biz.example"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_leads(tmp, leads)
            with patch.object(LEADENRICH, "APIFY_API_KEY", "fake-key"), \
                    patch.dict(os.environ, {"LEAD_INGEST_KEY": "fake-key"}), \
                    patch.object(LEADENRICH, "scrape_facebook_pages", return_value=pages), \
                    patch("leadgen.send_to_dashboard") as mock_dashboard:
                LEADENRICH.run_enrichment(
                    LEADENRICH.EnrichConfig(json_path=path, dashboard=True, max_workers=1)
                )

        mock_dashboard.assert_called_once()
        sent = mock_dashboard.call_args.args[0]
        self.assertEqual([row["place_id"] for row in sent], ["pid1"])

    def test_missing_api_key_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_leads(tmp, [_lead()])
            with patch.object(LEADENRICH, "APIFY_API_KEY", None), \
                    patch.object(LEADENRICH, "load_leads") as mock_load:
                LEADENRICH.run_enrichment(LEADENRICH.EnrichConfig(json_path=path))
        mock_load.assert_not_called()


@SKIP
class TestSaveLeads(unittest.TestCase):
    def test_save_is_atomic_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "leads_output.json")
            LEADENRICH.save_leads([_lead()], path)
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(len(saved), 1)
            self.assertEqual(os.listdir(tmp), ["leads_output.json"])

    def test_load_leads_rejects_non_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "leads_output.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"leads": []}, f)
            self.assertEqual(LEADENRICH.load_leads(path), [])

    def test_load_leads_missing_file(self):
        self.assertEqual(LEADENRICH.load_leads("does_not_exist.json"), [])


if __name__ == "__main__":
    unittest.main()
