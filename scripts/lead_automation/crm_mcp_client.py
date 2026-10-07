#!/usr/bin/env python3
"""Synchronous facade over the official MCP Python SDK.

One background event loop so Playwright's sync API and the async MCP client
can run in the same process. The server URL is required (``--mcp-url`` or
``CRM_MCP_URL``). This module has no default URL.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
import asyncio
import json
import re
import threading
import time

from helper_scripts.utils.logger.logger import setup_logger

logger = setup_logger(
    name="crm_enrich",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)
logger.propagate = False

AUTH_MESSAGE = "CRM MCP auth failed; check CRM_MCP_TOKEN"
URL_MESSAGE = "Set CRM_MCP_URL or pass --mcp-url"

CORE_TOOLS = ("list_leads", "get_lead", "update_lead")
DISCOVERY_TOOLS = ("list_ventures", "list_batches", "get_batch")
REQUIRED_TOOLS = DISCOVERY_TOOLS + CORE_TOOLS

# Keys update_lead accepts today. Note-only Maps fields stay out of this set
# until the server lists them; promoting one later is a one-line edit here
# (the startup tools/list check also promotes a key when the description
# already lists it under "Allowed keys").
UPDATE_LEAD_WRITABLE = frozenset({
    "business_name",
    "contact_first_name",
    "contact_last_name",
    "contact_title",
    "email",
    "phone",
    "website",
    "address",
    "notes",
    "tags",
    "score",
    "estimated_value",
    "business_description",
    "sms_message",
    "email_subject",
    "email_message",
    "next_action_label",
    "next_action_at",
    "column_id",
    "email_opt_out",
})

NOTE_ONLY_FIELDS = (
    "google_maps_uri",
    "rating",
    "user_ratings_total",
    "business_status",
    "place_types",
    "needs_review",
)

# Never send these from crm_enrich even though the server allows them.
NEVER_WRITE_FIELDS = frozenset({
    "score",
    "column_id",
    "sms_message",
    "email_subject",
    "email_message",
    "email_opt_out",
    "next_action_label",
    "next_action_at",
    "business_name",
    "estimated_value",
    "business_description",
})

CONNECT_BACKOFF = (1, 2, 4)


class CrmError(Exception):
    """Base error for the CRM MCP client."""


class CrmConfigError(CrmError):
    """Missing URL or other local configuration. CLI exit 2."""


class CrmConnectionError(CrmError):
    """Connect, auth, or tooling failure. CLI exit 3."""


class CrmAuthError(CrmConnectionError):
    """HTTP 401/403. The message never includes the token."""

    def __init__(self, message=AUTH_MESSAGE):
        super().__init__(message)


class CrmToolError(CrmError):
    """A tool result with isError / is_error set."""


def redact_url(url):
    """Drop query strings and fragments so tokens in URLs are not logged."""
    if not url:
        return ""
    parts = urlsplit(str(url))
    query = "REDACTED" if parts.query else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def safe_error_text(exc, token=None):
    text = f"{type(exc).__name__}"
    detail = str(exc or "")
    if token:
        detail = detail.replace(str(token), "[redacted]")
    detail = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", detail, flags=re.I)
    detail = re.sub(r"(CRM_MCP_\w+=)\S+", r"\1[redacted]", detail)
    if detail and detail != text:
        text = f"{text}: {detail}"
    return text[:400]


def status_code_of(exc):
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        code = getattr(response, "status_code", None)
        if code is None:
            code = getattr(current, "status_code", None)
        if code is not None:
            try:
                return int(code)
            except (TypeError, ValueError):
                return None
        current = getattr(current, "__cause__", None)
    return None


def writable_from_tool(tool):
    """Start from UPDATE_LEAD_WRITABLE and promote keys the server already allows."""
    writable = set(UPDATE_LEAD_WRITABLE)
    description = getattr(tool, "description", "") or ""
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
    blob = description
    if isinstance(schema, dict):
        try:
            blob = description + "\n" + json.dumps(schema)
        except TypeError:
            blob = description
    match = re.search(r"allowed keys?:\s*([^\n]+)", blob, flags=re.I)
    mentioned = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1))) if match else set()
    for key in NOTE_ONLY_FIELDS:
        if key in mentioned:
            writable.add(key)
    return frozenset(writable)


def parse_tool_result(result):
    """Prefer structured content, otherwise the first JSON text block."""
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        chunks = []
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", "") or ""
            if text:
                chunks.append(text.strip())
        raise CrmToolError("; ".join(chunks) or "CRM tool returned an error")
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        if set(structured.keys()) == {"result"}:
            inner = structured["result"]
            if isinstance(inner, (dict, list)):
                return inner
        return structured
    if isinstance(structured, list):
        return structured
    for block in getattr(result, "content", None) or []:
        text = (getattr(block, "text", "") or "").strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    return {}


def derive_catalog(leads):
    """Build venture/batch rows from lead records when discovery tools are absent."""
    ventures = {}
    batches = {}
    for lead in leads:
        vid = lead.get("venture_id")
        vname = lead.get("venture_name") or ""
        if vid and vid not in ventures:
            ventures[vid] = {
                "id": vid,
                "name": vname,
                "slug": lead.get("venture_slug") or vid,
                "batch_count": 0,
                "lead_count": 0,
                "archived_at": None,
                "color": None,
            }
        if vid and vid in ventures:
            ventures[vid]["lead_count"] += 1
        bid = lead.get("batch_id")
        if not bid:
            continue
        if bid not in batches:
            batches[bid] = {
                "batch_id": bid,
                "name": lead.get("batch_name") or bid,
                "venture_id": vid,
                "total": 0,
                "is_legacy": False,
                "source": None,
                "imported_at": None,
                "rates": {},
            }
        batches[bid]["total"] += 1
    for batch in batches.values():
        vid = batch.get("venture_id")
        if vid in ventures:
            ventures[vid]["batch_count"] += 1
    return {"ventures": list(ventures.values()), "batches": list(batches.values())}


class CrmClient:
    """Sync wrapper. ``server`` is an in-process ``MCPServer`` for tests."""

    def __init__(self, url=None, token=None, transport="streamable-http", server=None):
        if server is None and not (url and str(url).strip()):
            raise CrmConfigError(URL_MESSAGE)
        self.url = str(url).strip() if url else None
        self._token = token or None
        self.transport = transport or "streamable-http"
        self._server = server
        self._loop = None
        self._thread = None
        self._loop_ready = threading.Event()
        self._client = None
        self._cm = None
        self._http = None
        self._did_reconnect = False
        self.tool_names = []
        self.discovery_fallback = False
        self.writable_fields = set(UPDATE_LEAD_WRITABLE)

    def _headers(self):
        if not self._token:
            return {}
        return {"Authorization": f"Bearer {self._token}"}

    def _ensure_loop(self):
        if self._loop is not None:
            return
        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop_ready.set()
            self._loop.run_forever()
        self._thread = threading.Thread(target=_run, name="crm-mcp", daemon=True)
        self._thread.start()
        if not self._loop_ready.wait(10):
            raise CrmConnectionError("CRM MCP event loop did not start")

    def _submit(self, coro, timeout=120):
        if self._loop is None:
            raise CrmConnectionError("CRM MCP client is not connected")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _open_client(self):
        from mcp import Client

        if self._server is not None:
            self._cm = Client(self._server)
        elif self.transport == "sse":
            from mcp.client.sse import sse_client
            self._cm = Client(sse_client(self.url, headers=self._headers() or None))
        else:
            from mcp.client.streamable_http import (
                create_mcp_http_client,
                streamable_http_client,
            )
            self._http = create_mcp_http_client(headers=self._headers() or None)
            transport = streamable_http_client(self.url, http_client=self._http)
            self._cm = Client(transport)
        self._client = await self._cm.__aenter__()

    async def _shutdown(self):
        cm, client, http = self._cm, self._client, self._http
        self._client = None
        self._cm = None
        self._http = None
        if cm is not None and client is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("CRM MCP close: %s", type(exc).__name__)
        if http is not None:
            closer = getattr(http, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    pass

    async def _load_tools(self):
        listed = await self._client.list_tools()
        tools = list(getattr(listed, "tools", None) or [])
        self.tool_names = [tool.name for tool in tools]
        missing_core = [name for name in CORE_TOOLS if name not in self.tool_names]
        if missing_core:
            raise CrmConnectionError(
                "CRM MCP is missing tools: " + ", ".join(missing_core)
            )
        missing_discovery = [name for name in DISCOVERY_TOOLS if name not in self.tool_names]
        self.discovery_fallback = bool(missing_discovery)
        if missing_discovery:
            logger.error(
                "CRM MCP discovery tools missing (%s); coverage will be computed from list_leads",
                ", ".join(missing_discovery),
            )
        update_tool = next((tool for tool in tools if tool.name == "update_lead"), None)
        self.writable_fields = writable_from_tool(update_tool)

    async def _open(self):
        logger.info("Connecting to CRM MCP at %s", redact_url(self.url) or "in-process")
        await self._open_client()
        await self._load_tools()

    def connect(self, sleeper=None):
        """Connect and initialize. Retries DNS/connect/timeouts, not auth failures."""
        sleeper = sleeper or time.sleep
        self._ensure_loop()
        last = None
        attempts = len(CONNECT_BACKOFF) + 1
        for attempt in range(attempts):
            try:
                self._submit(self._open(), timeout=90)
                self._did_reconnect = False
                return
            except CrmAuthError:
                raise
            except CrmConnectionError as exc:
                if "missing tools" in str(exc):
                    raise
                last = exc
            except Exception as exc:
                if status_code_of(exc) in (401, 403):
                    raise CrmAuthError() from None
                last = exc
            if attempt < attempts - 1:
                try:
                    self._submit(self._shutdown(), timeout=20)
                except Exception:
                    pass
                sleeper(CONNECT_BACKOFF[attempt])
        raise CrmConnectionError(
            "CRM MCP connection failed: " + safe_error_text(last, self._token)
        )

    def close(self):
        if self._loop is None:
            return
        try:
            self._submit(self._shutdown(), timeout=20)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    async def _call(self, name, arguments):
        result = await self._client.call_tool(name, arguments or {})
        return parse_tool_result(result)

    def _invoke(self, name, arguments):
        try:
            return self._submit(self._call(name, arguments))
        except CrmToolError:
            raise
        except CrmAuthError:
            raise
        except Exception as exc:
            if status_code_of(exc) in (401, 403):
                raise CrmAuthError() from None
            if self._did_reconnect:
                raise CrmConnectionError(safe_error_text(exc, self._token)) from exc
            self._did_reconnect = True
            logger.error("CRM MCP disconnected; reconnecting once")
            try:
                self._submit(self._shutdown(), timeout=20)
                self._submit(self._open(), timeout=90)
            except CrmAuthError:
                raise
            except Exception as reconn:
                raise CrmConnectionError(
                    "CRM MCP connection failed: " + safe_error_text(reconn, self._token)
                ) from reconn
            return self._submit(self._call(name, arguments))

    def list_ventures(self, include_archived=False):
        args = {"include_archived": True} if include_archived else {}
        return self._invoke("list_ventures", args)

    def list_batches(self, venture):
        return self._invoke("list_batches", {"venture": venture})

    def get_batch(self, batch):
        return self._invoke("get_batch", {"batch": batch})

    def get_lead(self, lead_id):
        data = self._invoke("get_lead", {"lead_id": lead_id})
        if isinstance(data, dict) and isinstance(data.get("lead"), dict):
            return data["lead"]
        return data

    def update_lead(self, lead_id, fields):
        return self._invoke("update_lead", {"lead_id": lead_id, "fields": fields})

    def list_leads_page(self, batch=None, filters=None, limit=200, offset=0):
        filters = filters or {}
        args = {"limit": int(limit), "offset": int(offset)}
        if batch:
            args["batch"] = batch
        if filters.get("status"):
            args["status_name"] = filters["status"]
        if filters.get("tags"):
            args["tags"] = list(filters["tags"])
        if filters.get("has_email") is not None:
            args["has_email"] = bool(filters["has_email"])
        if filters.get("min_score") is not None:
            args["min_score"] = filters["min_score"]
        if filters.get("max_score") is not None:
            args["max_score"] = filters["max_score"]
        if filters.get("search"):
            args["search"] = filters["search"]
        return self._invoke("list_leads", args)

    def iter_leads(self, batch=None, filters=None, page_size=200, cap=None):
        """Yield leads until a short page. ``count`` is the page size, not the total."""
        offset = 0
        yielded = 0
        page_size = max(1, min(int(page_size or 200), 200))
        while True:
            page = self.list_leads_page(batch=batch, filters=filters, limit=page_size, offset=offset)
            leads = page.get("leads") if isinstance(page, dict) else None
            leads = list(leads or [])
            if not leads:
                return
            for lead in leads:
                yield lead
                yielded += 1
                if cap is not None and yielded >= cap:
                    return
            if len(leads) < page_size:
                return
            offset += len(leads)

    def catalog_from_leads(self, cap=5000):
        """Fallback when list_ventures / list_batches / get_batch are absent."""
        leads = list(self.iter_leads(page_size=200, cap=cap))
        return derive_catalog(leads)
