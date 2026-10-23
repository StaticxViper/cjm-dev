"""POST the run summary to the CRM dashboard URL."""

from __future__ import annotations

import json

from scripts.script_manager.sinks import SinkError
from scripts.script_manager.sinks.http import parse_hosts, post_json, require_allowed_url

_URL = "SCRIPT_MANAGER_DASHBOARD_URL"


def send(run_result: dict, config: dict) -> None:
    env = config["env"]
    url = require_allowed_url(
        env.get(_URL) or "",
        parse_hosts(env.get("SCRIPT_MANAGER_CALLBACK_HOSTS")),
    )
    token = (env.get("CRM_MCP_MV_LLC") or "").strip()
    if not token:
        raise SinkError("CRM_MCP_MV_LLC is not set")
    body = json.dumps(run_result, separators=(",", ":")).encode("utf-8")
    post_json(
        url,
        body,
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
