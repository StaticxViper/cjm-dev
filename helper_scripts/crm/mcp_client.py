"""JSON-RPC transport for the Moulton Ventures CRM MCP endpoint.

Lead upload runs the MCP initialize handshake. Opportunity upload posts
tools/call directly. Callers keep their own error types and result parsing.
"""

from __future__ import annotations

import httpx

CRM_MCP_URL = "https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1/mcp-crm"


def mcp_headers(api_key):
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {api_key}",
    }


def jsonrpc_request(request_id, method, params=None):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def jsonrpc_notification(method):
    return {"jsonrpc": "2.0", "method": method}


def post_json(url, api_key, payload, *, timeout=60.0, client=None, poster=None):
    """POST one JSON-RPC body.

    ``poster`` is the lead client's ``httpx.post`` so tests that patch that
    name still see the call. An injected ``client`` is the opp-finder path.
    With neither, a short-lived httpx client is opened for this call.
    """
    headers = mcp_headers(api_key)
    if client is not None:
        return client.post(url, headers=headers, json=payload)
    if poster is not None:
        return poster(url, headers=headers, json=payload, timeout=timeout)
    with httpx.Client(timeout=timeout) as session:
        return session.post(url, headers=headers, json=payload)
