"""
HTTP client for /functions/v1/leads-ingest.

Requires LEADS_API_KEY in the environment (x-api-key header).
"""
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1"
ENDPOINT = "/leads-ingest"
LEADS_API_KEY = os.getenv("LEAD_INGEST_KEY")

MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0


def _headers() -> Dict[str, str]:
    if not LEADS_API_KEY:
        raise RuntimeError("LEADS_API_KEY environment variable is not set")
    return {
        "Content-Type": "application/json",
        "x-api-key": LEADS_API_KEY,
    }


def request_with_retry(
    method: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    timeout: float = 60.0,
) -> Any:
    """Issue a request with exponential backoff on HTTP 429."""
    backoff = INITIAL_BACKOFF
    last_response: Optional[httpx.Response] = None

    with httpx.Client(base_url=BASE_URL, timeout=timeout) as client:
        for attempt in range(MAX_RETRIES):
            response = client.request(
                method=method.upper(),
                url=ENDPOINT,
                headers=_headers(),
                params=params,
                json=json_body,
            )
            last_response = response

            if response.status_code == 429:
                if attempt == MAX_RETRIES - 1:
                    response.raise_for_status()
                time.sleep(min(backoff, MAX_BACKOFF))
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue

            response.raise_for_status()
            if response.content:
                return response.json()
            return {}

    if last_response is not None:
        last_response.raise_for_status()
    return {}


def parse_leads_response(body: Any) -> List[dict]:
    """Accept top-level array or wrapped {leads|data: [...]}."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("leads", "data"):
            value = body.get(key)
            if isinstance(value, list):
                return value
    return []


def fetch_existing_leads(group: Optional[str] = None) -> List[dict]:
    params = {"group": group} if group else None
    body = request_with_retry("GET", params=params)
    return parse_leads_response(body)


def post_leads_batch(leads: List[dict]) -> Any:
    return request_with_retry("POST", json_body=leads)


def post_lead(lead: dict) -> dict:
    result = request_with_retry("POST", json_body=lead)
    if isinstance(result, dict):
        return result
    return {"raw": result}


def classify_response(resp: Any) -> str:
    """Return 'created', 'updated', or 'skipped' for a single API result."""
    if not isinstance(resp, dict):
        return "skipped"
    status = resp.get("status")
    if status == "created":
        return "created"
    if status == "updated":
        return "updated"
    if resp.get("success") is True and status is None:
        return "created"
    return "skipped"


def count_batch_results(response: Any, submitted: int) -> Dict[str, int]:
    """
    Tally created/updated/skipped from a batch POST response.
    Handles list of per-lead results or a single summary object.
    """
    counts = {"created": 0, "updated": 0, "skipped": 0}

    if isinstance(response, list):
        for item in response:
            key = classify_response(item)
            counts[key] += 1
        return counts

    if isinstance(response, dict):
        if "results" in response and isinstance(response["results"], list):
            for item in response["results"]:
                key = classify_response(item)
                counts[key] += 1
            return counts

        single = classify_response(response)
        if single != "skipped":
            counts[single] = 1
            counts["skipped"] = max(0, submitted - 1)
        else:
            counts["skipped"] = submitted
        return counts

    counts["skipped"] = submitted
    return counts
