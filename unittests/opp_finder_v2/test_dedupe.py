"""URL canonicalization and cross-site merges."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from opp_finder_v2.dedupe import canonical_url, dedupe_opportunities, opp_id_for  # noqa: E402
from opp_finder_v2.models import Criteria, Opportunity  # noqa: E402

SCRAPED = datetime(2026, 10, 5, tzinfo=timezone.utc)
BREAKDOWN = {
    "title_keywords": 0,
    "title_boost": 0,
    "body_keywords": 0,
    "remote": 0,
    "employment_type": 0,
    "recency": 0,
    "rate": 0,
}


def criteria() -> Criteria:
    return Criteria(
        keywords_any=["python"],
        keywords_all=[],
        title_boost=["python"],
        exclude_keywords=[],
        remote_only=False,
        employment_types=["contract", "freelance", "full_time", "part_time"],
        location_allow=["us", "usa", "united states", "anywhere", "worldwide"],
        location_deny=[],
        location_unknown="keep",
        posted_within_days=None,
        min_rate_hourly=40,
        min_rate_annual=85000,
        min_rate_unknown="keep",
        min_relevance=0,
        raw={},
    )


def opportunity(**overrides) -> Opportunity:
    values = dict(
        opp_id="",
        title="Python Automation Engineer (Contract)",
        company="Acme Data LLC",
        location="Remote",
        remote=True,
        url="https://remotive.com/jobs/1?utm_source=newsletter",
        apply_url=None,
        source_site="remotive",
        sources=[
            {
                "site": "remotive",
                "url": "https://remotive.com/jobs/1?utm_source=newsletter",
                "scraped_at": "2026-10-05T00:00:00Z",
            }
        ],
        posted_date="2026-10-04",
        snippet="short",
        salary_text=None,
        rate_min=None,
        rate_max=None,
        rate_unit=None,
        currency=None,
        employment_type="contract",
        tags=["python"],
        matched_keywords=["python"],
        relevance_score=0,
        score_breakdown=dict(BREAKDOWN),
        scraped_at="2026-10-05T00:00:00Z",
    )
    values.update(overrides)
    return Opportunity(**values)


class TestDedupe(unittest.TestCase):
    def test_tracking_params_and_www_are_stripped(self):
        cleaned = canonical_url(
            "HTTPS://WWW.Example.com/jobs/1/?utm_source=x&b=2&fbclid=z&a=1#section"
        )
        self.assertEqual(cleaned, "https://example.com/jobs/1?a=1&b=2")
        self.assertEqual(
            canonical_url("https://www.indeed.com/viewjob?jk=abc123&utm_campaign=c&src=email"),
            "https://indeed.com/viewjob?jk=abc123",
        )

    def test_title_noise_and_company_suffix_share_an_id(self):
        left = opp_id_for("Python Automation Engineer (Contract)", "Acme Data LLC")
        right = opp_id_for("Python Automation Engineer - Remote", "Acme Data")
        self.assertEqual(left, right)
        self.assertEqual(len(left), 16)

    def test_same_job_on_two_boards_merges(self):
        first = opportunity()
        second = opportunity(
            title="Python Automation Engineer - Remote",
            company="Acme Data",
            location="Remote, US",
            url="https://weworkremotely.com/remote-jobs/acme?fbclid=1",
            source_site="weworkremotely",
            sources=[
                {
                    "site": "weworkremotely",
                    "url": "https://weworkremotely.com/remote-jobs/acme?fbclid=1",
                    "scraped_at": "2026-10-05T01:00:00Z",
                }
            ],
            snippet="A longer description of the python automation role and its duties.",
            rate_min=60,
            rate_max=80,
            rate_unit="hour",
            currency="USD",
            salary_text="$60 - $80/hr",
        )
        merged, merges = dedupe_opportunities([first, second], criteria(), SCRAPED)
        self.assertEqual(merges, 1)
        self.assertEqual(len(merged), 1)
        record = merged[0]
        self.assertEqual(len(record.sources), 2)
        sites = {source["site"] for source in record.sources}
        self.assertEqual(sites, {"remotive", "weworkremotely"})
        self.assertIn("longer description", record.snippet)
        self.assertEqual(record.rate_max, 80)
        self.assertEqual(record.rate_unit, "hour")
        self.assertEqual(record.relevance_score, sum(record.score_breakdown.values()))

    def test_same_title_at_two_companies_stays_separate(self):
        first = opportunity(company="Acme Data")
        second = opportunity(
            company="Other Studio",
            url="https://remoteok.com/jobs/2",
            source_site="remoteok",
            sources=[{"site": "remoteok", "url": "https://remoteok.com/jobs/2", "scraped_at": "2026-10-05T00:00:00Z"}],
        )
        merged, merges = dedupe_opportunities([first, second], criteria(), SCRAPED)
        self.assertEqual(merges, 0)
        self.assertEqual(len(merged), 2)

    def test_empty_company_does_not_merge_on_title(self):
        first = opportunity(company=None, url="https://example.com/a")
        second = opportunity(
            company="",
            url="https://example.com/b",
            source_site="remoteok",
            sources=[{"site": "remoteok", "url": "https://example.com/b", "scraped_at": "2026-10-05T00:00:00Z"}],
        )
        merged, merges = dedupe_opportunities([first, second], criteria(), SCRAPED)
        self.assertEqual(merges, 0)
        self.assertEqual(len(merged), 2)

    def test_known_rate_beats_unknown(self):
        rich = opportunity(rate_min=50, rate_max=70, rate_unit="hour", currency="USD", snippet="x")
        thin = opportunity(snippet="x" * 20, url="https://example.com/same-job")
        # Same company and title, different URLs: merge on opp_id.
        merged, merges = dedupe_opportunities([thin, rich], criteria(), SCRAPED)
        self.assertEqual(merges, 1)
        self.assertEqual(merged[0].rate_max, 70)
        self.assertGreater(len(merged[0].snippet), 1)


if __name__ == "__main__":
    unittest.main()
