"""
Unit tests for scripts/lead_automation/crm_mcp_client.py

Run from repo root:
    python -m unittest unittests.lead_automation.test_crm_mcp_client
"""
import json
import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crm_enrich"

if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.chdir(_LEADGEN_DIR)

from crm_mcp_client import (  # noqa: E402
    AUTH_MESSAGE,
    URL_MESSAGE,
    UPDATE_LEAD_WRITABLE,
    CrmAuthError,
    CrmClient,
    CrmConfigError,
    CrmConnectionError,
    CrmToolError,
    safe_error_text,
    status_code_of,
    writable_from_tool,
)


def _load(name):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _page_server():
    from mcp.server import MCPServer

    mcp = MCPServer("crm-fixture")
    pages = {
        0: _load("list_leads_page1.json"),
        2: _load("list_leads_page2.json"),
    }
    calls = {"offsets": []}

    @mcp.tool()
    def list_ventures() -> dict:
        """List ventures."""
        return _load("list_ventures.json")

    @mcp.tool()
    def list_batches(venture: str) -> dict:
        """List batches."""
        return _load("list_batches.json")

    @mcp.tool()
    def get_batch(batch: str) -> dict:
        """Get one batch."""
        return _load("get_batch.json")

    @mcp.tool()
    def list_leads(batch: str = "", limit: int = 50, offset: int = 0) -> dict:
        """List a page of leads. count is the page size."""
        calls["offsets"].append(offset)
        page = pages.get(offset) or {"count": 0, "offset": offset, "leads": []}
        return page

    @mcp.tool()
    def get_lead(lead_id: str) -> dict:
        """Fetch one lead."""
        for page in pages.values():
            for lead in page["leads"]:
                if lead["id"] == lead_id:
                    return lead
        raise RuntimeError("missing")

    @mcp.tool()
    def update_lead(lead_id: str, fields: dict) -> dict:
        """Update a lead."""
        raise RuntimeError("boom")

    return mcp, calls


class TestConfig(unittest.TestCase):
    def test_url_is_required(self):
        with self.assertRaises(CrmConfigError) as caught:
            CrmClient()
        self.assertEqual(str(caught.exception), URL_MESSAGE)
        self.assertNotIn("supabase", str(caught.exception).lower())

    def test_auth_message_omits_token(self):
        token = "super-secret-token"
        text = safe_error_text(Exception(f"Bearer {token} rejected"), token=token)
        self.assertNotIn(token, text)
        self.assertNotIn(token, AUTH_MESSAGE)
        self.assertEqual(str(CrmAuthError()), AUTH_MESSAGE)

    def test_status_code_401(self):
        class Response:
            status_code = 401

        class Boom(Exception):
            response = Response()

        self.assertEqual(status_code_of(Boom()), 401)

    def test_writable_constant_and_description_promotion(self):
        self.assertNotIn("google_maps_uri", UPDATE_LEAD_WRITABLE)
        self.assertIn("email", UPDATE_LEAD_WRITABLE)

        class Tool:
            description = "Allowed keys: email, phone, google_maps_uri, notes, tags."

        promoted = writable_from_tool(Tool())
        self.assertIn("google_maps_uri", promoted)
        self.assertNotIn("rating", writable_from_tool(Tool()))


class TestInProcess(unittest.TestCase):
    def test_pagination_stops_on_short_page(self):
        mcp, calls = _page_server()
        client = CrmClient(server=mcp)
        try:
            client.connect(sleeper=lambda _seconds: None)
            leads = list(client.iter_leads(batch="35404690-180f-42af-b034-dcf567a1628f", page_size=2))
        finally:
            client.close()
        self.assertEqual([lead["id"] for lead in leads], [
            "e89bdb1c-22af-4d6f-a529-12e8207abdcb",
            "459faa3b-1111-4222-8333-459faa3b0001",
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        ])
        self.assertEqual(calls["offsets"], [0, 2])

    def test_is_error_raises_tool_error(self):
        mcp, _calls = _page_server()
        client = CrmClient(server=mcp)
        try:
            client.connect(sleeper=lambda _seconds: None)
            with self.assertRaises(CrmToolError):
                client.update_lead("e89bdb1c-22af-4d6f-a529-12e8207abdcb", {"notes": "x"})
        finally:
            client.close()

    def test_missing_core_tool(self):
        from mcp.server import MCPServer

        mcp = MCPServer("incomplete")

        @mcp.tool()
        def list_leads(batch: str = "") -> dict:
            """List leads."""
            return {"leads": []}

        @mcp.tool()
        def get_lead(lead_id: str) -> dict:
            """Get lead."""
            return {"id": lead_id}

        client = CrmClient(server=mcp)
        try:
            with self.assertRaises(CrmConnectionError) as caught:
                client.connect(sleeper=lambda _seconds: None)
            self.assertIn("update_lead", str(caught.exception))
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
