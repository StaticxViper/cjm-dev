"""Upload leads to the Moulton Ventures CRM over its MCP endpoint.

Discovery still uses API Manager for Google Places. Dashboard upload does not.
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

CRM_MCP_URL = os.getenv(
    "CRM_MCP_URL",
    "https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1/mcp-crm",
)
# Web Dev - MV Software. Override with CRM_MCP_VENTURE (id, slug, or name).
DEFAULT_VENTURE = os.getenv("CRM_MCP_VENTURE", "web-dev-mv-software-iq3x")

_LEAD_FIELDS = frozenset({
    "business_name",
    "email",
    "phone",
    "website",
    "address",
    "contact_first_name",
    "contact_last_name",
    "notes",
    "business_description",
    "score",
    "estimated_value",
    "tags",
    "status_id",
    "status_name",
})

_run_batch_name = None
_batch_created = False


class CrmMcpError(RuntimeError):
    pass


def run_batch_name():
    """One batch name per process so a multi-city run stays in one import."""
    global _run_batch_name
    if not _run_batch_name:
        _run_batch_name = "Leadgen " + datetime.now().strftime("%Y-%m-%d %H:%M")
    return _run_batch_name


def reset_run_batch():
    """Test hook. Production runs keep one batch for the process."""
    global _run_batch_name, _batch_created
    _run_batch_name = None
    _batch_created = False


class CrmMcpClient:
    def __init__(self, url=None, api_key=None, venture=None):
        self.url = url or CRM_MCP_URL
        self.api_key = os.getenv("CRM_MCP_MV_LLC") if api_key is None else api_key
        self.venture = DEFAULT_VENTURE if venture is None else venture
        self._request_id = 0
        self._initialized = False

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _post(self, payload):
        response = httpx.post(self.url, headers=self._headers(), json=payload, timeout=60.0)
        if response.status_code == 202:
            return {}
        if response.status_code >= 400:
            detail = (response.text or "").strip().replace("\n", " ")[:300]
            raise CrmMcpError(f"CRM MCP HTTP {response.status_code}: {detail}")
        if not response.content:
            return {}
        return response.json()

    def _rpc(self, method, params=None):
        self._request_id += 1
        body = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params is not None:
            body["params"] = params
        data = self._post(body)
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise CrmMcpError(message or "CRM MCP error")
        if isinstance(data, dict):
            return data.get("result")
        return data

    def ensure_session(self):
        if self._initialized:
            return
        if not self.api_key:
            raise CrmMcpError("CRM_MCP_MV_LLC is not set")
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "leadgen", "version": "1.0"},
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    def call_tool(self, name, arguments):
        self.ensure_session()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if isinstance(result, dict) and result.get("isError"):
            text = ""
            for block in result.get("content") or []:
                if isinstance(block, dict) and block.get("text"):
                    text = block["text"]
                    break
            raise CrmMcpError(text or f"{name} failed")
        return result

    def ensure_batch(self):
        global _batch_created
        name = run_batch_name()
        if not _batch_created:
            self.call_tool("create_batch", {"venture": self.venture, "name": name})
            _batch_created = True
        return name

    def create_lead(self, fields):
        payload = {}
        extras = []
        for key, value in (fields or {}).items():
            if value in (None, ""):
                continue
            if key in _LEAD_FIELDS:
                payload[key] = value
            else:
                extras.append(f"{key}: {value}")
        if extras:
            note = str(payload.get("notes") or "").strip()
            extra = "; ".join(extras)
            payload["notes"] = f"{note}; {extra}".strip("; ").strip()
        if "business_name" not in payload:
            raise CrmMcpError("business_name is required")
        if "score" in payload:
            payload["score"] = max(0, min(100, int(payload["score"])))
        payload["venture"] = self.venture
        payload["batch"] = self.ensure_batch()
        return self.call_tool("create_lead", payload)
