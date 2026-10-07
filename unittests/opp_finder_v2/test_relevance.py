"""Scoring components, hard filters, and rate normalization."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from opp_finder_v2.models import Criteria, Opportunity  # noqa: E402
from opp_finder_v2.parsing import parse_salary_text  # noqa: E402
from opp_finder_v2.relevance import BREAKDOWN_KEYS, apply_relevance, score_opportunity  # noqa: E402

SCRAPED = datetime(2026, 10, 5, tzinfo=timezone.utc)


def criteria(**overrides) -> Criteria:
    values = dict(
        keywords_any=["python", "automation", "playwright"],
        keywords_all=[],
        title_boost=["python"],
        exclude_keywords=["clearance required", "senior staff"],
        remote_only=True,
        employment_types=["contract", "freelance", "part_time", "full_time"],
        location_allow=["us", "usa", "united states", "anywhere", "worldwide"],
        location_deny=["uk only", "europe only"],
        location_unknown="keep",
        posted_within_days=14,
        min_rate_hourly=40,
        min_rate_annual=85000,
        min_rate_unknown="keep",
        min_relevance=0,
        raw={},
    )
    values.update(overrides)
    return Criteria(**values)


def opportunity(**overrides) -> Opportunity:
    values = dict(
        opp_id="0" * 16,
        title="Python Automation Engineer",
        company="Acme",
        location="Remote (US)",
        remote=True,
        url="https://example.com/jobs/1",
        apply_url=None,
        source_site="remotive",
        sources=[],
        posted_date="2026-10-03",
        snippet="Build Playwright flows for backend services.",
        salary_text="$70 - $90/hr",
        rate_min=70,
        rate_max=90,
        rate_unit="hour",
        currency="USD",
        employment_type="contract",
        tags=[],
        matched_keywords=[],
        relevance_score=0,
        score_breakdown={},
        scraped_at="2026-10-05T00:00:00Z",
    )
    values.update(overrides)
    return Opportunity(**values)


class TestRelevance(unittest.TestCase):
    def test_each_score_component_and_clamped_sum(self):
        opp = opportunity(
            title="Python automation playwright backend",
            snippet="scraping data pipelines and web scraping work",
        )
        crit = criteria(
            keywords_any=["python", "automation", "playwright", "backend", "scraping", "data"],
            title_boost=["python", "automation"],
        )
        score, breakdown, matched = score_opportunity(opp, crit, SCRAPED)
        self.assertEqual(breakdown["title_keywords"], 45)
        self.assertEqual(breakdown["title_boost"], 10)
        self.assertEqual(breakdown["body_keywords"], 10)
        self.assertEqual(breakdown["remote"], 10)
        self.assertEqual(breakdown["employment_type"], 10)
        self.assertEqual(breakdown["recency"], 10)
        self.assertEqual(breakdown["rate"], 5)
        self.assertEqual(score, min(100, sum(breakdown.values())))
        self.assertEqual(set(breakdown), set(BREAKDOWN_KEYS))
        self.assertIn("python", matched)
        self.assertNotIn("pythonic", " ".join(matched))

    def test_body_only_keyword_does_not_get_title_points(self):
        opp = opportunity(title="Support lead", snippet="We use playwright in production.")
        score, breakdown, matched = score_opportunity(
            opp, criteria(keywords_any=["playwright"], title_boost=[]), SCRAPED
        )
        self.assertEqual(breakdown["title_keywords"], 0)
        self.assertEqual(breakdown["body_keywords"], 5)
        self.assertEqual(matched, ["playwright"])
        self.assertEqual(score, sum(breakdown.values()))

    def test_unknown_fields_are_neutral(self):
        opp = opportunity(
            location=None,
            remote=None,
            posted_date=None,
            employment_type=None,
            rate_min=None,
            rate_max=None,
            rate_unit=None,
            currency=None,
            salary_text=None,
            snippet="python services",
            title="Engineer",
        )
        reason = apply_relevance(opp, criteria(min_relevance=0), SCRAPED)
        self.assertIsNone(reason)
        self.assertEqual(opp.score_breakdown["remote"], 0)
        self.assertEqual(opp.score_breakdown["recency"], 0)
        self.assertEqual(opp.score_breakdown["rate"], 0)
        self.assertEqual(opp.score_breakdown["employment_type"], 0)
        self.assertEqual(opp.relevance_score, sum(opp.score_breakdown.values()))

    def test_exclude_keyword_drops(self):
        opp = opportunity(snippet="This role is clearance required for federal work.")
        reason = apply_relevance(opp, criteria(), SCRAPED)
        self.assertEqual(reason, "exclude_keyword")

    def test_remote_false_drops_and_unknown_does_not(self):
        onsite = opportunity(remote=False, location="Austin, TX")
        self.assertEqual(apply_relevance(onsite, criteria(), SCRAPED), "not_remote")
        unknown = opportunity(remote=None, location="Austin, TX")
        self.assertIsNone(apply_relevance(unknown, criteria(min_relevance=0), SCRAPED))

    def test_location_deny_and_allow(self):
        denied = opportunity(location="UK only")
        self.assertEqual(apply_relevance(denied, criteria(), SCRAPED), "location_deny")
        allowed = opportunity(location="Remote (US)")
        self.assertIsNone(apply_relevance(allowed, criteria(min_relevance=0), SCRAPED))
        _, breakdown, _matched = score_opportunity(allowed, criteria(), SCRAPED)
        self.assertEqual(breakdown["remote"], 10)

    def test_stale_post_drops_and_missing_date_does_not(self):
        stale = opportunity(posted_date="2026-09-01")
        self.assertEqual(apply_relevance(stale, criteria(), SCRAPED), "stale")
        missing = opportunity(posted_date=None)
        self.assertIsNone(apply_relevance(missing, criteria(min_relevance=0), SCRAPED))

    def test_hourly_and_annual_thresholds(self):
        parsed = parse_salary_text("$60 - $80/hr")
        self.assertEqual(parsed["rate_min"], 60)
        self.assertEqual(parsed["rate_max"], 80)
        self.assertEqual(parsed["rate_unit"], "hour")
        self.assertEqual(parsed["currency"], "USD")
        annual = parse_salary_text("$20k-$35k")
        self.assertEqual(annual["rate_min"], 20000)
        self.assertEqual(annual["rate_max"], 35000)
        self.assertEqual(annual["rate_unit"], "year")

        low_hour = opportunity(rate_min=30, rate_max=30, rate_unit="hour", salary_text="$30/hr")
        self.assertEqual(apply_relevance(low_hour, criteria(), SCRAPED), "below_rate")
        at_hour = opportunity(rate_min=40, rate_max=40, rate_unit="hour")
        self.assertIsNone(apply_relevance(at_hour, criteria(min_relevance=0), SCRAPED))
        _, breakdown, _matched = score_opportunity(at_hour, criteria(), SCRAPED)
        self.assertEqual(breakdown["rate"], 5)

        low_year = opportunity(rate_min=80000, rate_max=80000, rate_unit="year", salary_text="$80,000 a year")
        self.assertEqual(apply_relevance(low_year, criteria(), SCRAPED), "below_rate")
        high_year = opportunity(rate_min=90000, rate_max=90000, rate_unit="year")
        _, breakdown, _matched = score_opportunity(high_year, criteria(), SCRAPED)
        self.assertEqual(breakdown["rate"], 5)

        euro = opportunity(rate_min=100000, rate_max=120000, rate_unit="year", currency="EUR")
        self.assertIsNone(apply_relevance(euro, criteria(min_relevance=0), SCRAPED))
        _, breakdown, _matched = score_opportunity(euro, criteria(), SCRAPED)
        self.assertEqual(breakdown["rate"], 0)

    def test_low_relevance_drops(self):
        opp = opportunity(title="Office coordinator", snippet="phones and filing", remote=None, location=None,
                          employment_type=None, rate_min=None, rate_max=None, rate_unit=None, posted_date=None,
                          salary_text=None)
        reason = apply_relevance(opp, criteria(keywords_any=["office"], min_relevance=40), SCRAPED)
        self.assertEqual(reason, "low_relevance")

    def test_keyword_word_boundary(self):
        opp = opportunity(title="Pythonic style guide", snippet="not a job")
        reason = apply_relevance(opp, criteria(keywords_any=["python"], title_boost=[], min_relevance=0), SCRAPED)
        self.assertEqual(reason, "no_keyword")

    def test_title_match_required_drops_body_only(self):
        opp = opportunity(title="Marketing manager", snippet="We use python and automation.")
        reason = apply_relevance(opp, criteria(require_title_match=True, min_relevance=0), SCRAPED)
        self.assertEqual(reason, "no_keyword")
        kept = opportunity(title="Python QA engineer", snippet="manual testing")
        self.assertIsNone(apply_relevance(kept, criteria(require_title_match=True, min_relevance=0), SCRAPED))

    def test_hybrid_is_not_remote(self):
        from opp_finder_v2.parsing import infer_remote

        self.assertFalse(infer_remote("Hybrid - Austin, TX", [], None))
        self.assertTrue(infer_remote("Remote or hybrid, United States", [], None))

    def test_us_only_keeps_us_locations(self):
        us_criteria = criteria(us_only=True, min_relevance=0)
        for place in ("Remote (US)", "Austin, TX", "New York, NY", "San Francisco, CA", "United States"):
            kept = opportunity(location=place)
            self.assertIsNone(apply_relevance(kept, us_criteria, SCRAPED), place)
        for place in ("Remote, France", "Berlin, Germany", "London, UK", "Tokyo, Japan", "Toronto, Canada", ""):
            dropped = opportunity(location=place or None)
            reason = apply_relevance(dropped, us_criteria, SCRAPED)
            self.assertIn(reason, {"location_deny", "unknown_location"}, place)
        worldwide = opportunity(location="Worldwide")
        self.assertEqual(apply_relevance(worldwide, us_criteria, SCRAPED), "unknown_location")


if __name__ == "__main__":
    unittest.main()
