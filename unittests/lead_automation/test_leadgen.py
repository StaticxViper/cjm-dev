"""
Unit tests for scripts/lead_automation/leadgen.py

Run from repo root:
    python -m unittest unittests.lead_automation.test_leadgen
"""
import importlib
import json
import os
import sys
import tempfile
import time
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
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        if "leadgen" in sys.modules:
            return importlib.reload(sys.modules["leadgen"])
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


def _quality_entry(**overrides):
    base = {
        "business_name": "Local Plumbing LLC",
        "website": "https://localplumbing.example.com",
        "phone_google": "(215) 555-1234",
        "user_ratings_total": 10,
        "business_status": "OPERATIONAL",
        "reviews": [],
    }
    base.update(overrides)
    return base


@SKIP
class TestFranchiseAndOwner(unittest.TestCase):
    def test_is_franchise_matches_name(self):
        self.assertTrue(
            LEADGEN.is_franchise("Roto-Rooter of Cherry Hill", "https://example.com")
        )

    def test_is_franchise_matches_domain(self):
        self.assertTrue(
            LEADGEN.is_franchise("Local Cleaners", "https://www.servpro.com/locations/nj")
        )

    def test_independent_business_not_franchise(self):
        self.assertFalse(
            LEADGEN.is_franchise(
                "Alspach Landscaping",
                "https://www.alspachlandscaping.com/",
            )
        )

    def test_franchise_rejected_when_enabled(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(business_name="Molly Maid of Philly"),
            filter_franchises=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "franchise")

    def test_franchise_kept_when_disabled(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(business_name="Molly Maid of Philly"),
            filter_franchises=False,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_extract_owner_names_from_reviews(self):
        reviews = [
            {"text": "Ask for Mike next time, he was great."},
            {"text": "Sarah the owner was wonderful to work with."},
        ]
        names = LEADGEN.extract_owner_names(reviews)
        self.assertIn("Mike", names)
        self.assertIn("Sarah", names)

    def test_extract_owner_names_empty(self):
        self.assertEqual(LEADGEN.extract_owner_names([]), [])
        self.assertEqual(LEADGEN.extract_owner_names([{"text": "Good job."}]), [])


@SKIP
class TestSelectionHelpers(unittest.TestCase):
    def test_locations_by_state_groups_coords(self):
        sample = {
            "NJ": {"Cherry Hill": "39.9,-75.1", "Cinnaminson": "40.0,-75.0"},
            "DE": {"Dover": "39.1,-75.5"},
        }
        grouped = LEADGEN._locations_by_state(sample)
        self.assertEqual(list(grouped.keys()), ["NJ", "DE"])
        self.assertEqual(len(grouped["NJ"]), 2)
        self.assertEqual(grouped["NJ"][0][0], "Cherry Hill")
        self.assertEqual(grouped["DE"][0][1], "39.1,-75.5")

    def test_parse_index_selection_all_on_empty(self):
        self.assertIsNone(LEADGEN._parse_index_selection("", 5))
        self.assertIsNone(LEADGEN._parse_index_selection("   ", 5))

    def test_parse_index_selection_parses_commas(self):
        self.assertEqual(LEADGEN._parse_index_selection("1,3", 5), [0, 2])

    def test_parse_index_selection_ignores_invalid(self):
        self.assertEqual(LEADGEN._parse_index_selection("0,99,abc,2", 5), [1])

    def test_format_numbered_items_horizontal_wraps(self):
        text = LEADGEN._format_numbered_items_horizontal(
            ["alpha", "beta", "gamma"],
            width=20,
        )
        lines = text.splitlines()
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("1) alpha"))
        self.assertIn("2) beta", text)
        self.assertIn("3) gamma", text)

    def test_format_numbered_items_horizontal_packs_wide(self):
        text = LEADGEN._format_numbered_items_horizontal(
            ["a", "b", "c"],
            width=80,
        )
        self.assertEqual(text, "1) a  2) b  3) c")


