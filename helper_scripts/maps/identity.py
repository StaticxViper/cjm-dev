"""Google Maps profile URL and place-id identity keys."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import unquote, urlparse

CHIJ_RE = re.compile(r"(?:!19s|place_id[=:])(ChIJ[\w-]+)")
HEX_FID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")


def normalize_profile_url(url):
    """Collapse a Maps place URL to a stable identity key."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path or "")
        if "/maps/place/" in path:
            parts = path.split("/maps/place/", 1)[1]
            name = parts.split("/")[0]
            fid = None
            match = HEX_FID_RE.search(url) or HEX_FID_RE.search(unquote(parsed.query or ""))
            if match:
                fid = match.group(1).lower()
            chij = None
            place_match = CHIJ_RE.search(url)
            if place_match:
                chij = place_match.group(1)
            if chij:
                return f"https://www.google.com/maps/place/?q=place_id:{chij}"
            if fid:
                return f"https://www.google.com/maps/place/?q={fid}"
            if name:
                return f"https://www.google.com/maps/place/{name}"
        return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    except Exception:
        return str(url).split("?")[0].split("#")[0]


def extract_place_id_from_url(url):
    """Return a Google place_id (ChIJ...) or a stable maps: fallback id."""
    if not url:
        return None
    match = CHIJ_RE.search(url)
    if match:
        return match.group(1)
    match = HEX_FID_RE.search(url)
    if match:
        return f"maps:{match.group(1).lower()}"
    stable = normalize_profile_url(url)
    if stable:
        digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:20]
        return f"maps:{digest}"
    return None
