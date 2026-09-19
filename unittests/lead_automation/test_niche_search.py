"""
Unit tests for niche lead search.

Run from repo root:
    python -m unittest unittests.lead_automation.test_niche_search
"""
import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"


def _import_modules():
    prev = os.getcwd()
    try:
        os.chdir(_LEADGEN_DIR)
        if str(_LEADGEN_DIR) not in sys.path:
            sys.path.insert(0, str(_LEADGEN_DIR))
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        names = (
            "niche_config",
            "intent_scoring",
            "lead_signals",
            "website_quality",
            "social_activity",
            "outreach_angle",
            "niche_search",
            "niche_results",
            "leadgen",
        )
        loaded = {}
        for name in names:
            if name in sys.modules:
                loaded[name] = importlib.reload(sys.modules[name])
            else:
                loaded[name] = importlib.import_module(name)
        return loaded
    finally:
        os.chdir(prev)


def _load_or_skip():
    try:
        return _import_modules(), None
    except Exception as exc:
        return None, exc


MODULES, _IMPORT_ERR = _load_or_skip()
SKIP = unittest.skipIf(
    MODULES is None,
    f"niche search import failed: {_IMPORT_ERR!r}",
)


def _now():
    return datetime(2026, 6, 1, tzinfo=timezone.utc)


def _fixture(name, **overrides):
    """Representative leads used by scoring / filter tests."""
    bases = {
        "no_website_high_reviews_active_social": {
            "business_name": "ABC Dog Training",
            "website": "",
            "website_status": "none",
            "website_issues": ["no_website"],
            "website_quality_score": 100,
            "user_ratings_total": 46,
            "rating": 4.9,
            "business_status": "OPERATIONAL",
            "phone_google": "(856) 555-0101",
            "instagram_url": "https://instagram.com/abcdogs",
            "social_posts": [{"platform": "instagram", "date": "2026-05-20"}],
            "address": "10 Main St, Cherry Hill, NJ 08002",
            "search_term": "reactive dog trainer",
        },
        "strong_website_high_reviews": {
            "business_name": "Prime Detail Studio",
            "website": "https://primedetail.example",
            "website_status": "ok",
            "website_quality_score": 18,
            "website_issues": [],
            "website_analysis": {
                "https": True,
                "has_booking": True,
                "has_viewport": True,
                "has_contact_form": True,
                "has_click_to_call": True,
                "specialty_pages": True,
                "last_updated": "2024-01-01",
            },
            "user_ratings_total": 90,
            "rating": 4.9,
            "business_status": "OPERATIONAL",
            "phone_google": "(215) 555-0102",
            "email": "hello@primedetail.example",
        },
        "broken_website": {
            "business_name": "Harbor Notary",
            "website": "https://harbor-notary.example",
            "website_status": "http_500",
            "website_issues": ["broken"],
            "website_quality_score": 90,
            "user_ratings_total": 31,
            "rating": 4.8,
            "business_status": "OPERATIONAL",
            "phone_google": "(609) 555-0103",
            "search_term": "mobile notary",
        },
        "social_only": {
            "business_name": "Joy Doula",
            "website": "https://instagram.com/joydoula",
            "website_status": "social_or_directory",
            "website_issues": ["no_website"],
            "website_quality_score": 100,
            "instagram_url": "https://instagram.com/joydoula",
            "social_posts": [{"platform": "instagram", "date": "2026-05-28"}],
            "user_ratings_total": 12,
            "rating": 5.0,
            "business_status": "OPERATIONAL",
        },
        "franchise": {
            "business_name": "Petco Dog Training",
            "website": "https://www.petco.com/training",
            "website_status": "ok",
            "website_quality_score": 25,
            "is_franchise": True,
            "user_ratings_total": 200,
            "rating": 4.2,
            "business_status": "OPERATIONAL",
        },
        "low_demand": {
            "business_name": "Quiet Lessons",
            "website": "",
            "website_status": "none",
            "website_issues": ["no_website"],
            "website_quality_score": 100,
            "user_ratings_total": 0,
            "rating": None,
            "business_status": None,
        },
        "high_value_specialty": {
            "business_name": "Reactive Reset Board and Train",
            "website": "https://weak-trainer.example",
            "website_status": "ok",
            "website_quality_score": 72,
            "website_issues": ["no_viewport", "no_mobile_cta", "no_conversion_path"],
            "website_analysis": {
                "https": True,
                "has_booking": False,
                "has_contact_form": False,
                "has_quote_form": False,
                "has_click_to_call": False,
                "has_viewport": False,
                "specialty_pages": False,
            },
            "user_ratings_total": 22,
            "rating": 4.8,
            "business_status": "OPERATIONAL",
            "phone_google": "(732) 555-0199",
            "search_term": "board and train",
            "service_area": "mobile service across Ocean and Monmouth counties",
        },
    }
    row = dict(bases[name])
    row.update(overrides)
    return row