@SKIP
class TestSettingsPersistence(unittest.TestCase):
    def test_save_and_load_settings_round_trip(self):
        cfg = LEADGEN.LeadgenConfig(
            min_score=70,
            min_reviews=8,
            filter_franchises=False,
            require_phone=True,
            require_website=True,
            require_email=True,
            lead_enrichment=False,
            output_mode="both",
            json_output="custom_leads.json",
            keywords=["landscaping"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadgen_settings.json"
            payload = LEADGEN.save_settings(cfg, path=path)
            self.assertEqual(payload["min_score"], 70)
            self.assertTrue(payload["require_website"])
            self.assertTrue(payload["require_email"])
            self.assertTrue(payload["require_phone"])
            self.assertFalse(payload["lead_enrichment"])
            self.assertNotIn("keywords", payload)
            loaded = LEADGEN.load_saved_settings(path=path)
            self.assertEqual(loaded["min_score"], 70)
            self.assertEqual(loaded["min_reviews"], 8)
            self.assertFalse(loaded["filter_franchises"])
            self.assertTrue(loaded["require_website"])
            self.assertTrue(loaded["require_email"])
            self.assertFalse(loaded["lead_enrichment"])
            self.assertEqual(loaded["output_mode"], "both")
            self.assertEqual(loaded["json_output"], "custom_leads.json")
            rebuilt = LEADGEN.config_from_saved_settings(path=path)
            self.assertEqual(rebuilt.min_score, 70)
            self.assertEqual(rebuilt.output_mode, "both")
            self.assertTrue(rebuilt.require_website)
            self.assertTrue(rebuilt.require_email)
            self.assertTrue(rebuilt.require_phone)
            self.assertFalse(rebuilt.lead_enrichment)
            self.assertEqual(list(LEADGEN.KEYWORD_CATEGORIES.keys()), rebuilt.keywords)

    def test_load_saved_settings_migrates_legacy_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadgen_settings.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "min_score": 75,
                        "output_mode": "csv",
                        "csv_output": "old_leads.csv",
                    },
                    f,
                )
            loaded = LEADGEN.load_saved_settings(path=path)
            self.assertEqual(loaded["output_mode"], "json")
            self.assertEqual(loaded["json_output"], "old_leads.json")
            self.assertNotIn("csv_output", loaded)

    def test_load_saved_settings_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            self.assertEqual(LEADGEN.load_saved_settings(path=path), {})

    def test_interactive_customize_saves_without_running(self):
        fake_cfg = LEADGEN.LeadgenConfig(min_score=65, output_mode="dashboard")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadgen_settings.json"
            with patch.object(LEADGEN, "SETTINGS_PATH", path), \
                    patch.object(LEADGEN, "interactive_customize_config", return_value=fake_cfg), \
                    patch.object(LEADGEN, "interactive_run_config") as mock_run, \
                    patch("builtins.input", side_effect=["2", "3"]):
                result = LEADGEN.interactive_main_menu()
            self.assertIsNone(result)
            mock_run.assert_not_called()
            saved = LEADGEN.load_saved_settings(path=path)
            self.assertEqual(saved["min_score"], 65)
            self.assertEqual(saved["output_mode"], "dashboard")


