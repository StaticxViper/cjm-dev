"""Public ATS job-board endpoints. Each one was checked live on 2026-11-02.

Only official public read endpoints are listed. None needs a key. A board
slug that the ATS does not know answers 404, which the Actor reports as a
``not_found`` row for that company.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse


VERIFIED_ON = "2026-11-02"

ATS = {
    "greenhouse": {
        "title": "Greenhouse",
        "endpoint": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true&pay_transparency=true",
        "docs": "https://developers.greenhouse.io/job-board.html",
    },
    "lever": {
        "title": "Lever",
        "endpoint": "https://api.lever.co/v0/postings/{slug}?mode=json",
        "endpoint_eu": "https://api.eu.lever.co/v0/postings/{slug}?mode=json",
        "docs": "https://github.com/lever/postings-api",
    },
    "ashby": {
        "title": "Ashby",
        "endpoint": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
        "docs": "https://developers.ashbyhq.com/docs/public-job-posting-api",
    },
    "workable": {
        "title": "Workable",
        "endpoint": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
        # Workable does not document the careers-widget feed. Its documented
        # API needs an employer token, so this public endpoint is the one used.
        "docs": "",
    },
}

ATS_ORDER = ("greenhouse", "lever", "ashby", "workable")

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

# Path segment that comes right before the slug in an API or board URL.
_SLUG_MARKERS = ("boards", "postings", "job-board", "accounts")


def board_url(ats, slug, eu=False):
    spec = ATS[ats]
    template = spec.get("endpoint_eu") if eu and spec.get("endpoint_eu") else spec["endpoint"]
    return template.format(slug=quote(slug, safe=""))


def normalize_slug(value):
    """Return (slug, eu) from a bare slug or a board / API URL. Empty when invalid."""
    text = str(value or "").strip()
    if not text:
        return "", False
    eu = False
    if "/" in text:
        candidate = text if "://" in text else "https://" + text
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower()
        if host and "." in host:
            eu = ".eu." in host
            parts = [part for part in parsed.path.split("/") if part]
            slug = ""
            for marker in _SLUG_MARKERS:
                if marker in parts:
                    index = parts.index(marker)
                    if index + 1 < len(parts):
                        slug = parts[index + 1]
                        break
            if not slug and parts:
                slug = parts[0]
            text = slug
    if not _SLUG.fullmatch(text):
        return "", eu
    return text, eu
