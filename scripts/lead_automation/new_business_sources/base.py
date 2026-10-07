"""Shared types, access checks, and polite HTTP for new-business sources."""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib import robotparser

import requests

from email_discovery import CAPTCHA_MARKERS, SEARCH_DELAY_MAX, SEARCH_DELAY_MIN
from playwright_discovery import is_google_block_page

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "unittests" / "lead_automation" / "fixtures" / "new_business"
LEADGEN_DIR = Path(__file__).resolve().parents[1]

ACCESS_OK = "ok"
ACCESS_BLOCKED = "blocked"
ACCESS_LOGIN = "login_required"
ACCESS_PAYWALL = "paywalled"
ACCESS_ROBOTS = "robots_disallowed"
ACCESS_UNAVAILABLE = "unavailable"
ACCESS_DISABLED = "disabled"

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

LOGIN_MARKERS = (
    "sign in to continue",
    "log in to continue",
    "password",
    "create an account",
)
PAYWALL_MARKERS = (
    "paywall",
    "purchase this report",
    "payment required",
    "subscription required",
    "buy this record",
)

_HOST_LOCKS = {}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fixture_dir(source_id):
    return FIXTURE_ROOT / source_id


def load_fixture_text(source_id, name):
    path = fixture_dir(source_id) / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_fixture_json(source_id, name="payload.json"):
    text = load_fixture_text(source_id, name)
    if not text:
        return None
    return json.loads(text)


def resolve_fixture_dates(value, today=None):
    """Replace days-ago tokens so dry-run fixtures stay inside the age window."""
    today = today or datetime.now(timezone.utc).date()
    prefix = "{" + "{days_ago:"
    suffix = "}" * 2
    if isinstance(value, str) and value.startswith(prefix) and value.endswith(suffix):
        from datetime import timedelta
        days = int(value[len(prefix):-len(suffix)])
        return (today - timedelta(days=days)).isoformat()
    if isinstance(value, list):
        return [resolve_fixture_dates(item, today=today) for item in value]
    if isinstance(value, dict):
        return {key: resolve_fixture_dates(item, today=today) for key, item in value.items()}
    return value


@dataclass
class NewBusinessRecord:
    business_name: str = ""
    alternate_names: list = field(default_factory=list)
    category: str = ""
    description: str = ""
    registration_date: str | None = None
    formation_date: str | None = None
    filing_date: str | None = None
    opening_date: str | None = None
    business_status: str = ""
    state: str = ""
    county: str = ""
    city: str = ""
    zip: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    email: str = ""
    maps_url: str = ""
    place_id: str = ""
    entity_id: str = ""
    source_name: str = ""
    source_url: str = ""
    source_record_url: str = ""
    source_category: str = ""
    retrieved_at: str = ""
    newness_evidence: list = field(default_factory=list)
    public_contacts: list = field(default_factory=list)
    fields_provided: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    phone_origin: str = ""
    email_source: str = ""
    email_source_url: str = ""
    email_confidence: str = ""
    email_evidence: str = ""

    def as_dict(self):
        payload = asdict(self)
        payload.pop("raw", None)
        return payload


class SourceAdapter:
    """One public source. Subclasses implement parse and, when live, fetch_payload."""

    def __init__(self, entry):
        self.entry = entry
        self.id = entry.get("id") or ""
        self.name = entry.get("name") or self.id
        self.category = entry.get("category") or ""
        self.coverage = entry.get("coverage") or {}
        self.enabled = bool(entry.get("enabled"))
        self.status = entry.get("status") or "candidate"
        self.url = entry.get("url") or entry.get("endpoint") or ""

    def runnable(self):
        return self.enabled and self.status == "verified"

    def check_access(self, html=None, robots_txt=None, target_url=None):
        target = target_url or self.url
        if robots_txt is not None or html is not None:
            if robots_txt and target and not robots_allowed(robots_txt, target):
                return ACCESS_ROBOTS
            if html:
                return classify_access_html(html, target or "")
            return ACCESS_OK
        if not self.enabled or self.status in ("disabled", "candidate"):
            return "disabled"
        if self.status == "blocked":
            return ACCESS_BLOCKED
        access = (self.entry.get("access") or "public").lower()
        if access == "login":
            return ACCESS_LOGIN
        if access == "paywall":
            return ACCESS_PAYWALL
        if access == "captcha":
            return ACCESS_BLOCKED
        if target:
            robots_body = fetch_robots(target)
            if robots_body and not robots_allowed(robots_body, target):
                return ACCESS_ROBOTS
        return ACCESS_OK

    def fetch(self, geo, since_date, limit, dry_run=False):
        raise NotImplementedError