@SKIP
class TestLeadEnrichmentSetting(unittest.TestCase):
    def _run_config(self, **overrides):
        base = dict(
            output_mode="json",
            keywords=["landscaping"],
            locations=[("NJ", "Cherry Hill", "39.9,-75.0")],
        )
        base.update(overrides)
        return LEADGEN.LeadgenConfig(**base)

    def _run_leadgen(self, config, rows, mock_enrich, contacted_file="no_contacted_file.txt"):
        with patch.object(LEADGEN, "GOOGLE_API_KEY", "fake-key"), \
                patch.object(LEADGEN, "CONTACTED_FILE", contacted_file), \
                patch.object(LEADGEN, "load_existing_place_ids", return_value=set()), \
                patch.object(LEADGEN, "get_places", return_value=[{"place_id": "pid1"}]), \
                patch.object(LEADGEN, "process_businesses", return_value=rows), \
                patch.object(LEADGEN, "enrich_missing_emails", mock_enrich), \
                patch.object(LEADGEN, "save_results") as mock_save:
            LEADGEN.run_leadgen(config)
        return mock_save

    def test_enabled_by_default(self):
        self.assertTrue(LEADGEN.LeadgenConfig().lead_enrichment)

    def test_legacy_settings_without_key_keep_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadgen_settings.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"min_score": 70}, f)
            self.assertTrue(LEADGEN.config_from_saved_settings(path=path).lead_enrichment)

    def test_cli_flag_disables_and_counts_as_override(self):
        with patch.object(sys, "argv", ["leadgen.py", "--no-lead-enrichment"]):
            args = LEADGEN.parse_args()
        self.assertFalse(args.lead_enrichment)
        self.assertTrue(LEADGEN._has_cli_overrides(args))
        with patch.object(LEADGEN, "config_from_saved_settings", return_value=LEADGEN.LeadgenConfig()):
            self.assertFalse(LEADGEN.config_from_args(args).lead_enrichment)

    def test_run_leadgen_enriches_before_output(self):
        rows = [{"business_name": "A", "place_id": "pid1", "email": "", "lead_score": 90}]
        mock_enrich = MagicMock(return_value=[])
        mock_save = self._run_leadgen(self._run_config(lead_enrichment=True), rows, mock_enrich)
        mock_enrich.assert_called_once_with(rows)
        mock_save.assert_called_once()

    def test_run_leadgen_skips_enrichment_when_disabled(self):
        rows = [{"business_name": "A", "place_id": "pid1", "email": "", "lead_score": 90}]
        mock_enrich = MagicMock()
        mock_save = self._run_leadgen(self._run_config(lead_enrichment=False), rows, mock_enrich)
        mock_enrich.assert_not_called()
        mock_save.assert_called_once()

    def test_enriched_lead_already_contacted_is_dropped(self):
        rows = [
            {"business_name": "A", "place_id": "pid1", "email": "office@biz.example", "lead_score": 90},
            {"business_name": "B", "place_id": "pid2", "email": "", "lead_score": 80},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            contacted = os.path.join(tmp, "contacted.txt")
            with open(contacted, "w", encoding="utf-8") as f:
                f.write("office@biz.example\n")
            mock_save = self._run_leadgen(
                self._run_config(lead_enrichment=True),
                rows,
                MagicMock(return_value=[rows[0]]),
                contacted_file=contacted,
            )
        saved_rows = mock_save.call_args.args[0]
        self.assertEqual([row["place_id"] for row in saved_rows], ["pid2"])

    def test_enrich_missing_emails_returns_enriched_rows(self):
        row = {"business_name": "A", "email": ""}
        fake_module = MagicMock()
        fake_module.enrich_leads.return_value = [row]
        with patch.dict(sys.modules, {"leadenrich": fake_module}):
            self.assertEqual(LEADGEN.enrich_missing_emails([row]), [row])

    def test_enrich_missing_emails_swallows_failure(self):
        fake_module = MagicMock()
        fake_module.enrich_leads.side_effect = RuntimeError("actor down")
        with patch.dict(sys.modules, {"leadenrich": fake_module}):
            self.assertEqual(LEADGEN.enrich_missing_emails([{"email": ""}]), [])


@SKIP
class TestQualityFilters(unittest.TestCase):
    def test_valid_us_phone(self):
        self.assertTrue(LEADGEN.is_valid_us_phone("(215) 555-1234"))
        self.assertFalse(LEADGEN.is_valid_us_phone("555"))
        self.assertFalse(LEADGEN.is_valid_us_phone(None))

    def test_closed_business_rejected(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(business_status="CLOSED_PERMANENTLY")
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "closed_business")

    def test_missing_status_kept(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(business_status=None)
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_low_review_count_rejected(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(user_ratings_total=4),
            min_reviews=5,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "low_review_count")

    def test_min_review_count_accepted(self):
        ok, _ = LEADGEN.passes_quality_filters(
            _quality_entry(user_ratings_total=5),
            min_reviews=5,
        )
        self.assertTrue(ok)

    def test_stale_review_rejected(self):
        old_ts = int(time.time()) - (19 * 30 * 24 * 60 * 60)
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(reviews=[{"time": old_ts}])
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "stale_reviews")

    def test_no_reviews_passes_recency_check(self):
        ok, _ = LEADGEN.passes_quality_filters(_quality_entry(reviews=[]))
        self.assertTrue(ok)

    def test_invalid_phone_rejected_when_required(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(phone_google=None),
            require_phone=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "invalid_phone")

    def test_invalid_phone_kept_when_not_required(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(phone_google=None),
            require_phone=False,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_no_website_rejected_when_required(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(website=None),
            require_website=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "no_website")

    def test_no_website_kept_when_not_required(self):
        ok, reason = LEADGEN.passes_quality_filters(
            _quality_entry(website=None),
            require_website=False,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_latest_review_timestamp(self):
        reviews = [{"time": 100}, {"time": 300}]
        self.assertEqual(LEADGEN.latest_review_timestamp(reviews), 300)


@SKIP
class TestScoreLead(unittest.TestCase):
    def test_score_weights_sum_to_100(self):
        self.assertEqual(sum(LEADGEN.SCORE_WEIGHTS.values()), 100)

    def test_no_website_good_google_normalized(self):
        self.assertEqual(
            LEADGEN.score_lead(
                has_website=False,
                https=False,
                has_viewport=False,
                html_length=0,
                has_email=False,
                has_cta=False,
                rating=5.0,
                user_ratings_total=100,
                business_status="OPERATIONAL",
            ),
            round(40 / 50 * 100),
        )

    def test_no_website_all_fail_scores_100(self):
        self.assertEqual(
            LEADGEN.score_lead(
                has_website=False,
                https=False,
                has_viewport=False,
                html_length=0,
                has_email=True,
                has_cta=False,
                rating=4.0,
                user_ratings_total=10,
                business_status=None,
            ),
            100,
        )

    def test_ideal_lead_zero_score(self):
        self.assertEqual(
            LEADGEN.score_lead(
                has_website=True,
                https=True,
                has_viewport=True,
                html_length=5000,
                has_email=False,
                has_cta=True,
                rating=5.0,
                user_ratings_total=20,
                business_status="OPERATIONAL",
            ),
            0,
        )

    def test_has_email_increases_score(self):
        base_kwargs = dict(
            has_website=True,
            https=True,
            has_viewport=True,
            html_length=5000,
            has_cta=True,
            rating=5.0,
            user_ratings_total=20,
            business_status="OPERATIONAL",
        )
        without = LEADGEN.score_lead(has_email=False, **base_kwargs)
        with_email = LEADGEN.score_lead(has_email=True, **base_kwargs)
        self.assertGreater(with_email, without)

    def test_all_fail_website_scores_100(self):
        self.assertEqual(
            LEADGEN.score_lead(
                has_website=True,
                https=False,
                has_viewport=False,
                html_length=1000,
                has_email=True,
                has_cta=False,
                rating=4.0,
                user_ratings_total=10,
                business_status=None,
            ),
            100,
        )

    def test_partial_website_issues_normalized(self):
        score = LEADGEN.score_lead(
            has_website=True,
            https=False,
            has_viewport=False,
            html_length=1000,
            has_email=True,
            has_cta=True,
            rating=5.0,
            user_ratings_total=20,
            business_status="OPERATIONAL",
        )
        self.assertEqual(score, round((18 + 14 + 14 + 6) / 60 * 100))


@SKIP
class TestProcessBusinessesFilter(unittest.TestCase):
    def _details(self, **overrides):
        base = {
            "website": "http://example.com",
            "phone_google": "(215) 555-1234",
            "address": "1 Main",
            "business_status": "OPERATIONAL",
            "reviews": [],
            "rating": 5.0,
            "user_ratings_total": 20,
        }
        base.update(overrides)
        return base

    @patch("leadgen.get_place_details")
    @patch("leadgen.analyze_website")
    @patch("leadgen.time.sleep", return_value=None)
    def test_filters_below_min_score(self, _sleep, mock_analyze, mock_details):
        mock_details.return_value = self._details()
        mock_analyze.return_value = {
            "emails": ["a@b.com"],
            "phones_website": [],
            "https": True,
            "has_viewport": True,
            "html_length": 5000,
            "has_title": True,
            "has_cta": True,
            "error": None,
        }
        businesses = [{
            "place_id": "pid1",
            "business_name": "Good Site Co",
            "rating": 5.0,
            "user_ratings_total": 20,
            "niche_key": "landscaping",
            "address": "1 Main",
        }]
        rows = LEADGEN.process_businesses(
            businesses,
            "fake-key",
            set(),
            set(),
            min_score=80,
        )
        self.assertEqual(rows, [])

    @patch("leadgen.get_place_details")
    @patch("leadgen.analyze_website")
    @patch("leadgen.time.sleep", return_value=None)
    def test_quality_filter_rejects_closed_before_scrape(self, _sleep, mock_analyze, mock_details):
        mock_details.return_value = self._details(business_status="CLOSED_PERMANENTLY")
        businesses = [{
            "place_id": "pid1",
            "business_name": "Closed Co",
            "rating": 5.0,
            "user_ratings_total": 20,
            "niche_key": "landscaping",
            "address": "1 Main",
        }]
        rows = LEADGEN.process_businesses(
            businesses,
            "fake-key",
            set(),
            set(),
            min_score=0,
        )
        self.assertEqual(rows, [])
        mock_analyze.assert_not_called()

    @patch("leadgen.get_place_details")
    @patch("leadgen.analyze_website")
    @patch("leadgen.time.sleep", return_value=None)
    def test_qualifying_row_includes_place_id_and_address(self, _sleep, mock_analyze, mock_details):
        mock_details.return_value = self._details(
            website=None,
            address="99 Oak Ave, Cherry Hill, NJ",
        )
        mock_analyze.return_value = {
            "emails": [],
            "phones_website": [],
            "https": False,
            "has_viewport": False,
            "html_length": 0,
            "has_title": False,
            "has_cta": False,
            "error": None,
        }
        businesses = [{
            "place_id": "pid-abc",
            "business_name": "No Site Co",
            "rating": 5.0,
            "user_ratings_total": 20,
            "niche_key": "landscaping",
            "address": "vicinity fallback",
        }]
        rows = LEADGEN.process_businesses(
            businesses,
            "fake-key",
            set(),
            set(),
            min_score=0,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["place_id"], "pid-abc")
        self.assertEqual(rows[0]["address"], "99 Oak Ave, Cherry Hill, NJ")
        self.assertEqual(rows[0]["email"], "")
        self.assertFalse(rows[0]["has_email"])

    @patch("leadgen.get_place_details")
    @patch("leadgen.analyze_website")
    @patch("leadgen.time.sleep", return_value=None)
    def test_require_website_rejects_before_scrape(self, _sleep, mock_analyze, mock_details):
        mock_details.return_value = self._details(website=None)
        businesses = [{
            "place_id": "pid1",
            "business_name": "No Site Co",
            "rating": 5.0,
            "user_ratings_total": 20,
            "niche_key": "landscaping",
            "address": "1 Main",
        }]
        rows = LEADGEN.process_businesses(
            businesses,
            "fake-key",
            set(),
            set(),
            min_score=0,
            require_website=True,
        )
        self.assertEqual(rows, [])
        mock_analyze.assert_not_called()

    @patch("leadgen.get_place_details")
    @patch("leadgen.analyze_website")
    @patch("leadgen.time.sleep", return_value=None)
    def test_require_email_filters_after_scrape(self, _sleep, mock_analyze, mock_details):
        mock_details.return_value = self._details()
        mock_analyze.return_value = {
            "emails": [],
            "phones_website": [],
            "https": True,
            "has_viewport": True,
            "html_length": 5000,
            "has_title": True,
            "has_cta": True,
            "error": None,
        }
        businesses = [{
            "place_id": "pid1",
            "business_name": "No Email Co",
            "rating": 5.0,
            "user_ratings_total": 20,
            "niche_key": "landscaping",
            "address": "1 Main",
        }]
        rows = LEADGEN.process_businesses(
            businesses,
            "fake-key",
            set(),
            set(),
            min_score=0,
            require_email=True,
        )
        self.assertEqual(rows, [])
        mock_analyze.assert_called_once()

    @patch("leadgen.get_place_details")
    @patch("leadgen.analyze_website")
    @patch("leadgen.time.sleep", return_value=None)
    def test_require_email_keeps_lead_with_email(self, _sleep, mock_analyze, mock_details):
        mock_details.return_value = self._details()
        mock_analyze.return_value = {
            "emails": ["hello@example.com"],
            "phones_website": [],
            "https": False,
            "has_viewport": False,
            "html_length": 100,
            "has_title": False,
            "has_cta": False,
            "error": None,
        }
        businesses = [{
            "place_id": "pid1",
            "business_name": "Email Co",
            "rating": 4.0,
            "user_ratings_total": 5,
            "niche_key": "landscaping",
            "address": "1 Main",
        }]
        rows = LEADGEN.process_businesses(
            businesses,
            "fake-key",
            set(),
            set(),
            min_score=0,
            require_email=True,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["email"], "hello@example.com")
        self.assertTrue(rows[0]["has_email"])


@SKIP
class TestSendToDashboard(unittest.TestCase):
    @patch("helper_scripts.api_manager.APIManager")
    def test_send_to_dashboard_builds_bulk_payload(self, mock_api_cls):
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        rows = [{
            "business_name": "Test Biz",
            "address": "123 Main St, Houston, TX 77001, USA",
            "phone_google": "555-1234",
            "email": "contact@test.com",
            "niche_key": "landscaping",
            "lead_score": 85,
        }]
        LEADGEN.send_to_dashboard(rows)
        mock_api.build_request.assert_called_once()
        call_kwargs = mock_api.build_request.call_args.kwargs
        self.assertEqual(call_kwargs["endpoint"], LEADGEN.DASHBOARD_BULK_ENDPOINT)
        payload = call_kwargs["json_body"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["business_name"], "Test Biz")
        self.assertEqual(payload[0]["address"], "123 Main St, Houston, TX 77001, USA")
        self.assertEqual(payload[0]["score"], 85)
        self.assertEqual(payload[0]["category"], "landscaping-leads")


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
        self.assertEqual(places[0]["niche_key"], "landscaping")
        self.assertIn("place_id", places[0])


@SKIP
class TestSaveResults(unittest.TestCase):
    def test_save_results_new_file(self):
        rows = [
            {
                "business_name": "A",
                "place_id": "ChIJabc",
                "address": "1 St",
                "phone_google": "555",
                "phone_website": None,
                "email": "a@a.com",
                "has_email": True,
                "website": "https://a.com",
                "rating": 4.0,
                "user_ratings_total": 10,
                "business_status": "OPERATIONAL",
                "https": True,
                "has_viewport": True,
                "html_length": 5000,
                "lead_score": 0,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "leads_out.json")
            LEADGEN.save_results(rows, path)
            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["place_id"], "ChIJabc")
            self.assertEqual(data[0]["business_name"], "A")
            self.assertTrue(data[0]["has_email"])

    def test_save_results_appends_and_dedupes_by_place_id(self):
        existing = [
            {
                "business_name": "Old",
                "place_id": "pid1",
                "lead_score": 50,
                "website": "https://old.com",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "leads_out.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f)
            LEADGEN.save_results(
                [
                    {
                        "business_name": "Old Again",
                        "place_id": "pid1",
                        "lead_score": 90,
                        "website": "https://old.com",
                    },
                    {
                        "business_name": "New",
                        "place_id": "pid2",
                        "lead_score": 80,
                        "website": "https://new.com",
                    },
                ],
                path,
            )
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            ids = {row["place_id"] for row in data}
            self.assertEqual(ids, {"pid1", "pid2"})
            # First occurrence of pid1 kept (score 50); pid2 score 80 sorts first
            self.assertEqual(data[0]["place_id"], "pid2")
            self.assertEqual(data[1]["business_name"], "Old")


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
        mock_get.assert_called()
        call_kwargs = mock_get.call_args.kwargs
        self.assertIn("User-Agent", call_kwargs.get("headers", {}))

    @patch("leadgen.requests.get")
    def test_parses_mailto_href(self, mock_get):
        html = (
            '<html><body><a href="mailto:sales@biz.example?subject=Hi">Email</a>'
            "</body></html>"
        )
        resp = MagicMock()
        resp.text = html
        mock_get.return_value = resp
        out = LEADGEN.analyze_website("https://biz.example")
        self.assertIn("sales@biz.example", out["emails"])

    @patch("leadgen.requests.get")
    def test_https_retry_when_http_body_tiny(self, mock_get):
        tiny = MagicMock()
        tiny.text = "ok"
        rich = MagicMock()
        rich.text = (
            "<!doctype html><html><head><title>Biz</title></head>"
            "<body>Contact info@biz.example for a quote. " + ("x" * 300) + "</body></html>"
        )

        def _side_effect(url, **_kwargs):
            if url.startswith("https://"):
                return rich
            return tiny

        mock_get.side_effect = _side_effect
        out = LEADGEN.analyze_website("http://biz.example")
        self.assertTrue(out["https"])
        self.assertIn("info@biz.example", out["emails"])
        self.assertGreaterEqual(mock_get.call_count, 2)

    @patch("leadgen.requests.get")
    def test_contact_page_fallback_when_homepage_has_no_email(self, mock_get):
        home = MagicMock()
        home.text = "<html><body>Call us for a quote</body></html>"
        contact = MagicMock()
        contact.text = "<html><body>Email hello@biz.example</body></html>"

        def _side_effect(url, **_kwargs):
            if url.rstrip("/").endswith("/contact"):
                return contact
            return home

        mock_get.side_effect = _side_effect
        out = LEADGEN.analyze_website("https://biz.example")
        self.assertIn("hello@biz.example", out["emails"])
        self.assertGreaterEqual(mock_get.call_count, 2)

    def test_extract_emails_from_mailto_soup(self):
        html = '<a href="mailto:Owner@Example.COM">mail</a>'
        soup = LEADGEN.BeautifulSoup(html, "html.parser")
        emails = LEADGEN._extract_emails_from_html(html, soup=soup)
        self.assertEqual(emails, ["owner@example.com"])


if __name__ == "__main__":
    unittest.main()
