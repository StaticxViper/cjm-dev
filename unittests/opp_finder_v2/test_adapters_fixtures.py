"""Fixture parses for the API, RSS, and Playwright adapters. No network."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from opp_finder_v2.adapters import fetch_site  # noqa: E402
from opp_finder_v2.browser.detection import classify_page  # noqa: E402
from opp_finder_v2.browser.session import BrowserSession  # noqa: E402
from opp_finder_v2.config import load_sites  # noqa: E402
from opp_finder_v2.listings import build_opportunity  # noqa: E402
from opp_finder_v2.models import Criteria, RunOptions, SearchQuery, SiteConfig  # noqa: E402

FIXTURES = ROOT / "scripts" / "opp_finder_v2" / "fixtures"
SCRAPED = datetime(2026, 10, 5, tzinfo=timezone.utc)


def loose_criteria() -> Criteria:
    return Criteria(
        keywords_any=["engineer", "developer", "python", "automation", "remote", "data"],
        keywords_all=[],
        title_boost=[],
        exclude_keywords=[],
        remote_only=False,
        employment_types=["contract", "freelance", "full_time", "part_time", "temporary", "internship"],
        location_allow=["us", "usa", "united states", "anywhere", "worldwide"],
        location_deny=[],
        location_unknown="keep",
        posted_within_days=None,
        min_rate_hourly=None,
        min_rate_annual=None,
        min_rate_unknown="keep",
        min_relevance=0,
        raw={},
    )


def dry_options() -> RunOptions:
    package = ROOT / "scripts" / "opp_finder_v2"
    return RunOptions(
        config_path=package / "sites.json",
        criteria_path=package / "criteria.json",
        dry_run=True,
        no_artifacts=True,
        format="json",
    )


class TestAdapterFixtures(unittest.TestCase):
    def test_enabled_adapters_parse_fixtures(self):
        catalog = load_sites()
        criteria = loose_criteria()
        options = dry_options()
        enabled = [site for site in catalog.sites if site.enabled]
        self.assertGreaterEqual(len(enabled), 1)
        for site in enabled:
            result = fetch_site(site, SearchQuery(criteria.keywords_any), criteria, options)
            self.assertEqual(result.status, "ok", site.id)
            self.assertGreaterEqual(len(result.listings), 1, site.id)
            kept = None
            for listing in result.listings:
                opp, reason = build_opportunity(listing, site, criteria, SCRAPED)
                if opp is not None and reason is None:
                    kept = opp
                    break
            self.assertIsNotNone(kept, site.id)
            self.assertTrue(kept.title)
            self.assertTrue(kept.url.startswith("http"))
            self.assertEqual(kept.source_site, site.id)
            self.assertEqual(len(kept.opp_id), 16)
            self.assertEqual(kept.relevance_score, sum(kept.score_breakdown.values()))

    def test_wwr_title_splits_company(self):
        catalog = load_sites()
        site = next(item for item in catalog.sites if item.id == "weworkremotely")
        result = fetch_site(site, SearchQuery(["python"]), loose_criteria(), dry_options())
        companies = {listing.company for listing in result.listings}
        self.assertIn("Sparix Global", companies)
        self.assertTrue(all(":" not in (listing.title or "")[:12] or listing.company for listing in result.listings))
        self.assertTrue(all(":" not in listing.title for listing in result.listings if listing.company))

    def test_detection_ignores_bare_blocked_and_flags_walls(self):
        normal = (FIXTURES / "sample_board" / "page.html").read_text(encoding="utf-8")
        self.assertIn("blocked", normal.lower())
        self.assertIsNone(classify_page("https://jobs.example/search", normal))
        captcha = (FIXTURES / "sample_board" / "captcha.html").read_text(encoding="utf-8")
        self.assertEqual(classify_page("https://jobs.example/search", captcha), "captcha")
        login = (FIXTURES / "sample_board" / "login.html").read_text(encoding="utf-8")
        self.assertEqual(classify_page("https://www.linkedin.com/login", login), "login_wall")
        long_page = "<html><head><title>Jobs</title></head><body>" + ("Sign in " * 5) + ("role description " * 80) + "</body></html>"
        self.assertIsNone(
            classify_page(
                "https://www.linkedin.com/jobs/search/",
                long_page,
                extra={"login_wall_text": ["Sign in"]},
            )
        )

    def test_playwright_adapter_reads_fixture_html(self):
        site = SiteConfig(
            id="sample_board",
            name="Sample Board",
            enabled=False,
            base_url="https://jobs.example",
            mode="playwright",
            access="guest",
            results={
                "list": [{"test_id": "job-card"}],
                "fields": {
                    "title": [{"css": "a.job-title"}],
                    "url": [{"css": "a.job-title", "attr": "href", "absolute_url": True}],
                    "company": [{"css": ".company"}],
                    "location": [{"css": ".location"}],
                    "posted_date": [{"css": ".posted"}],
                    "employment_type": [{"css": ".type"}],
                    "snippet": [{"css": ".snippet"}],
                },
            },
            pagination={"type": "none", "max_pages": 1, "stop_when_no_new": 2},
            rate_limit={"min_delay_s": 0, "max_delay_s": 0, "max_results": 10, "max_requests": 3},
            auth={"type": "none"},
        )
        options = dry_options()
        browser = BrowserSession(headless=True)
        try:
            result = fetch_site(site, SearchQuery(["python"]), loose_criteria(), options, browser=browser)
        finally:
            browser.close()
        self.assertEqual(result.status, "ok")
        self.assertGreaterEqual(len(result.listings), 1)
        first = result.listings[0]
        self.assertEqual(first.title, "Python Automation Engineer")
        self.assertEqual(first.url, "https://jobs.example/jobs/python-automation")
        self.assertEqual(first.company, "Acme Data")
        self.assertIn("Playwright", first.snippet or "")


if __name__ == "__main__":
    unittest.main()