@SKIP
class TestNicheConfig(unittest.TestCase):
    def test_loads_twenty_niches(self):
        niches = MODULES["niche_config"].load_niches()
        self.assertEqual(len(niches), 20)
        self.assertIn("specialty_dog_trainers", niches)
        self.assertTrue(all(item.get("high_pri_lead") for item in niches.values()))

    def test_query_generation_is_unique_and_stable(self):
        cfg = MODULES["niche_config"]
        niche = cfg.get_niche("specialty_dog_trainers")
        first = cfg.build_search_queries(niche)
        second = cfg.build_search_queries(niche, extra_keywords=["dog trainer", "reactivity coaching"])
        self.assertIn("dog trainer", first)
        self.assertIn("board and train", first)
        self.assertEqual(first, cfg.build_search_queries(niche))
        self.assertEqual(len(second), len(set(item.lower() for item in second)))
        self.assertIn("reactivity coaching", second)

    def test_get_niche_by_display_name(self):
        niche = MODULES["niche_config"].get_niche("Specialty Dog Trainers")
        self.assertEqual(niche["id"], "specialty_dog_trainers")

    def test_negative_keywords(self):
        niche = MODULES["niche_config"].get_niche("specialty_dog_trainers")
        self.assertTrue(MODULES["niche_config"].matches_negative_keywords("Petco Training", niche))
        self.assertFalse(MODULES["niche_config"].matches_negative_keywords("ABC Dog Training", niche))


@SKIP
class TestDedupAndFranchise(unittest.TestCase):
    def test_dedupe_across_queries(self):
        entries = [
            {"business_name": "ABC", "place_id": "ChIJ1", "search_term": "dog trainer"},
            {"business_name": "ABC", "place_id": "ChIJ1", "search_term": "puppy trainer"},
            {"business_name": "XYZ", "place_id": "ChIJ2", "search_term": "dog trainer"},
        ]
        unique = MODULES["niche_search"].dedupe_discovered(entries)
        self.assertEqual(len(unique), 2)

    def test_franchise_detection(self):
        leadgen = MODULES["leadgen"]
        self.assertTrue(leadgen.is_franchise("Petco Dog Training", "https://local.example"))
        self.assertTrue(leadgen.is_franchise("Local Training", "https://www.petsmart.com/x"))
        self.assertFalse(leadgen.is_franchise("ABC Dog Training", "https://abcdogs.example"))


