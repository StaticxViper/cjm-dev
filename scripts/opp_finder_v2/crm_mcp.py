"""Upload opportunities to the Moulton Ventures CRM over its MCP endpoint.

This client posts JSON-RPC tool calls to the CRM MCP server. It does not use
helper_scripts.api_manager.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from opp_finder_v2.models import Opportunity
from opp_finder_v2.parsing import HOURS_PER_YEAR

CRM_MCP_URL = "https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1/mcp-crm"
CRM_MCP_ENV = "CRM_MCP_MV_LLC"
DEFAULT_VENTURE = "Side Job Leads"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class CrmError(Exception):
    pass


@dataclass
class UploadResult:
    created: int = 0
    skipped: int = 0
    failed: int = 0
    batch: str = ""


def load_crm_key() -> str:
    load_dotenv(_REPO_ROOT / ".env")
    return os.environ.get(CRM_MCP_ENV, "").strip()


def _redact(text: str, key: str) -> str:
    if key and key in text:
        return text.replace(key, "<redacted>")
    return text


def _norm_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


def _annual_value(opp: Opportunity) -> float | None:
    if opp.currency and opp.currency.upper() not in {"USD", "$", "US$"}:
        return None
    amount = opp.rate_max if opp.rate_max is not None else opp.rate_min
    if amount is None or not opp.rate_unit:
        return None
    if opp.rate_unit == "year":
        return float(amount)
    if opp.rate_unit == "hour":
        return float(amount) * HOURS_PER_YEAR
    if opp.rate_unit == "month":
        return float(amount) * 12
    return None


def opportunity_to_lead(opp: Opportunity, *, venture: str, batch: str) -> dict[str, Any]:
    company = (opp.company or "").strip()
    title = opp.title.strip()
    business_name = f"{title} — {company}" if company else title
    tags = ["opp-finder", opp.source_site]
    if opp.employment_type:
        tags.append(opp.employment_type)
    if opp.remote is True:
        tags.append("remote")
    elif opp.remote is False:
        tags.append("on-site")
    for keyword in opp.matched_keywords:
        tags.append(keyword)
    unique_tags: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        cleaned = str(tag).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        unique_tags.append(cleaned[:40])
        if len(unique_tags) == 15:
            break
    note_lines = [
        f"Role: {title}",
        f"Company: {company or 'unknown'}",
        f"Location: {opp.location or 'unknown'}",
        f"Remote: {opp.remote}",
        f"Employment: {opp.employment_type or 'unknown'}",
        f"Posted: {opp.posted_date or 'unknown'}",
        f"Salary: {opp.salary_text or 'unknown'}",
        f"Score: {opp.relevance_score}",
        f"Source: {opp.source_site}",
        f"Listing: {opp.url}",
        f"Apply: {opp.apply_url or opp.url}",
        f"opp_id: {opp.opp_id}",
        "",
        opp.snippet or "",
    ]
    payload: dict[str, Any] = {
        "business_name": business_name[:180],
        "website": opp.url,
        "address": opp.location or "",
        "notes": "\n".join(note_lines)[:4000],
        "business_description": (opp.snippet or title)[:500],
        "score": max(0, min(100, int(opp.relevance_score))),
        "tags": unique_tags,
        "venture": venture,
        "batch": batch,
        "status_name": "New Lead",
    }
    annual = _annual_value(opp)
    if annual is not None:
        payload["estimated_value"] = round(annual, 2)
    return payload


class CrmMcp:
    def __init__(self, key: str, url: str = CRM_MCP_URL, client: Any = None):
        if not key:
            raise CrmError(
                f"{CRM_MCP_ENV} is not set. Add it to .env. Results stay in the JSON file."
            )
        self.key = key
        self.url = url
        self._client = client
        self._next_id = 1

    def call(self, name: str, arguments: dict | None = None) -> dict:
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        self._next_id += 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.key}",
        }
        if self._client is not None:
            response = self._client.post(self.url, headers=headers, json=body)
        else:
            with httpx.Client(timeout=60) as client:
                response = client.post(self.url, headers=headers, json=body)
        text = _redact(response.text, self.key)
        if response.status_code >= 400:
            raise CrmError(f"CRM MCP {name} HTTP {response.status_code}: {text[:500]}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise CrmError(f"CRM MCP {name} returned non-JSON: {text[:500]}") from exc
        if "error" in payload:
            message = payload["error"].get("message") if isinstance(payload["error"], dict) else payload["error"]
            raise CrmError(f"CRM MCP {name}: {_redact(str(message), self.key)}")
        result = payload.get("result") or {}
        if result.get("isError"):
            bits = result.get("content") or []
            detail = bits[0].get("text") if bits else "tool error"
            raise CrmError(f"CRM MCP {name}: {_redact(str(detail), self.key)}")
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        content = result.get("content") or []
        if content and isinstance(content[0], dict) and content[0].get("text"):
            raw = content[0]["text"]
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {"text": raw}
            if isinstance(parsed, dict):
                return parsed
        return result if isinstance(result, dict) else {}


def _batch_token(created: dict, fallback: str) -> str:
    batch = created.get("batch") if isinstance(created.get("batch"), dict) else created
    if isinstance(batch, dict):
        for key in ("batch_id", "id", "slug", "name"):
            value = batch.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _lead_exists(payload: dict, url: str) -> bool:
    leads = payload.get("leads") or []
    target = _norm_url(url)
    if not target:
        return False
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        website = lead.get("website") or ""
        if _norm_url(str(website)) == target:
            return True
    return False


def upload_opportunities(
    opportunities: list[Opportunity],
    *,
    venture: str = DEFAULT_VENTURE,
    batch_label: str,
    key: str | None = None,
    client: CrmMcp | None = None,
) -> UploadResult:
    """Create one CRM batch and one lead per new listing URL."""
    pending = [opp for opp in opportunities if (opp.url or "").strip() and (opp.title or "").strip()]
    result = UploadResult()
    if not pending:
        return result
    crm = client or CrmMcp(key if key is not None else load_crm_key())
    fresh: list[Opportunity] = []
    for opp in pending:
        try:
            existing = crm.call(
                "list_leads",
                {"venture": venture, "search": opp.url, "limit": 10},
            )
        except CrmError:
            existing = {}
        if _lead_exists(existing, opp.url):
            result.skipped += 1
            continue
        fresh.append(opp)
    if not fresh:
        return result
    created = crm.call(
        "create_batch",
        {
            "venture": venture,
            "name": batch_label[:120],
            "notes": "Imported by opp_finder_v2",
        },
    )
    batch = _batch_token(created, batch_label)
    result.batch = batch
    for opp in fresh:
        try:
            crm.call("create_lead", opportunity_to_lead(opp, venture=venture, batch=batch))
            result.created += 1
        except CrmError:
            result.failed += 1
    return result
