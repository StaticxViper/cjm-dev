"""Signed POST of the run summary to the Property Portal callback."""

from __future__ import annotations

import json

from scripts.script_manager.sinks import SinkError
from scripts.script_manager.sinks.http import SIGNATURE_HEADER, parse_hosts, post_json, require_allowed_url, signature

_URL = "SCRIPT_MANAGER_PROPERTY_PORTAL_URL"


def send(run_result: dict, config: dict) -> None:
    env = config["env"]
    url = require_allowed_url(
        env.get(_URL) or "",
        parse_hosts(env.get("SCRIPT_MANAGER_CALLBACK_HOSTS")),
    )
    secret = (env.get("SCRIPT_MANAGER_CALLBACK_SECRET") or "").strip()
    if not secret:
        raise SinkError("SCRIPT_MANAGER_CALLBACK_SECRET is not set")
    body = json.dumps(run_result, separators=(",", ":")).encode("utf-8")
    post_json(
        url,
        body,
        {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: signature(secret, body),
        },
    )