@SKIP
class TestWebsiteAndSocial(unittest.TestCase):
    def test_social_or_directory_is_not_a_website(self):
        check = MODULES["website_quality"].cheap_website_check("https://instagram.com/joydoula")
        self.assertTrue(check["no_website"])
        self.assertFalse(check["website_broken"])

    def test_broken_website_requires_failed_request(self):
        def boom(_url):
            raise RuntimeError("dns failed")

        check = MODULES["website_quality"].cheap_website_check(
            "https://down.example",
            fetch_fn=boom,
        )
        self.assertTrue(check["website_broken"])
        self.assertEqual(check["website_status"], "error")

    def test_website_classification_bands(self):
        quality = MODULES["website_quality"]
        strong_html = """
        <html><head><title>Prime Detail</title>
        <meta name="viewport" content="width=device-width">
        <meta name="description" content="Ceramic coating and paint correction">
        </head><body>
        <h1>Our Services</h1>
        <p>Ceramic coating, paint correction, and luxury detailing across the region.</p>
        <a href="tel:+15555550111">Call</a>
        <a href="/services">Services</a><a href="/about">About</a>
        <a href="/contact">Contact</a><a href="/blog">Blog</a>
        <form action="/quote">Get a quote</form>
        <script src="https://calendly.com/prime"></script>
        </body></html>
        """
        strong = quality.analyze_website_quality(
            "https://primedetail.example",
            html=strong_html,
            cheap={"url": "https://primedetail.example", "https": True, "reachable": True, "http_status": 200},
        )
        self.assertLessEqual(strong["website_quality_score"], 40)
        self.assertTrue(strong["has_booking"])

        poor_html = "<html><head><title>x</title></head><body>hi</body></html>"
        poor = quality.analyze_website_quality(
            "http://thin.example",
            html=poor_html,
            cheap={"url": "http://thin.example", "https": False, "reachable": True, "http_status": 200},
        )
        self.assertGreaterEqual(poor["website_quality_score"], 41)

    def test_social_url_only_is_not_active(self):
        result = MODULES["social_activity"].classify_social_activity(
            {"instagram_url": "https://instagram.com/abcdogs"},
            posts=[],
            now=_now(),
            rules=MODULES["niche_config"].load_score_rules(),
        )
        self.assertFalse(result["active_social"])
        self.assertEqual(result["social_activity_score"], 15)

    def test_social_active_requires_recent_post(self):
        result = MODULES["social_activity"].classify_social_activity(
            {"instagram_url": "https://instagram.com/abcdogs"},
            posts=[{"platform": "instagram", "date": (_now() - timedelta(days=5)).isoformat()}],
            now=_now(),
            rules=MODULES["niche_config"].load_score_rules(),
        )
        self.assertTrue(result["active_social"])


@SKIP
class TestIntentScoring(unittest.TestCase):
    def _score(self, fixture_name, niche_id="specialty_dog_trainers"):
        niche = MODULES["niche_config"].get_niche(niche_id)
        rules = MODULES["niche_config"].load_score_rules()
        lead = _fixture(fixture_name)
        MODULES["social_activity"].apply_social_fields(
            lead,
            MODULES["social_activity"].classify_social_activity(
                lead, posts=lead.get("social_posts"), now=_now(), rules=rules
            ),
        )
        return MODULES["intent_scoring"].score_intent_lead(lead, niche, rules=rules, now=_now()), lead

    def test_scores_are_deterministic(self):
        (score_a, breakdown_a), _lead_a = self._score("no_website_high_reviews_active_social")
        (score_b, breakdown_b), _lead_b = self._score("no_website_high_reviews_active_social")
        self.assertEqual(score_a, score_b)
        self.assertEqual(breakdown_a, breakdown_b)

    def test_no_website_high_reviews_active_social(self):
        (score, breakdown), lead = self._score("no_website_high_reviews_active_social")
        applied = {item["key"]: item["points"] for item in breakdown if item["applied"]}
        self.assertIn("no_website", applied)
        self.assertIn("review_count_band", applied)
        self.assertIn("active_social", applied)
        self.assertGreaterEqual(score, 55)
        tagged = MODULES["niche_search"].niche_tags(
            "api_manager",
            MODULES["niche_config"].get_niche("specialty_dog_trainers"),
        )
        self.assertIn("high-pri-lead", tagged)
        self.assertNotIn(
            "high-pri-lead",
            MODULES["niche_search"].niche_tags("api_manager", {"id": "other", "high_pri_lead": False}),
        )
        self.assertTrue(lead["lead_signals"]["no_website"])

    def test_strong_website_is_penalized(self):
        (score, breakdown), lead = self._score("strong_website_high_reviews", "premium_mobile_auto_detailers")
        applied = {item["key"] for item in breakdown if item["applied"]}
        self.assertIn("strong_website", applied)
        self.assertTrue(lead["lead_signals"]["strong_website"])
        self.assertLess(score, 70)

    def test_broken_website_scores_without_no_website(self):
        (score, breakdown), lead = self._score("broken_website", "mobile_notaries")
        applied = {item["key"] for item in breakdown if item["applied"]}
        self.assertIn("website_broken", applied)
        self.assertNotIn("no_website", applied)
        self.assertGreaterEqual(score, 25)

    def test_franchise_negative_scoring(self):
        (_score, breakdown), lead = self._score("franchise")
        applied = {item["key"]: item["points"] for item in breakdown if item["applied"]}
        self.assertEqual(applied.get("franchise"), -25)
        self.assertTrue(lead["lead_signals"]["franchise"])

    def test_low_demand_negative_scoring(self):
        (_score, breakdown), lead = self._score("low_demand", "specialty_music_teachers")
        applied = {item["key"] for item in breakdown if item["applied"]}
        self.assertIn("weak_demand", applied)
        self.assertTrue(lead["lead_signals"]["weak_demand"])

    def test_high_value_specialty_and_breakdown(self):
        (score, breakdown), lead = self._score("high_value_specialty")
        applied = {item["key"] for item in breakdown if item["applied"]}
        self.assertIn("high_value_service", applied)
        self.assertTrue(lead["lead_signals"]["high_value_service"])
        text = MODULES["intent_scoring"].format_score_breakdown(lead)
        self.assertIn(f"Lead Score: {score}", text)
        self.assertIn("High-value specialty", text)

    def test_social_only_business(self):
        (score, breakdown), lead = self._score("social_only", "birth_postpartum_doulas")
        applied = {item["key"] for item in breakdown if item["applied"]}
        self.assertIn("no_website", applied)
        self.assertIn("active_social", applied)
        self.assertTrue(lead["lead_signals"]["no_website"])
        self.assertGreaterEqual(score, 25)

    def test_outreach_angle_uses_evidence(self):
        niche = MODULES["niche_config"].get_niche("mobile_notaries")
        lead = _fixture("broken_website")
        MODULES["intent_scoring"].score_intent_lead(lead, niche, now=_now())
        angle = MODULES["outreach_angle"].generate_outreach_angle(lead, niche)
        self.assertNotIn("I noticed you don't have a website", angle)
        self.assertIn("31 reviews", angle)


