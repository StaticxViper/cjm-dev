"""Shared Actor entry helpers. Copy this file with the template; do not import it across Actors."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
import os
import random
import time

# Same Chrome UA the local Playwright scrapers already send. robots.txt is
# evaluated for User-agent: *, which is the group this UA falls into.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def find_repo_root():
    """Repo root locally, or CJM_REPO_ROOT inside the Actor image."""
    env = os.environ.get("CJM_REPO_ROOT")
    if env:
        root = Path(env)
        if (root / "helper_scripts").is_dir() and (root / "scripts").is_dir():
            return root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "helper_scripts").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not find the repo root. Set CJM_REPO_ROOT.")


def prepare_imports():
    """Put the repo, city-data CLI, and lead_automation CLI on sys.path."""
    import sys

    root = find_repo_root()
    for path in (
        root,
        root / "scripts" / "city_data",
        root / "scripts" / "lead_automation",
    ):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    return root


def unused_proxy_note(actor_input):
    """proxyConfiguration is accepted by the form and never used."""
    if (actor_input or {}).get("proxyConfiguration"):
        return "proxyConfiguration is ignored; this Actor does not rotate proxies or IPs."
    return None


def fetch_text(url, attempts=3, timeout=20):
    """GET a text URL. Retries 429 and 5xx with jittered backoff.

    Navigation retries for the scrapers stay inside the existing Playwright
    sessions. This helper is for robots.txt and similar short HTTP reads.
    """
    last = None
    for attempt in range(attempts):
        try:
            req = urlrequest.Request(url, headers={"User-Agent": USER_AGENT})
            with urlrequest.urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", 200) or 200
                body = response.read().decode("utf-8", "replace")
                if status == 429 or status >= 500:
                    raise RuntimeError(f"HTTP {status} for {url}")
                return body
        except urlerror.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            last = exc
        if attempt + 1 < attempts:
            time.sleep(random.uniform(0.4, 1.2) * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last}")
