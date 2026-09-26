"""
Unit tests for scripts/lead_automation/leadenrich_playwright.py

Run from repo root:
    python -m unittest unittests.lead_automation.test_leadenrich_playwright
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"


def _import_module():
    _prev = os.getcwd()
    try:
        os.chdir(_LEADGEN_DIR)
        if str(_LEADGEN_DIR) not in sys.path:
            sys.path.insert(0, str(_LEADGEN_DIR))
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        if "leadenrich_playwright" in sys.modules:
            return importlib.reload(sys.modules["leadenrich_playwright"])
        return importlib.import_module("leadenrich_playwright")
    finally:
        os.chdir(_prev)


def _get_module_or_skip():
    try:
        return _import_module(), None
    except Exception as e:
        return None, e


MOD, _IMPORT_ERR = _get_module_or_skip()
SKIP = unittest.skipIf(
    MOD is None,
    f"leadenrich_playwright import failed (install project deps): {_IMPORT_ERR!r}",
)


def _lead(**overrides):
    base = {
        "business_name": "Acme Plumbing Co.",
        "place_id": "pid1",
        "address": "123 Maple Ave, Cherry Hill, NJ 08002, USA",
        "phone_google": "(856) 555-0142",
        "email": "",
        "has_email": False,
        "website": "",
        "lead_score": 82,
        "niche_key": "plumbing",
    }
    base.update(overrides)
    return base


class FakeSession:
    def __init__(self, results=None, blocked=False):
        self.google_blocked = blocked
        self.results = results if results is not None else []
        self.searches = []
        self.closed = False

    def search(self, query):
        self.searches.append(query)
        if self.google_blocked:
            return []
        if callable(self.results):
            return self.results(query)
        return list(self.results)

    def close(self):
        self.closed = True

    def _ensure_browser(self):
        return None


GOOD_HTML = """
<html>
<head>
  <title>Acme Plumbing | Cherry Hill NJ</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Family-owned plumbing contractor serving Cherry Hill and the metro area with 24/7 repairs.">
  <link rel="canonical" href="https://acmeplumbing.example/">
  <meta property="og:title" content="Acme Plumbing">
  <meta property="og:description" content="Family-owned plumbing contractor serving Cherry Hill.">
  <script type="application/ld+json">{"@type":"LocalBusiness","name":"Acme Plumbing"}</script>
</head>
<body>
  <h1>Acme Plumbing Co.</h1>
  <p>Call us today for a quote or estimate. Contact the office at
     <a href="mailto:info@acmeplumbing.example">info@acmeplumbing.example</a>
     or (856) 555-0142.</p>
  <p>We handle drain cleaning, water heaters, and emergency repairs across Cherry Hill
     and the surrounding towns. Schedule service online or call the shop.
     Our team has been family owned for decades and we stand behind every job.
     Request a quote, book a visit, and get same-week availability whenever we can.
     We also publish service pages for each town we cover so neighbors can find us.</p>
  <img src="https://acmeplumbing.example/van.jpg" alt="Service van">
  <a href="https://www.facebook.com/acmeplumbing">Facebook</a>
</body>
</html>
"""

THIN_HTML = """
<html>
<head><title>x</title></head>
<body>
  <h1>One</h1>
  <h1>Two</h1>
  <img src="http://cdn.example/a.jpg">
