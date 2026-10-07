"""CRM MCP upload mapping. No network and no APIManager."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from opp_finder_v2.crm_mcp import (  # noqa: E402
    CrmMcp,
    opportunity_to_lead,
    upload_opportunities,
)
from opp_finder_v2.models import Opportunity  # noqa: E402


def opportunity(**overrides) -> Opportunity:
    values = dict(
        opp_id="abc123abc123abcd",
        title="QA Test Engineer",
        company="Acme",
        location="Remote (US)",
        remote=True,
        url="https://example.com/jobs/qa",
        apply_url="https://example.com/jobs/qa/apply",
        source_site="remotive",
        sources=[],
        posted_date="2026-10-05",
        snippet="Python test automation.",
        salary_text="$50/hr",
        rate_min=50,
        rate_max=50,
        rate_unit="hour",
        currency="USD",
        employment_type="contract",
        tags=[],
        matched_keywords=["QA"],
        relevance_score=40,
        score_breakdown={},
        scraped_at="2026-10-06T00:00:00Z",
    )
    values.update(overrides)
    return Opportunity(**values)


class FakeCrm:
    def __init__(self, key="test-key"):
        self.key = key
        self.calls = []

    def call(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if name == "list_leads":
            url = arguments["search"]
            if url.endswith("/existing"):
                return {"leads": [{"website": url}]}
            return {"leads": []}
        if name == "create_batch":
            return {"batch_id": "batch-1", "name": arguments["name"]}
        if name == "create_lead":
            if arguments["website"].endswith("/fail"):
                from opp_finder_v2.crm_mcp import CrmError

                raise CrmError("nope")
            return {"id": "lead-1"}
        raise AssertionError(name)


class TestCrmMcp(unittest.TestCase):
    def test_lead_payload_uses_role_and_score(self):
        payload = opportunity_to_lead(
            opportunity(),
            venture="Side Job Leads",
            batch="batch-1",
        )
        self.assertEqual(payload["business_name"], "QA Test Engineer — Acme")
        self.assertEqual(payload["website"], "https://example.com/jobs/qa")
        self.assertEqual(payload["score"], 40)
        self.assertEqual(payload["venture"], "Side Job Leads")
        self.assertEqual(payload["status_name"], "New Lead")
        self.assertIn("opp-finder", payload["tags"])
        self.assertEqual(payload["estimated_value"], 50 * 2080)
        self.assertNotIn("api_manager", payload["notes"])

    def test_upload_skips_existing_url_and_creates_a_batch(self):
        crm = FakeCrm()
        fresh = opportunity()
        duplicate = opportunity(url="https://example.com/jobs/existing", title="Duplicate")
        failed = opportunity(url="https://example.com/jobs/fail", title="Broken")
        result = upload_opportunities(
            [duplicate, fresh, failed],
            venture="Side Job Leads",
            batch_label="Opp finder test",
            client=crm,
        )
        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.batch, "batch-1")
        names = [name for name, _args in crm.calls]
        self.assertIn("create_batch", names)
        self.assertEqual(names.count("create_lead"), 2)
        self.assertNotIn("APIManager", crm.__class__.__mro__[0].__name__)

    def test_client_sends_bearer_not_api_manager(self):
        seen = {}

        class DummyResponse:
            status_code = 200
            text = '{"jsonrpc":"2.0","id":1,"result":{"structuredContent":{"ok":true}}}'

            def json(self):
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"structuredContent": {"ok": True}},
                }

        class DummyClient:
            def post(self, url, headers, json):
                seen["url"] = url
                seen["auth"] = headers["Authorization"]
                seen["body"] = json
                return DummyResponse()

        client = CrmMcp("secret-token", client=DummyClient())
        payload = client.call("list_ventures", {})
        self.assertEqual(payload, {"ok": True})
        self.assertTrue(seen["url"].endswith("/mcp-crm"))
        self.assertEqual(seen["auth"], "Bearer secret-token")
        self.assertEqual(seen["body"]["method"], "tools/call")
        self.assertNotIn("X-API-Key", seen)
