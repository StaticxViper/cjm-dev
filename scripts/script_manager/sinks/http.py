"""Signed JSON posts. Hosts must be on the allowlist. Redirects stay off."""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlparse

from scripts.script_manager.sinks import SinkError

SIGNATURE_HEADER = "X-Script-Manager-Signature"


def signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def parse_hosts(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip().lower() for part in value.split(",") if part.strip()}


def require_allowed_url(url: str, hosts: set[str]) -> str:
    if not url or not str(url).strip():
        raise SinkError("callback URL is empty")
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise SinkError("callback URL must use https")
    if parsed.username or parsed.password:
        raise SinkError("callback URL must not include userinfo")
    host = (parsed.hostname or "").lower()
    if not host or host not in hosts:
        shown = host or "(missing)"
        raise SinkError(f"callback host {shown} is not allowlisted")
    return url.strip()


def post_json(url: str, body: bytes, headers: dict[str, str]) -> int:
    import httpx

    response = httpx.post(url, content=body, headers=headers, timeout=60.0, follow_redirects=False)
    if response.status_code >= 400:
        raise SinkError(f"callback HTTP {response.status_code}")
    return response.status_code