@SKIP
class TestFiltersExportAndIngest(unittest.TestCase):
    def _rows(self):
        niche = MODULES["niche_config"].get_niche("specialty_dog_trainers")
        rules = MODULES["niche_config"].load_score_rules()
        rows = []
        for name, niche_id in (
            ("no_website_high_reviews_active_social", "specialty_dog_trainers"),
            ("strong_website_high_reviews", "premium_mobile_auto_detailers"),
            ("broken_website", "mobile_notaries"),
            ("franchise", "specialty_dog_trainers"),
            ("high_value_specialty", "specialty_dog_trainers"),
            ("low_demand", "specialty_music_teachers"),
        ):
            lead = _fixture(name)
            lead["niche"] = MODULES["niche_config"].get_niche(niche_id)["display_name"]
            lead["tags"] = MODULES["niche_search"].niche_tags(
                "api_manager",
                MODULES["niche_config"].get_niche(niche_id),
            )
            lead["city"] = "Cherry Hill"
            lead["state"] = "NJ"
            lead["profile_url"] = "https://maps.google.com/?cid=1"
            MODULES["social_activity"].apply_social_fields(
                lead,
                MODULES["social_activity"].classify_social_activity(
                    lead, posts=lead.get("social_posts"), now=_now(), rules=rules
                ),
            )
            MODULES["intent_scoring"].score_intent_lead(
                lead,
                MODULES["niche_config"].get_niche(niche_id),
                rules=rules,
                now=_now(),
            )
            lead["outreach_angle"] = MODULES["outreach_angle"].generate_outreach_angle(lead, niche)
            rows.append(lead)
        return rows

    def test_filter_presets(self):
        results = MODULES["niche_results"]
        rows = self._rows()
        highest = results.apply_preset(rows, "highest_intent")
        self.assertTrue(all(int(row["lead_score"]) >= 70 for row in highest))
        no_web = results.apply_preset(rows, "no_website")
        self.assertTrue(all((row.get("lead_signals") or {}).get("no_website") for row in no_web))
        broken = results.apply_preset(rows, "broken_website")
        self.assertTrue(all(int(row.get("website_quality_score") or 0) >= 60 for row in broken))

    def test_csv_export_columns(self):
        results = MODULES["niche_results"]
        rows = self._rows()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads.csv"
            results.export_csv(rows, path)
            text = path.read_text(encoding="utf-8")
            header = text.splitlines()[0]
            for column in results.CSV_COLUMNS:
                self.assertIn(column, header)
            self.assertIn("ABC Dog Training", text)

    def test_high_pri_tag_on_dashboard_payload(self):
        leadgen = MODULES["leadgen"]
        rows = [{
            "business_name": "ABC Dog Training",
            "address": "10 Main St, Cherry Hill, NJ 08002",
            "phone_google": "(856) 555-0101",
            "email": "a@example.com",
            "niche_key": "specialty_dog_trainers",
            "category": "dog-training-leads",
            "lead_score": 80,
            "source": "api_manager",
            "tags": MODULES["niche_search"].niche_tags(
                "api_manager",
                MODULES["niche_config"].get_niche("specialty_dog_trainers"),
            ),
        }]
        with patch("helper_scripts.api_manager.APIManager") as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api
            leadgen.send_to_dashboard(rows)
        payload = mock_api.build_request.call_args.kwargs["json_body"]
        self.assertIn("high-pri-lead", payload[0]["tags"])
        self.assertIn("lead_automation", payload[0]["tags"])
        self.assertEqual(payload[0]["category"], "dog-training-leads")

    def test_keyword_search_payload_omits_high_pri_without_row_tags(self):
        leadgen = MODULES["leadgen"]
        rows = [{
            "business_name": "Test Biz",
            "address": "123 Main St, Houston, TX 77001, USA",
            "phone_google": "555-1234",
            "email": "contact@test.com",
            "niche_key": "landscaping",
            "lead_score": 85,
        }]
        with patch("helper_scripts.api_manager.APIManager") as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api
            leadgen.send_to_dashboard(rows)
        payload = mock_api.build_request.call_args.kwargs["json_body"]
        self.assertEqual(
            payload[0]["tags"],
            ["lead_automation", "google-places-api"],
        )

    def test_run_niche_search_tags_and_filters(self):
        search = MODULES["niche_search"]
        niche = MODULES["niche_config"].get_niche("specialty_dog_trainers")

        def discover(_queries, _locations, _config):
            return [
                {
                    "business_name": "ABC Dog Training",
                    "place_id": "ChIJ-abc",
                    "address": "10 Main St, Cherry Hill, NJ 08002",
                    "phone_google": "(856) 555-0101",
                    "website": "",
                    "rating": 4.9,
                    "user_ratings_total": 46,
                    "business_status": "OPERATIONAL",
                    "search_term": "reactive dog trainer",
                    "location_searched": "Cherry Hill, NJ",
                    "source": "api_manager",
                },
                {
                    "business_name": "Petco Dog Training",
                    "place_id": "ChIJ-petco",
                    "address": "1 Chain Rd, Cherry Hill, NJ 08002",
                    "website": "https://www.petco.com/training",
                    "rating": 4.2,
                    "user_ratings_total": 200,
                    "business_status": "OPERATIONAL",
                    "search_term": "dog trainer",
                    "location_searched": "Cherry Hill, NJ",
                    "source": "api_manager",
                },
            ], 2

        config = search.NicheSearchConfig(
            niche_id="specialty_dog_trainers",
            locations=[("NJ", "Cherry Hill", "39.9,-75.1")],
            min_reviews=10,
            min_rating=4.5,
            min_score=55,
            filter_franchises=True,
            json_output=str(Path(tempfile.gettempdir()) / "niche_test_leads.json"),
            search_history_path=str(Path(tempfile.gettempdir()) / "niche_test_history.json"),
            output_mode="json",
            open_reviewer=False,
            skip_searched=False,
        )
        with patch.object(search, "cheap_website_check", return_value={
            "url": "",
            "no_website": True,
            "website_broken": False,
            "website_status": "none",
            "reachable": False,
        }), patch.object(search, "enrich_lead_with_email"), patch.object(
            search, "discover_api_manager", side_effect=AssertionError("live Places API must stay mocked")
        ), patch.object(
            search, "discover_playwright", side_effect=AssertionError("live Playwright must stay mocked")
        ), patch.object(
            MODULES["leadgen"], "save_results"
        ), patch.object(MODULES["leadgen"], "update_usage_stats"), patch(
            "search_history.SearchHistory.save"
        ), patch("search_history.SearchHistory.record_run"):
            rows, stats = search.run_niche_search(
                config,
                niches={"specialty_dog_trainers": niche},
                discover_fn=discover,
            )
        names = {row["business_name"] for row in rows}
        self.assertIn("ABC Dog Training", names)
        self.assertNotIn("Petco Dog Training", names)
        self.assertIn("high-pri-lead", rows[0]["tags"])
        self.assertEqual(rows[0]["score_model"], "intent_v1")
        self.assertGreaterEqual(stats["qualified_leads"], 1)