</body>
</html>
"""


@SKIP
class TestSerpClassification(unittest.TestCase):
    def test_facebook_page_is_classified_and_scored(self):
        result = {
            "title": "Acme Plumbing Co.",
            "url": "https://www.facebook.com/acmeplumbing",
            "snippet": "Cherry Hill plumber",
        }
        item = MOD.classify_serp_result(result, _lead())
        self.assertEqual(item["kind"], "facebook")
        self.assertEqual(item["url"], "https://www.facebook.com/acmeplumbing")
        self.assertGreaterEqual(item["score"], 0.72)
        self.assertTrue(item["accepted"])

    def test_unrelated_facebook_is_not_accepted(self):
        result = {
            "title": "Dover Auto Body",
            "url": "https://www.facebook.com/doverautobody",
            "snippet": "",
        }
        item = MOD.classify_serp_result(result, _lead())
        self.assertEqual(item["kind"], "facebook")
        self.assertFalse(item["accepted"])

    def test_official_site_is_website(self):
        result = {
            "title": "Acme Plumbing Co.",
            "url": "https://acmeplumbing.example/",
            "snippet": "Official site",
        }
        item = MOD.classify_serp_result(result, _lead())
        self.assertEqual(item["kind"], "website")

    def test_yelp_is_directory_not_website(self):
        result = {
            "title": "Acme Plumbing",
            "url": "https://www.yelp.com/biz/acme-plumbing",
            "snippet": "",
        }
        item = MOD.classify_serp_result(result, _lead())
        self.assertEqual(item["kind"], "directory")
        self.assertEqual(item["label"], "yelp")

    def test_pick_facebook_requires_similarity(self):
        classified = MOD.classify_serp_results(
            [
                {"title": "Dover Auto Body", "url": "https://www.facebook.com/dover"},
                {"title": "Acme Plumbing Co.", "url": "https://www.facebook.com/acmeplumbing"},
            ],
            _lead(),
        )
        url, score = MOD.pick_facebook_url(classified)
        self.assertEqual(url, "https://www.facebook.com/acmeplumbing")
        self.assertGreaterEqual(score, 0.72)

    def test_pick_website_skips_directories(self):
        classified = MOD.classify_serp_results(
            [
                {"title": "Acme", "url": "https://www.yelp.com/biz/acme"},
                {"title": "Acme Plumbing Co.", "url": "https://acmeplumbing.example/"},
            ],
            _lead(),
        )
        self.assertEqual(
            MOD.pick_website_url(classified, _lead()),
            "https://acmeplumbing.example/",
        )

    def test_known_website_wins(self):
        lead = _lead(website="https://known.example")
        self.assertEqual(MOD.pick_website_url([], lead), "https://known.example")

    def test_empty_result_is_none(self):
        self.assertIsNone(MOD.classify_serp_result({"url": ""}, _lead()))


@SKIP
class TestResearchQueries(unittest.TestCase):
    def test_includes_location_facebook_and_website(self):
        queries = MOD.build_research_queries(_lead())
        blob = " ".join(queries).lower()
        self.assertTrue(queries)
        self.assertIn("acme plumbing", blob)
        self.assertIn("facebook", blob)
        self.assertIn("website", blob)
        self.assertIn("cherry hill", blob)

    def test_name_only_when_address_missing(self):
        queries = MOD.build_research_queries(_lead(address=""))
        self.assertTrue(any("facebook" in q.lower() for q in queries))

    def test_empty_name_returns_no_queries(self):
        self.assertEqual(MOD.build_research_queries(_lead(business_name="")), [])


@SKIP
class TestSeoAudit(unittest.TestCase):
    def test_healthy_page_scores_low(self):
        out = MOD.analyze_seo(GOOD_HTML, "https://acmeplumbing.example/")
        self.assertLess(out["score"], 20)
        self.assertTrue(out["https"])
        self.assertIn("Acme Plumbing", out["title"])

    def test_thin_http_page_flags_improvements(self):
        out = MOD.analyze_seo(THIN_HTML, "http://thin.example/")
        self.assertGreaterEqual(out["score"], 40)
        joined = " ".join(out["issues"]).lower()
        self.assertIn("https", joined)
        self.assertIn("viewport", joined)
        self.assertIn("h1", joined)
        self.assertTrue(out["recommendations"])

    def test_load_error_is_max_opportunity(self):
        out = MOD.analyze_seo("", "https://down.example/", load_error="timeout")
        self.assertEqual(out["score"], 100)
        self.assertTrue(out["issues"])

    def test_extract_social_links_finds_facebook(self):
        links = MOD.extract_social_links(GOOD_HTML, "https://acmeplumbing.example/")
        self.assertEqual(links["facebook"], "https://www.facebook.com/acmeplumbing")


@SKIP
class TestCrmMapping(unittest.TestCase):
    def test_crm_lead_to_row_maps_fields(self):
        row = MOD.crm_lead_to_row({
            "id": "uuid-1",
            "business_name": "Acme Plumbing Co.",
            "phone": "+1-555-123-4567",
            "email": None,
            "website": "https://acmeplumbing.com",
            "score": 82,
            "source_group_name": "Plumbers",
            "business_status": "OPERATIONAL",
            "tags": ["high-priority"],
            "notes": "Call after 4pm.",
        })
        self.assertEqual(row["crm_id"], "uuid-1")
        self.assertEqual(row["phone_google"], "+1-555-123-4567")
        self.assertEqual(row["email"], "")
        self.assertFalse(row["has_email"])
        self.assertEqual(row["website"], "https://acmeplumbing.com")
        self.assertEqual(row["lead_score"], 82)
        self.assertEqual(row["niche_key"], "Plumbers")
        self.assertEqual(row["source"], "crm_pipeline")

    def test_crm_lead_to_row_ignores_non_dict(self):
        self.assertEqual(MOD.crm_lead_to_row(None), {})

    def test_export_body_includes_filters(self):
        cfg = MOD.EnrichConfig(
            crm_status=["New Lead"],
            category="Plumbers",
            has_phone=True,
            missing_email=True,
            min_score=50,
            max_score=100,
            search="acme",
            since="2026-01-01",
        )
        body = MOD.build_crm_export_body(cfg, limit=500, offset=0)
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["status"], ["New Lead"])
        self.assertEqual(body["category"], "Plumbers")
        self.assertTrue(body["has_phone"])
        self.assertTrue(body["missing_email"])
        self.assertEqual(body["min_score"], 50)
        self.assertEqual(body["search"], "acme")
        self.assertEqual(body["offset"], 0)

    def test_fetch_crm_leads_paginates(self):
        page1 = {
            "success": True,
            "count": 1,
            "total": 2,
            "leads": [{"id": "a", "business_name": "A", "email": None, "score": 80}],
        }
        page2 = {
            "success": True,
            "count": 1,
            "total": 2,
            "leads": [{"id": "b", "business_name": "B", "email": None, "score": 70}],
        }
        mock_api = MagicMock()
        mock_api.return_value.build_request.side_effect = [page1, page2]
        cfg = MOD.EnrichConfig(from_crm=True, crm_page_size=1)
        rows = MOD.fetch_crm_leads(cfg, api_cls=mock_api)
        self.assertEqual([row["crm_id"] for row in rows], ["a", "b"])
        self.assertEqual(mock_api.return_value.build_request.call_count, 2)
        first_body = mock_api.return_value.build_request.call_args_list[0].kwargs["json_body"]
        self.assertEqual(first_body["offset"], 0)
        self.assertEqual(
            mock_api.return_value.build_request.call_args_list[0].kwargs["endpoint"],
            "/crm-leads-export",
        )

    def test_fetch_crm_leads_respects_limit(self):
        page = {
            "total": 50,
            "leads": [{"id": str(i), "business_name": f"Biz {i}"} for i in range(3)],
        }
        mock_api = MagicMock()
        mock_api.return_value.build_request.return_value = page
        cfg = MOD.EnrichConfig(limit=2, crm_page_size=10)
        rows = MOD.fetch_crm_leads(cfg, api_cls=mock_api)
        self.assertEqual(len(rows), 2)


@SKIP
class TestCandidateSelection(unittest.TestCase):
    def test_unchecked_lead_is_selected(self):
        self.assertTrue(MOD.needs_enrichment(_lead()))

    def test_facebook_enriched_lead_still_needs_playwright(self):
        lead = _lead(enrichment={"source": "facebook", "status": "enriched"})
        self.assertTrue(MOD.needs_enrichment(lead))

    def test_completed_playwright_research_is_skipped(self):
        lead = _lead(enrichment={"source": "playwright_google", "status": MOD.STATUS_RESEARCHED})
        self.assertFalse(MOD.needs_enrichment(lead))

    def test_failed_scrape_is_retried(self):
        lead = _lead(enrichment={"source": "playwright_google", "status": MOD.STATUS_SCRAPE_FAILED})
        self.assertTrue(MOD.needs_enrichment(lead))

    def test_retry_all_reselects(self):
        lead = _lead(enrichment={"source": "playwright_google", "status": MOD.STATUS_NO_MATCH})
        self.assertTrue(MOD.needs_enrichment(lead, retry_all=True))


@SKIP
class TestApplyResearch(unittest.TestCase):
    def test_email_sets_enriched_status(self):
        lead = _lead()
        status = MOD.apply_research(lead, {
            "website": "https://acmeplumbing.example/",
            "facebook_url": "https://www.facebook.com/acmeplumbing",
            "email": "info@acmeplumbing.example",
            "phones": ["(+1) 856-555-0142"],
            "seo": {"score": 12, "issues": [], "recommendations": []},
            "url_source": "search",
        })
        self.assertEqual(status, MOD.STATUS_ENRICHED)
        self.assertEqual(lead["email"], "info@acmeplumbing.example")
        self.assertTrue(lead["has_email"])
        self.assertEqual(lead["facebook_url"], "https://www.facebook.com/acmeplumbing")
        self.assertEqual(lead["enrichment"]["source"], "playwright_google")

    def test_site_without_email_is_researched(self):
        lead = _lead()
        status = MOD.apply_research(lead, {
            "website": "https://acmeplumbing.example/",
            "seo": {"score": 40, "issues": ["thin"], "recommendations": ["add copy"]},
        })
        self.assertEqual(status, MOD.STATUS_RESEARCHED)
        self.assertEqual(lead["email"], "")
        self.assertEqual(lead["seo"]["score"], 40)

    def test_no_match_when_nothing_found(self):
        lead = _lead()
        status = MOD.apply_research(lead, {"load_error": "no website or facebook match"})
        self.assertEqual(status, MOD.STATUS_NO_MATCH)

    def test_failed_flag_is_retryable(self):
        lead = _lead()
        status = MOD.apply_research(lead, {"failed": True, "load_error": "boom"})
        self.assertEqual(status, MOD.STATUS_SCRAPE_FAILED)
        self.assertIn(status, MOD.RETRYABLE_STATUSES)


@SKIP
class TestEnrichLeads(unittest.TestCase):
    def test_enriches_rows_in_place_with_mocked_search_and_visit(self):
        rows = [
            _lead(),
            _lead(
                place_id="pid2",
                email="known@biz.example",
                has_email=True,
                enrichment={"source": "playwright_google", "status": "researched"},
            ),
        ]
        session = FakeSession(results=[
            {"title": "Acme Plumbing Co.", "url": "https://acmeplumbing.example/", "snippet": ""},
            {"title": "Acme Plumbing Co.", "url": "https://www.facebook.com/acmeplumbing", "snippet": ""},
        ])
        visit = {
            "url": "https://acmeplumbing.example/",
            "final_url": "https://acmeplumbing.example/",
            "html": GOOD_HTML,
            "title": "Acme Plumbing | Cherry Hill NJ",
            "emails": ["info@acmeplumbing.example"],
            "phones": ["(+1) 856-555-0142"],
            "social": {"facebook": "https://www.facebook.com/acmeplumbing"},
            "error": None,
            "via": "playwright",
        }
        with patch.object(MOD, "visit_website", return_value=visit):
            processed = MOD.enrich_leads(rows, MOD.EnrichConfig(max_queries=2), session=session)

        self.assertEqual(processed, [rows[0]])
        self.assertEqual(rows[0]["email"], "info@acmeplumbing.example")
        self.assertEqual(rows[0]["facebook_url"], "https://www.facebook.com/acmeplumbing")
        self.assertIn("seo", rows[0])
        self.assertEqual(rows[0]["enrichment"]["status"], MOD.STATUS_ENRICHED)
        self.assertTrue(session.searches)
        self.assertFalse(session.closed)
        self.assertEqual(rows[1]["email"], "known@biz.example")
        self.assertEqual(rows[1]["enrichment"]["status"], "researched")

    def test_dry_run_does_not_mutate_or_visit(self):
        rows = [_lead()]
        session = FakeSession(results=[
            {"title": "Acme Plumbing Co.", "url": "https://acmeplumbing.example/", "snippet": ""},
        ])
        with patch.object(MOD, "visit_website") as mock_visit:
            processed = MOD.enrich_leads(
                rows,
                MOD.EnrichConfig(dry_run=True, max_queries=1),
                session=session,
            )
        self.assertEqual(processed, [])
        mock_visit.assert_not_called()
        self.assertNotIn("enrichment", rows[0])
        self.assertTrue(session.searches)

    def test_no_candidates_skips_search(self):
        rows = [_lead(enrichment={"source": "playwright_google", "status": MOD.STATUS_RESEARCHED})]
        session = FakeSession(results=[{"url": "https://x.example"}])
        processed = MOD.enrich_leads(rows, session=session)
        self.assertEqual(processed, [])
        self.assertEqual(session.searches, [])

    def test_visit_failure_records_research(self):
        rows = [_lead(website="https://down.example")]
        session = FakeSession(results=[])
        visit = {
            "url": "https://down.example",
            "final_url": "https://down.example",
            "html": "",
            "title": "",
            "emails": [],
            "phones": [],
            "social": {},
            "error": "timeout",
            "via": "playwright",
        }
        with patch.object(MOD, "visit_website", return_value=visit):
            processed = MOD.enrich_leads(rows, MOD.EnrichConfig(max_queries=1), session=session)
        self.assertEqual(processed[0]["enrichment"]["status"], MOD.STATUS_RESEARCHED)
        self.assertEqual(processed[0]["seo"]["score"], 100)


@SKIP
class TestRunEnrichment(unittest.TestCase):
    def _write_leads(self, tmp, leads):
        path = os.path.join(tmp, "leads_output.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(leads, f)
        return path

    def test_from_crm_requires_ingest_key(self):
        env = {k: v for k, v in os.environ.items() if k != "LEAD_INGEST_KEY"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(MOD, "fetch_crm_leads") as mock_fetch:
            MOD.run_enrichment(MOD.EnrichConfig(from_crm=True))
        mock_fetch.assert_not_called()

    def test_from_crm_saves_mapped_rows(self):
        crm_rows = [MOD.crm_lead_to_row({
            "id": "uuid-1",
            "business_name": "Acme Plumbing Co.",
            "email": None,
            "website": "https://acmeplumbing.example/",
            "score": 82,
        })]
        visit = {
            "url": "https://acmeplumbing.example/",
            "final_url": "https://acmeplumbing.example/",
            "html": GOOD_HTML,
            "title": "Acme",
            "emails": ["info@acmeplumbing.example"],
            "phones": [],
            "social": {},
            "error": None,
            "via": "playwright",
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "enriched.json")
            session = FakeSession(results=[
                {"title": "Acme Plumbing Co.", "url": "https://acmeplumbing.example/", "snippet": ""},
            ])
            with patch.dict(os.environ, {"LEAD_INGEST_KEY": "fake-key"}), \
                    patch.object(MOD, "fetch_crm_leads", return_value=crm_rows), \
                    patch.object(MOD, "EmailDiscoverySession", return_value=session), \
                    patch.object(MOD, "visit_website", return_value=visit):
                MOD.run_enrichment(MOD.EnrichConfig(
                    from_crm=True,
                    json_path=out,
                    output_path=out,
                    max_queries=1,
                ))
            with open(out, encoding="utf-8") as f:
                saved = json.load(f)
        self.assertEqual(saved[0]["email"], "info@acmeplumbing.example")
        self.assertEqual(saved[0]["crm_id"], "uuid-1")

    def test_dashboard_receives_newly_emailed_leads(self):
        leads = [_lead(website="https://acmeplumbing.example/")]
        visit = {
            "url": "https://acmeplumbing.example/",
            "final_url": "https://acmeplumbing.example/",
            "html": GOOD_HTML,
            "title": "Acme",
            "emails": ["info@acmeplumbing.example"],
            "phones": [],
            "social": {},
            "error": None,
            "via": "playwright",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_leads(tmp, leads)
            session = FakeSession(results=[])
            with patch.dict(os.environ, {"LEAD_INGEST_KEY": "fake-key"}), \
                    patch.object(MOD, "EmailDiscoverySession", return_value=session), \
                    patch.object(MOD, "visit_website", return_value=visit), \
                    patch("leadgen.send_to_dashboard") as mock_dashboard:
                MOD.run_enrichment(MOD.EnrichConfig(
                    json_path=path,
                    dashboard=True,
                    max_queries=1,
                ))
        mock_dashboard.assert_called_once()
        sent = mock_dashboard.call_args.args[0]
        self.assertEqual(sent[0]["email"], "info@acmeplumbing.example")


@SKIP
class TestCliConfig(unittest.TestCase):
    def test_from_crm_flags_map_to_config(self):
        with patch.object(sys, "argv", [
            "leadenrich_playwright.py",
            "--from-crm",
            "--status", "New Lead",
            "--category", "Plumbers",
            "--limit", "10",
            "--dry-run",
        ]):
            cfg = MOD.config_from_args(MOD.parse_args())
        self.assertTrue(cfg.from_crm)
        self.assertEqual(cfg.crm_status, ["New Lead"])
        self.assertEqual(cfg.category, "Plumbers")
        self.assertEqual(cfg.limit, 10)
        self.assertTrue(cfg.dry_run)
        self.assertTrue(cfg.missing_email)


if __name__ == "__main__":
    unittest.main()