def classify_access_html(html, url=""):
    if is_google_block_page(html or "", url or ""):
        return ACCESS_BLOCKED
    text = f"{url or ''} {html or ''}".lower()
    if any(marker in text for marker in CAPTCHA_MARKERS):
        return ACCESS_BLOCKED
    if any(marker in text for marker in PAYWALL_MARKERS):
        return ACCESS_PAYWALL
    if "sign in" in text or "log in" in text or ("password" in text and "account" in text):
        return ACCESS_LOGIN
    return ACCESS_OK


def robots_allowed(robots_txt, url, user_agent=None):
    parser = robotparser.RobotFileParser()
    parser.parse((robots_txt or "").splitlines())
    agent = user_agent or FETCH_HEADERS["User-Agent"]
    try:
        return parser.can_fetch(agent, url)
    except Exception:
        return False


def fetch_robots(url, timeout=10):
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = requests.get(robots_url, timeout=timeout, headers=FETCH_HEADERS)
    except requests.RequestException:
        return ""
    if response.status_code >= 400:
        return ""
    return response.text or ""


def _host_lock(url):
    host = urlparse(url).netloc.lower()
    lock = _HOST_LOCKS.get(host)
    if lock is None:
        import threading
        lock = threading.Lock()
        _HOST_LOCKS[host] = lock
    return lock


def polite_get(url, *, rate_limit=None, timeout=20, session=None):
    """One request at a time per host, with jittered delay and two retries."""
    rate_limit = rate_limit or {}
    min_delay = float(rate_limit.get("min_delay_s", SEARCH_DELAY_MIN))
    max_delay = float(rate_limit.get("max_delay_s", SEARCH_DELAY_MAX))
    getter = session.get if session is not None else requests.get
    lock = _host_lock(url)
    last_error = None
    with lock:
        for attempt in range(3):
            if attempt:
                delay = min(30.0, (2 ** (attempt - 1)) + random.uniform(0, 0.5))
                time.sleep(delay)
            elif rate_limit.get("_requests"):
                time.sleep(random.uniform(min_delay, max(min_delay, max_delay)))
            try:
                response = getter(url, timeout=timeout, headers=FETCH_HEADERS)
            except requests.RequestException as exc:
                last_error = exc
                continue
            rate_limit["_requests"] = int(rate_limit.get("_requests") or 0) + 1
            if response.status_code in (429,) or response.status_code >= 500:
                last_error = requests.HTTPError(f"HTTP {response.status_code}")
                retry_after = response.headers.get("Retry-After")
                if attempt < 2 and retry_after:
                    try:
                        time.sleep(min(30.0, float(retry_after)))
                    except ValueError:
                        pass
                continue
            return response
    if last_error:
        raise last_error
    raise requests.RequestException(f"Failed to fetch {url}")


def evidence(evidence_type, value, source_name, source_url, confidence="high"):
    if not value:
        return None
    return {
        "type": evidence_type,
        "date": str(value)[:10],
        "source_name": source_name,
        "source_url": source_url,
        "confidence": confidence,
    }


def compose_address(parts):
    bits = [str(part).strip() for part in parts if part and str(part).strip()]
    return ", ".join(bits)
