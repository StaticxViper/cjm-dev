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

    def test_parse_index_selection_ranges_and_none(self):
        self.assertEqual(LEADGEN._parse_index_selection("1-3,5", 5), [0, 1, 2, 4])
        self.assertEqual(LEADGEN._parse_index_selection("4-2", 5), [1, 2, 3])
        self.assertEqual(LEADGEN._parse_index_selection("all", 5), None)
        self.assertEqual(LEADGEN._parse_index_selection("none", 5), [])
        self.assertEqual(LEADGEN._parse_index_selection("1-99,abc", 3), [0, 1, 2])

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
            objective="both",
            require_website=True,
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
            self.assertEqual(payload["objective"], "both")
            self.assertNotIn("require_phone", payload)
            self.assertNotIn("require_email", payload)
            self.assertFalse(payload["lead_enrichment"])
            self.assertNotIn("keywords", payload)
            loaded = LEADGEN.load_saved_settings(path=path)
            self.assertEqual(loaded["min_score"], 70)
            self.assertEqual(loaded["min_reviews"], 8)
            self.assertFalse(loaded["filter_franchises"])
            self.assertTrue(loaded["require_website"])
            self.assertEqual(loaded["objective"], "both")
            self.assertFalse(loaded["lead_enrichment"])
            self.assertEqual(loaded["output_mode"], "both")
            self.assertEqual(loaded["json_output"], "custom_leads.json")
            rebuilt = LEADGEN.config_from_saved_settings(path=path)
            self.assertEqual(rebuilt.min_score, 70)
            self.assertEqual(rebuilt.output_mode, "both")
            self.assertTrue(rebuilt.require_website)
            self.assertEqual(rebuilt.objective, "both")
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

    def test_load_saved_settings_migrates_require_flags_to_objective(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadgen_settings.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "min_score": 60,
                        "require_phone": False,
                        "require_email": True,
                    },
                    f,
                )
            loaded = LEADGEN.load_saved_settings(path=path)
            self.assertEqual(loaded["objective"], "email")
            rebuilt = LEADGEN.config_from_saved_settings(path=path)
            self.assertEqual(rebuilt.objective, "email")

    def test_interactive_customize_saves_without_running(self):
        fake_cfg = LEADGEN.LeadgenConfig(min_score=65, output_mode="dashboard")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadgen_settings.json"
            with patch.object(LEADGEN, "SETTINGS_PATH", path), \
                    patch.object(LEADGEN, "interactive_customize_config", return_value=fake_cfg), \
                    patch.object(LEADGEN, "interactive_run_config") as mock_run, \
                    patch("builtins.input", side_effect=["2", "4"]):
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
            skip_searched=False,
        )
        base.update(overrides)
        return LEADGEN.LeadgenConfig(**base)

    def _run_leadgen(self, config, rows, mock_enrich, contacted_file="no_contacted_file.txt"):
        with tempfile.TemporaryDirectory() as tmp:
            config.search_history_path = str(Path(tmp) / "history.json")
            with patch.object(LEADGEN, "GOOGLE_API_KEY", "fake-key"), \
                    patch.object(LEADGEN, "CONTACTED_FILE", contacted_file), \
                    patch.object(LEADGEN, "load_existing_place_ids", return_value=set()), \
                    patch.object(LEADGEN, "load_existing_identities", return_value=set()), \
                    patch.object(LEADGEN, "get_places", return_value=[{"place_id": "pid1"}]), \
                    patch.object(LEADGEN, "process_businesses", return_value=rows), \
                    patch.object(LEADGEN, "enrich_missing_emails", mock_enrich), \
                    patch.object(LEADGEN, "update_usage_stats", return_value={"total_calls": 0}), \
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
        mock_enrich.assert_called_once_with(rows, leadgen_type="api_manager")
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

    def test_enrich_missing_emails_playwright_dispatches_to_playwright_module(self):
        row = {"business_name": "A", "email": ""}
        fake_module = MagicMock()
        fake_module.enrich_leads.return_value = [row]
        with patch.dict(sys.modules, {"leadenrich_playwright": fake_module}):
            self.assertEqual(
                LEADGEN.enrich_missing_emails([row], leadgen_type="playwright"),
                [row],
            )
        fake_module.enrich_leads.assert_called_once()

    def test_enrich_missing_emails_playwright_swallows_failure(self):
        fake_module = MagicMock()
        fake_module.enrich_leads.side_effect = RuntimeError("browser down")
        with patch.dict(sys.modules, {"leadenrich_playwright": fake_module}):
            self.assertEqual(
                LEADGEN.enrich_missing_emails([{"email": ""}], leadgen_type="playwright"),
                [],
            )

    def test_run_leadgen_playwright_passes_leadgen_type_to_enrichment(self):
        rows = [{"business_name": "A", "place_id": "pid1", "email": "", "lead_score": 90}]
        mock_enrich = MagicMock(return_value=[])
        with tempfile.TemporaryDirectory() as tmp:
            config = self._run_config(lead_enrichment=True, leadgen_type="playwright")
            config.search_history_path = str(Path(tmp) / "history.json")
            with patch.object(LEADGEN, "CONTACTED_FILE", "no_contacted_file.txt"), \
                    patch.object(LEADGEN, "load_existing_place_ids", return_value=set()), \
                    patch.object(LEADGEN, "load_existing_identities", return_value=set()), \
                    patch.object(
                        LEADGEN,
                        "gather_leads_playwright",
                        return_value=(rows, {"qualified_leads": 1}),
                    ), \
                    patch.object(LEADGEN, "enrich_missing_emails", mock_enrich), \
                    patch.object(LEADGEN, "save_results"):
                LEADGEN.run_leadgen(config)
        mock_enrich.assert_called_once_with(rows, leadgen_type="playwright")

    def test_gather_leads_playwright_persists_after_each_location(self):
        class FakeSession:
            google_blocked = False
            stats = {"pages_processed": 2}

            def search_location(self, keyword, city, state, **_kwargs):
                return [{
                    "business_name": f"{city} Biz",
                    "place_id": f"pid-{city.replace(' ', '-')}",
                    "website": "",
                    "phone_google": "555-123-4567",
                    "address": f"1 Main, {city}, {state}",
                }]

            def enrich_listing(self, stub):
                return dict(stub)

            def close(self):
                pass

        persisted = []

        def fake_persist(rows, config, location_label=None, json_path=None):
            persisted.append((location_label, [row.get("place_id") for row in rows]))
            return len(rows), len(rows)

        def fake_process(businesses, **_kwargs):
            first = businesses[0]
            return [{
                "business_name": first["business_name"],
                "place_id": first["place_id"],
                "lead_score": 80,
                "email": "",
            }]

        with tempfile.TemporaryDirectory() as tmp:
            config = self._run_config(
                lead_enrichment=False,
                leadgen_type="playwright",
                output_mode="both",
                keywords=["notary"],
                locations=[
                    ("UT", "Salt Lake City", "40.7,-111.8"),
                    ("NV", "Las Vegas", "36.1,-115.1"),
                ],
            )
            config.search_history_path = str(Path(tmp) / "history.json")
            config.json_output = str(Path(tmp) / "leads.json")
            with patch.object(LEADGEN, "BusinessDiscoverySession", return_value=FakeSession()), \
                    patch.object(LEADGEN, "process_businesses", side_effect=fake_process), \
                    patch.object(LEADGEN, "persist_lead_batch", side_effect=fake_persist), \
                    patch.object(LEADGEN, "listing_needs_detail", return_value=False):
                rows, stats = LEADGEN.gather_leads_playwright(
                    config,
                    set(),
                    set(),
                    {"places_nearby": 0, "places_details": 0},
                )

        self.assertEqual(
            [label for label, _ids in persisted],
            ["Salt Lake City, UT", "Las Vegas, NV"],
        )
        self.assertTrue(stats["flushed_incrementally"])
        self.assertEqual(stats["qualified_leads"], 2)
        self.assertEqual(stats["saved"], 2)
        self.assertEqual(stats["uploaded"], 2)
        self.assertEqual(len(rows), 2)

    def test_persist_lead_batch_saves_and_uploads(self):
        rows = [{"business_name": "A", "place_id": "pid1", "lead_score": 80}]
        config = self._run_config(output_mode="both")
        with patch.object(LEADGEN, "save_results") as mock_save, \
                patch.object(LEADGEN, "send_to_dashboard", return_value=1) as mock_send:
            saved, uploaded = LEADGEN.persist_lead_batch(
                rows, config, location_label="Cherry Hill, NJ"
            )
        mock_save.assert_called_once()
        mock_send.assert_called_once_with(rows)
        self.assertEqual((saved, uploaded), (1, 1))


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

    @patch("leadgen.enrich_lead_with_email", side_effect=lambda lead, **_kwargs: lead)
    @patch("leadgen.get_place_details")
    @patch("leadgen.analyze_website")
    @patch("leadgen.time.sleep", return_value=None)
    def test_require_email_filters_after_scrape(self, _sleep, mock_analyze, mock_details, _enrich):
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
            objective="email",
        )
        self.assertEqual(rows, [])
        mock_analyze.assert_called_once()

    @patch("leadgen.get_place_details")
    @patch("leadgen.analyze_website")
    @patch("leadgen.time.sleep", return_value=None)
    def test_require_email_keeps_lead_with_email(self, _sleep, mock_analyze, mock_details):
        mock_details.return_value = self._details()
        mock_analyze.return_value = {
            "emails": ["hello@biz.example"],
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
            objective="email",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["email"], "hello@biz.example")
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
        uploaded = LEADGEN.send_to_dashboard(rows)
        self.assertEqual(uploaded, 1)
        mock_api.build_request.assert_called_once()
        call_kwargs = mock_api.build_request.call_args.kwargs
        self.assertEqual(call_kwargs["endpoint"], LEADGEN.DASHBOARD_BULK_ENDPOINT)
        payload = call_kwargs["json_body"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["business_name"], "Test Biz")
        self.assertEqual(payload[0]["address"], "123 Main St, Houston, TX 77001, USA")
        self.assertEqual(payload[0]["score"], 85)
        self.assertEqual(payload[0]["category"], "landscaping-leads")

    @patch("leadgen.time.sleep", return_value=None)
    @patch("helper_scripts.api_manager.APIManager")
    def test_send_to_dashboard_connect_error_does_not_raise(self, mock_api_cls, _sleep):
        mock_api = MagicMock()
        mock_api.build_request.side_effect = ConnectionError("getaddrinfo failed")
        mock_api_cls.return_value = mock_api
        rows = [{
            "business_name": "Test Biz",
            "address": "123 Main St, Houston, TX 77001, USA",
            "phone_google": "555-1234",
            "email": "contact@test.com",
            "niche_key": "landscaping",
            "lead_score": 85,
        }]
        uploaded = LEADGEN.send_to_dashboard(rows)
        self.assertEqual(uploaded, 0)
        self.assertEqual(mock_api.build_request.call_count, 3)

    def test_persist_lead_batch_keeps_json_when_upload_fails(self):
        rows = [{"business_name": "A", "place_id": "pid1", "lead_score": 80}]
        config = LEADGEN.LeadgenConfig(output_mode="both", json_output="leads_output.json")
        with patch.object(LEADGEN, "save_results") as mock_save, \
                patch.object(LEADGEN, "send_to_dashboard", side_effect=ConnectionError("dns")):
            saved, uploaded = LEADGEN.persist_lead_batch(
                rows, config, location_label="Jacksonville, FL"
            )
        mock_save.assert_called_once()
        self.assertEqual(saved, 1)
        self.assertEqual(uploaded, 0)


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
        </head><body>Contact us at support@biz.example for a quote.
        </body></html>"""
        resp = MagicMock()
        resp.text = html.decode("utf-8")
        mock_get.return_value = resp

        out = LEADGEN.analyze_website("https://biz.example")
        self.assertIn("support@biz.example", out["emails"])
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
        html = '<a href="mailto:Owner@Biz.example">mail</a>'
        soup = LEADGEN.BeautifulSoup(html, "html.parser")
        emails = LEADGEN._extract_emails_from_html(html, soup=soup)
        self.assertEqual(emails, ["owner@biz.example"])


@SKIP
class TestLeadMeetsObjective(unittest.TestCase):
    def _lead(self, phone=None, email=""):
        return {
            "business_name": "Local Plumbing LLC",
            "phone_google": phone,
            "phone_website": None,
            "email": email,
            "has_email": bool(email),
        }

    def test_phone_requires_phone(self):
        self.assertTrue(
            LEADGEN.lead_meets_objective(self._lead(phone="(215) 555-1234"), "phone")
        )
        self.assertFalse(LEADGEN.lead_meets_objective(self._lead(), "phone"))

    def test_email_requires_email(self):
        self.assertTrue(
            LEADGEN.lead_meets_objective(self._lead(email="info@biz.example"), "email")
        )
        self.assertFalse(LEADGEN.lead_meets_objective(self._lead(), "email"))

    def test_either_accepts_phone_or_email(self):
        self.assertTrue(
            LEADGEN.lead_meets_objective(self._lead(phone="(215) 555-1234"), "either")
        )
        self.assertTrue(
            LEADGEN.lead_meets_objective(self._lead(email="info@biz.example"), "either")
        )
        self.assertTrue(
            LEADGEN.lead_meets_objective(
                self._lead(phone="(215) 555-1234", email="info@biz.example"),
                "either",
            )
        )
        self.assertFalse(LEADGEN.lead_meets_objective(self._lead(), "either"))

    def test_both_requires_phone_and_email(self):
        self.assertFalse(
            LEADGEN.lead_meets_objective(self._lead(phone="(215) 555-1234"), "both")
        )
        self.assertFalse(
            LEADGEN.lead_meets_objective(self._lead(email="info@biz.example"), "both")
        )
        self.assertTrue(
            LEADGEN.lead_meets_objective(
                self._lead(phone="(215) 555-1234", email="info@biz.example"),
                "both",
            )
        )

    def test_score_cannot_override_objective(self):
        lead = self._lead()
        lead["lead_score"] = 99
        self.assertFalse(LEADGEN.lead_meets_objective(lead, "email"))
        self.assertFalse(LEADGEN.lead_meets_objective(lead, "phone"))

    def test_legacy_flags_map_to_objective(self):
        self.assertEqual(LEADGEN.objective_from_require_flags(True, False), "phone")
        self.assertEqual(LEADGEN.objective_from_require_flags(False, True), "email")
        self.assertEqual(LEADGEN.objective_from_require_flags(True, True), "both")
        self.assertEqual(LEADGEN.objective_from_require_flags(False, False), "either")

    def test_cli_objective_wins_over_legacy_flags(self):
        with patch.object(
            sys,
            "argv",
            ["leadgen.py", "--objective", "either", "--require-phone", "--require-email"],
        ):
            args = LEADGEN.parse_args()
        with patch.object(LEADGEN, "config_from_saved_settings", return_value=LEADGEN.LeadgenConfig()):
            config = LEADGEN.config_from_args(args)
        self.assertEqual(config.objective, "either")

    def test_cli_legacy_flags_normalize_to_both(self):
        with patch.object(sys, "argv", ["leadgen.py", "--require-phone", "--require-email"]):
            args = LEADGEN.parse_args()
        with patch.object(LEADGEN, "config_from_saved_settings", return_value=LEADGEN.LeadgenConfig()):
            config = LEADGEN.config_from_args(args)
        self.assertEqual(config.objective, "both")


@SKIP
class TestLeadgenTypeConfig(unittest.TestCase):
    def test_default_is_api_manager(self):
        cfg = LEADGEN.LeadgenConfig()
        self.assertEqual(cfg.leadgen_type, "api_manager")
        self.assertEqual(cfg.playwright_max_pages, 20)
        self.assertEqual(cfg.playwright_max_results_per_search, 400)
        self.assertEqual(cfg.playwright_area_expansion, "off")

    def test_settings_round_trip_leadgen_type(self):
        cfg = LEADGEN.LeadgenConfig(
            leadgen_type="playwright",
            playwright_max_pages=7,
            playwright_max_results_per_search=50,
            playwright_area_expansion="dense",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadgen_settings.json"
            payload = LEADGEN.save_settings(cfg, path=path)
            self.assertEqual(payload["leadgen_type"], "playwright")
            self.assertEqual(payload["playwright_max_pages"], 7)
            self.assertEqual(payload["playwright_area_expansion"], "dense")
            rebuilt = LEADGEN.config_from_saved_settings(path=path)
            self.assertEqual(rebuilt.leadgen_type, "playwright")
            self.assertEqual(rebuilt.playwright_max_pages, 7)
            self.assertEqual(rebuilt.playwright_max_results_per_search, 50)
            self.assertEqual(rebuilt.playwright_area_expansion, "dense")

    def test_legacy_settings_keep_api_manager_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadgen_settings.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"min_score": 70}, f)
            rebuilt = LEADGEN.config_from_saved_settings(path=path)
            self.assertEqual(rebuilt.leadgen_type, "api_manager")

    def test_cli_leadgen_type_playwright(self):
        with patch.object(
            sys,
            "argv",
            [
                "leadgen.py",
                "--leadgen-type",
                "playwright",
                "--playwright-max-pages",
                "5",
                "--playwright-max-results-per-search",
                "40",
                "--playwright-area-expansion",
                "light",
            ],
        ):
            args = LEADGEN.parse_args()
        self.assertTrue(LEADGEN._has_cli_overrides(args))
        with patch.object(LEADGEN, "config_from_saved_settings", return_value=LEADGEN.LeadgenConfig()):
            config = LEADGEN.config_from_args(args)
        self.assertEqual(config.leadgen_type, "playwright")
        self.assertEqual(config.playwright_max_pages, 5)
        self.assertEqual(config.playwright_max_results_per_search, 40)
        self.assertEqual(config.playwright_area_expansion, "light")

    def test_normalize_leadgen_type_rejects_unknown(self):
        self.assertEqual(LEADGEN.normalize_leadgen_type("nope"), "api_manager")
        self.assertEqual(LEADGEN.normalize_leadgen_type("Playwright"), "playwright")


@SKIP
class TestPlaywrightDiscoveryHelpers(unittest.TestCase):
    def test_extract_place_id_prefers_chij(self):
        from playwright_discovery import extract_place_id_from_url, dedupe_businesses

        url = (
            "https://www.google.com/maps/place/TrueLine+Roofing/data=!4m7!3m6!"
            "1s0x89c6c91835a39afb:0x1b0b7cb83bb89836!19sChIJ-5qjNRjJxokRNpi4O7h8Cxs"
        )
        self.assertEqual(extract_place_id_from_url(url), "ChIJ-5qjNRjJxokRNpi4O7h8Cxs")

        businesses = [
            {"place_id": "ChIJ1", "business_name": "A", "address": "1 Main"},
            {"place_id": "ChIJ1", "business_name": "A Dup", "address": "1 Main"},
            {
                "business_name": "B Plumbing",
                "phone_google": "(856) 555-1212",
                "address": "2 Oak",
            },
            {
                "business_name": "B Plumbing",
                "phone_google": "856-555-1212",
                "address": "Different",
            },
        ]
        unique, removed = dedupe_businesses(businesses)
        self.assertEqual(removed, 2)
        self.assertEqual(len(unique), 2)

    def test_process_businesses_skips_place_details_when_disabled(self):
        businesses = [
            {
                "business_name": "Local Roofing",
                "place_id": "ChIJtest123",
                "address": "1 Main St, Camden, NJ",
                "phone_google": "(856) 555-0100",
                "website": None,
                "rating": 4.2,
                "user_ratings_total": 12,
                "niche_key": "roofing",
                "source": "playwright",
            }
        ]
        with patch.object(LEADGEN, "get_place_details") as mock_details, \
                patch.object(LEADGEN, "analyze_website") as mock_analyze:
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
            rows = LEADGEN.process_businesses(
                businesses,
                api_key="unused",
                existing_ids=set(),
                contacted_emails=set(),
                min_score=0,
                min_reviews=0,
                objective="phone",
                fetch_details=False,
                existing_identities=set(),
                source="playwright",
            )
        mock_details.assert_not_called()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "playwright")
        self.assertEqual(rows[0]["business_name"], "Local Roofing")

    def test_parse_card_fields_and_area_expansion(self):
        from playwright_discovery import (
            expansion_points,
            parse_card_fields,
            area_search_multiplier,
        )

        fields = parse_card_fields(
            "Cherry Hill Plumbing\n4.7\nPlumber · 935 Cropwell Rd\n"
            "Open · (856) 424-9670\nWebsite",
            extra={
                "website": "http://cherryhillplumbing.com/",
                "ratingText": "4.7",
                "reviewsText": "(51)",
            },
        )
        self.assertEqual(fields["phone_google"], "(856) 424-9670")
        self.assertEqual(fields["website"], "http://cherryhillplumbing.com/")
        self.assertEqual(fields["rating"], 4.7)
        self.assertEqual(fields["user_ratings_total"], 51)
        self.assertEqual(fields["category"], "Plumber")
        self.assertIn("935 Cropwell", fields["address"])

        self.assertEqual(expansion_points("39.95,-75.16", "off"), [])
        light = expansion_points("39.95,-75.16", "light")
        self.assertEqual(len(light), 4)
        dense = expansion_points((39.95, -75.16), "dense")
        self.assertEqual(len(dense), 8)
        self.assertEqual(area_search_multiplier("light"), 5)
        self.assertEqual(area_search_multiplier("dense"), 9)

    def test_listing_needs_detail_and_high_volume_preset(self):
        card = {
            "business_name": "Local Plumbing",
            "phone_google": "(856) 555-0100",
            "website": "https://local.example",
            "rating": 4.6,
        }
        cfg = LEADGEN.LeadgenConfig(objective="phone", min_reviews=0)
        self.assertFalse(LEADGEN.listing_needs_detail(card, cfg))
        self.assertTrue(
            LEADGEN.listing_needs_detail({"business_name": "No Phone"}, cfg)
        )
        cfg_reviews = LEADGEN.LeadgenConfig(objective="phone", min_reviews=5)
        self.assertTrue(LEADGEN.listing_needs_detail(card, cfg_reviews))

        preset = LEADGEN.apply_high_volume_preset(LEADGEN.LeadgenConfig())
        self.assertEqual(preset.leadgen_type, "playwright")
        self.assertEqual(preset.playwright_area_expansion, "light")
        self.assertGreaterEqual(preset.playwright_max_pages, 20)
        self.assertFalse(preset.lead_enrichment)
        self.assertEqual(preset.min_reviews, 0)

        volume = LEADGEN.estimate_discovery_volume(
            LEADGEN.LeadgenConfig(
                leadgen_type="playwright",
                playwright_area_expansion="light",
                keywords=["plumbing", "hvac"],
                locations=[
                    ("NJ", "Cherry Hill", "39.9,-75.1"),
                    ("PA", "Philadelphia", "39.9,-75.1"),
                ],
            )
        )
        self.assertEqual(volume["searches"], 2 * 2 * 5)
        self.assertGreaterEqual(volume["unique_high"], 100)

    def test_keyword_groups_cover_catalog(self):
        missing = [
            kw
            for kw in LEADGEN.KEYWORD_CATEGORIES
            if LEADGEN.keyword_group_for(kw) == "other"
            and kw not in LEADGEN.KEYWORD_GROUPS["other"]
        ]
        self.assertEqual(missing, [])

    def test_cli_state_filter(self):
        with patch.object(sys, "argv", ["leadgen.py", "--state", "NJ", "--city", "Cherry Hill"]):
            args = LEADGEN.parse_args()
        with patch.object(LEADGEN, "config_from_saved_settings", return_value=LEADGEN.LeadgenConfig()):
            config = LEADGEN.config_from_args(args)
        self.assertEqual(len(config.locations), 1)
        self.assertEqual(config.locations[0][1], "Cherry Hill")


@SKIP
class TestSearchHistory(unittest.TestCase):
    def test_make_search_key_and_skip(self):
        from search_history import SearchHistory, make_search_key, update_usage_stats

        key = make_search_key("api_manager", "Roofing", "Camden", "nj", search_radius=50000)
        self.assertEqual(key, "api_manager|roofing|camden|NJ|radius:50000")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            history = SearchHistory(path)
            self.assertFalse(history.was_searched(key))
            history.record_search(
                leadgen_type="api_manager",
                keyword="Roofing",
                city="Camden",
                state="NJ",
                search_radius=50000,
                businesses_found=12,
            )
            history.save()
            reloaded = SearchHistory(path)
            self.assertTrue(reloaded.was_searched(key))
            pending, skipped = reloaded.pending_keywords_for_location(
                ["Roofing", "plumbing"],
                "Camden",
                "NJ",
                leadgen_type="api_manager",
                search_radius=50000,
                skip_searched=True,
            )
            self.assertEqual(pending, ["plumbing"])
            self.assertEqual(len(skipped), 1)
            usage_path = Path(tmp) / "usage.json"
            data = update_usage_stats(
                usage_path,
                nearby_calls=2,
                details_calls=5,
            )
            self.assertEqual(data["nearby_calls"], 2)
            self.assertEqual(data["details_calls"], 5)
            self.assertEqual(data["total_calls"], 7)
            self.assertEqual(data["runs"], 1)

    def test_playwright_search_key_includes_expansion(self):
        from search_history import make_search_key

        key = make_search_key(
            "playwright",
            "plumbing",
            "Cherry Hill",
            "nj",
            playwright_max_pages=20,
            playwright_area_expansion="light",
        )
        self.assertEqual(
            key, "playwright|plumbing|cherry hill|NJ|pages:20|expand:light"
        )
        off_key = make_search_key(
            "playwright",
            "plumbing",
            "Cherry Hill",
            "NJ",
            playwright_max_pages=20,
        )
        self.assertEqual(off_key, "playwright|plumbing|cherry hill|NJ|pages:20")

    def test_cli_force_research(self):
        with patch.object(sys, "argv", ["leadgen.py", "--force-research"]):
            args = LEADGEN.parse_args()
        self.assertFalse(args.skip_searched)
        self.assertTrue(LEADGEN._has_cli_overrides(args))
        with patch.object(LEADGEN, "config_from_saved_settings", return_value=LEADGEN.LeadgenConfig()):
            config = LEADGEN.config_from_args(args)
        self.assertFalse(config.skip_searched)

    def test_log_stage_helpers_exist(self):
        self.assertTrue(callable(LEADGEN.log_stage))
        self.assertTrue(callable(LEADGEN.log_step))


if __name__ == "__main__":
    unittest.main()
