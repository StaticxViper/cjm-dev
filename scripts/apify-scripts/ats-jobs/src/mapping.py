"""Map Actor input onto ATS job rows.

Each ATS parser turns one board payload into job records with the same
shape. Filters, dedupe, newSinceLastRun, and maxItems run on those records
in input order, so a run is repeatable for the same boards.
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    from .runtime import is_block, iso_now, looks_json
    from .sources import ATS, ATS_ORDER, board_url, normalize_slug
    from .spend import JOB_EVENT, PRICES_USD
    from .state import STATE_STORE
except ImportError:
    from runtime import is_block, iso_now, looks_json
    from sources import ATS, ATS_ORDER, board_url, normalize_slug
    from spend import JOB_EVENT, PRICES_USD
    from state import STATE_STORE


log = logging.getLogger("apify")

REMOTE_CHOICES = ("any", "remote", "exclude")
MAX_COMPANIES = 1000

TEXT_FIELDS = (
    "ats",
    "company",
    "companySlug",
    "jobId",
    "title",
    "location",
    "workplaceType",
    "department",
    "postedDate",
    "url",
    "firstSeen",
)

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}
CURRENCY_CODES = ("USD", "EUR", "GBP", "CAD", "AUD", "CHF", "SEK", "NOK", "DKK", "JPY", "INR", "SGD", "NZD", "PLN", "BRL", "MXN", "ILS")

INTERVALS = {
    "per-year-salary": "year",
    "per-month-salary": "month",
    "per-week-salary": "week",
    "per-day-wage": "day",
    "per-hour-wage": "hour",
    "one-time": "one-time",
    "1 year": "year",
    "1 month": "month",
    "1 week": "week",
    "1 day": "day",
    "1 hour": "hour",
}

_AMOUNT = r"\d[\d,]*(?:\.\d+)?"
_CUR = r"(?:[$€£¥₹]|\b(?:" + "|".join(CURRENCY_CODES) + r")\b)"
_SALARY_RANGE = re.compile(
    r"(?P<cur>" + _CUR + r")\s?(?P<min>" + _AMOUNT + r")\s?(?P<mink>[kK])?"
    r"\s*(?:-|–|—|to)\s*"
    r"(?P<cur2>" + _CUR + r")?\s?(?P<max>" + _AMOUNT + r")\s?(?P<maxk>[kK])?"
    r"(?:\s*(?P<code>" + "|".join(CURRENCY_CODES) + r")\b)?",
)
_INTERVAL_HINTS = (
    (re.compile(r"\b(?:per|an|/|a)\s?(?:hour|hr)\b|\bhourly\b", re.I), "hour"),
    (re.compile(r"\b(?:per|a|/)\s?(?:year|yr|annum)\b|\bannual(?:ly)?\b|\byearly\b", re.I), "year"),
    (re.compile(r"\b(?:per|a|/)\s?(?:month|mo)\b|\bmonthly\b", re.I), "month"),
    (re.compile(r"\b(?:per|a|/)\s?week\b|\bweekly\b", re.I), "week"),
    (re.compile(r"\b(?:per|a|/)\s?day\b|\bdaily\b", re.I), "day"),
)
_TAG = re.compile(r"<[^>]+>")
_REMOTE_WORD = re.compile(r"\bremote\b", re.I)


# ---------------------------------------------------------------- input


def _bounded_int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _bounded_float(value, default, low, high):
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    return [text] if text else []


def _targets(raw):
    """Ordered, deduped (ats, slug, eu) targets plus input errors."""
    targets = []
    invalid = []
    seen = set()
    duplicates = 0
    lists = [(ats, False, raw.get(ats)) for ats in ATS_ORDER]
    lists.insert(2, ("lever", True, raw.get("leverEu")))
    for ats, eu_default, values in lists:
        for item in _as_list(values):
            slug, eu_url = normalize_slug(item)
            if not slug:
                invalid.append((ats, item))
                continue
            eu = bool(eu_default or eu_url) if ats == "lever" else False
            key = (ats, slug.lower(), eu)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            targets.append({"ats": ats, "slug": slug, "eu": eu})
    return targets, invalid, duplicates


def actor_input_to_config(actor_input):
    raw = actor_input or {}
    targets, invalid, duplicates = _targets(raw)
    remote = str(raw.get("remote") or "any").strip().lower()
    if remote not in REMOTE_CHOICES:
        remote = "any"
    keywords = _as_list(raw.get("keywords"))
    if not keywords:
        keywords = _as_list(raw.get("keyword"))
    locations = _as_list(raw.get("location"))
    error = ""
    if not targets and not invalid:
        error = "Add at least one company slug under greenhouse, lever, leverEu, ashby, or workable."
    elif len(targets) > MAX_COMPANIES:
        error = f"At most {MAX_COMPANIES} companies per run. This input has {len(targets)}."
    store = str(raw.get("stateStoreName") or STATE_STORE).strip() or STATE_STORE
    return {
        "targets": targets,
        "invalid": invalid,
        "duplicate_targets": duplicates,
        "locations": [item.lower() for item in locations],
        "remote": remote,
        "keywords": [item.lower() for item in keywords],
        "keyword_patterns": keyword_patterns(keywords),
        "new_since_last_run": bool(raw.get("newSinceLastRun")),
        "state_store": store,
        "max_items": _bounded_int(raw.get("maxItems"), 100, 1, 10000),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 1.0, 1.0, 10.0),
        "max_spend_usd": _bounded_float(raw.get("maxSpendUsd"), 5.0, 0.0, 100.0),
        "error": error,
    }


# ---------------------------------------------------------------- helpers


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _clip(value, limit):
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _plain(markup):
    text = html.unescape(html.unescape(str(markup or "")))
    return _clean(_TAG.sub(" ", text))


def iso_date(value):
    """ISO 8601 in UTC for timestamps, or YYYY-MM-DD for date-only values."""
    if value is None or value == "" or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _interval(value):
    text = _clean(value).lower()
    if not text or text == "none":
        return None
    return INTERVALS.get(text, text)


def _salary(minimum=None, maximum=None, currency=None, interval=None, raw=""):
    low = _number(minimum)
    high = _number(maximum)
    raw = _clip(raw, 300)
    if low is None and high is None and not raw:
        return None
    return {
        "min": low,
        "max": high,
        "currency": (_clean(currency).upper() or None) if currency else None,
        "interval": _interval(interval),
        "raw": raw,
    }


def _money_text(amount, currency):
    if amount is None:
        return ""
    return f"{currency + ' ' if currency else ''}{amount:,}"


def _currency(symbol_or_code):
    text = _clean(symbol_or_code)
    return CURRENCY_SYMBOLS.get(text) or (text.upper() if text else None)


def parse_salary_text(text):
    """First "$120,000 - $150,000"-style range in free text, or None."""
    plain = _clean(text)
    if not plain:
        return None
    match = _SALARY_RANGE.search(plain)
    if not match:
        return None

    def amount(raw, k):
        value = float(raw.replace(",", ""))
        return value * 1000 if k else value

    low = amount(match.group("min"), match.group("mink") or match.group("maxk"))
    high = amount(match.group("max"), match.group("maxk"))
    if high < low:
        return None
    currency = _currency(match.group("code") or match.group("cur"))
    interval = _interval_hint(plain[match.end(): match.end() + 40])
    return _salary(low, high, currency, interval, match.group(0))


def _interval_hint(text):
    for pattern, name in _INTERVAL_HINTS:
        if pattern.search(text or ""):
            return name
    return None


def _workplace(value):
    text = _clean(value).lower().replace("_", "-")
    if not text or text == "unspecified":
        return ""
    if "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if text in ("on-site", "onsite", "on site", "in-office", "office", "in office"):
        return "onsite"
    return ""


def _remote(workplace, locations):
    if workplace:
        return workplace == "remote"
    return any(_REMOTE_WORD.search(item or "") for item in locations)


def _unique(items):
    out = []
    for item in items:
        text = _clip(item, 200)
        if text and text not in out:
            out.append(text)
    return out


def job_key(ats, slug, job_id):
    return f"{ats}:{str(slug).lower()}:{job_id}"


def _record(ats, slug, company, job_id, title, locations, workplace, department, posted, url, salary):
    job_id = _clip(job_id, 200)
    title = _clip(title, 300)
    if not job_id or not title:
        return None
    locations = _unique(locations)
    return {
        "ats": ats,
        "company": _clip(company, 200) or slug,
        "companySlug": slug,
        "jobId": job_id,
        "title": title,
        "location": locations[0] if locations else "",
        "locations": locations,
        "remote": _remote(workplace, locations),
        "workplaceType": workplace,
        "salary": salary,
        "department": _clip(department, 200),
        "postedDate": iso_date(posted),
        "url": _clean(url),
    }


# ---------------------------------------------------------------- parsers


def _greenhouse_salary(job):
    ranges = [item for item in job.get("pay_input_ranges") or [] if isinstance(item, dict)]
    if ranges:
        first = ranges[0]
        currency = _clean(first.get("currency_type")).upper() or None
        low = _number((first.get("min_cents") or 0) / 100) if first.get("min_cents") is not None else None
        high = _number((first.get("max_cents") or 0) / 100) if first.get("max_cents") is not None else None
        parts = []
        for item in ranges:
            cur = _clean(item.get("currency_type")).upper()
            lo = _number(item["min_cents"] / 100) if item.get("min_cents") is not None else None
            hi = _number(item["max_cents"] / 100) if item.get("max_cents") is not None else None
            text = " - ".join(part for part in (_money_text(lo, cur), _money_text(hi, cur)) if part)
            title = _clean(item.get("title"))
            if text:
                parts.append(f"{title}: {text}" if title else text)
        return _salary(low, high, currency, _interval_hint(f"{first.get('title') or ''} {first.get('blurb') or ''}"), "; ".join(parts))
    return parse_salary_text(_plain(job.get("content")))


def _greenhouse_workplace(job):
    for item in job.get("metadata") or []:
        if not isinstance(item, dict):
            continue
        if "workplace" in _clean(item.get("name")).lower() or "remote" in _clean(item.get("name")).lower():
            value = item.get("value")
            if isinstance(value, list):
                value = " ".join(str(part) for part in value)
            if isinstance(value, bool):
                return "remote" if value else ""
            kind = _workplace(value)
            if kind:
                return kind
    return ""


def parse_greenhouse(payload, slug):
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return None
    records = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        location = (job.get("location") or {}).get("name") if isinstance(job.get("location"), dict) else ""
        offices = [office.get("location") or office.get("name") for office in job.get("offices") or [] if isinstance(office, dict)]
        departments = [dept.get("name") for dept in job.get("departments") or [] if isinstance(dept, dict)]
        record = _record(
            "greenhouse",
            slug,
            job.get("company_name") or slug,
            job.get("id"),
            job.get("title"),
            [location] + offices,
            _greenhouse_workplace(job),
            ", ".join(_unique(departments)),
            job.get("first_published") or job.get("updated_at"),
            job.get("absolute_url"),
            _greenhouse_salary(job),
        )
        if record:
            records.append(record)
    return records


def _lever_salary(posting):
    rng = posting.get("salaryRange")
    raw = _clean(posting.get("salaryDescriptionPlain")) or _plain(posting.get("salaryDescription"))
    if isinstance(rng, dict) and (rng.get("min") is not None or rng.get("max") is not None):
        currency = _clean(rng.get("currency")).upper()
        if not raw:
            low, high = _number(rng.get("min")), _number(rng.get("max"))
            raw = " - ".join(part for part in (_money_text(low, currency), _money_text(high, currency)) if part)
            interval = _interval(rng.get("interval"))
            if raw and interval:
                raw = f"{raw} per {interval}"
        return _salary(rng.get("min"), rng.get("max"), currency or None, rng.get("interval"), raw)
    if raw:
        return parse_salary_text(raw) or _salary(raw=raw)
    return None


def parse_lever(payload, slug):
    if not isinstance(payload, list):
        return None
    records = []
    for posting in payload:
        if not isinstance(posting, dict):
            continue
        categories = posting.get("categories") if isinstance(posting.get("categories"), dict) else {}
        locations = [categories.get("location")] + list(categories.get("allLocations") or [])
        record = _record(
            "lever",
            slug,
            slug,
            posting.get("id"),
            posting.get("text"),
            locations,
            _workplace(posting.get("workplaceType")),
            categories.get("department") or categories.get("team"),
            posting.get("createdAt"),
            posting.get("hostedUrl"),
            _lever_salary(posting),
        )
        if record:
            records.append(record)
    return records


def _ashby_salary(job):
    comp = job.get("compensation")
    if not isinstance(comp, dict):
        return None
    raw = _clean(comp.get("scrapeableCompensationSalarySummary")) or _clean(comp.get("compensationTierSummary"))
    for item in comp.get("summaryComponents") or []:
        if isinstance(item, dict) and item.get("compensationType") == "Salary":
            if item.get("minValue") is None and item.get("maxValue") is None:
                continue
            return _salary(item.get("minValue"), item.get("maxValue"), item.get("currencyCode"), item.get("interval"), raw)
    if raw:
        return parse_salary_text(raw) or _salary(raw=raw)
    return None


def _ashby_workplace(job):
    kind = _workplace(job.get("workplaceType"))
    if kind:
        return kind
    if job.get("isRemote") is True:
        return "remote"
    return ""


def parse_ashby(payload, slug):
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return None
    records = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("isListed") is False:
            continue
        secondary = [item.get("location") for item in job.get("secondaryLocations") or [] if isinstance(item, dict)]
        record = _record(
            "ashby",
            slug,
            slug,
            job.get("id") or job.get("jobUrl"),
            job.get("title"),
            [job.get("location")] + secondary,
            _ashby_workplace(job),
            job.get("department") or job.get("team"),
            job.get("publishedAt"),
            job.get("jobUrl"),
            _ashby_salary(job),
        )
        if record:
            records.append(record)
    return records


def _workable_locations(job):
    places = []
    for item in job.get("locations") or []:
        if not isinstance(item, dict) or item.get("hidden"):
            continue
        place = ", ".join(_unique([item.get("city"), item.get("region"), item.get("country")]))
        if place:
            places.append(place)
    if not places:
        place = ", ".join(_unique([job.get("city"), job.get("state"), job.get("country")]))
        if place:
            places.append(place)
    if job.get("telecommuting") is True and not any(_REMOTE_WORD.search(item) for item in places):
        places.append("Remote")
    return places


def parse_workable(payload, slug):
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return None
    company = payload.get("name") or slug
    records = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        record = _record(
            "workable",
            slug,
            company,
            job.get("shortcode"),
            job.get("title"),
            _workable_locations(job),
            "remote" if job.get("telecommuting") is True else "",
            job.get("department"),
            job.get("published_on") or job.get("created_at"),
            job.get("url") or job.get("shortlink"),
            None,
        )
        if record:
            records.append(record)
    return records


PARSERS = {
    "greenhouse": parse_greenhouse,
    "lever": parse_lever,
    "ashby": parse_ashby,
    "workable": parse_workable,
}


# ---------------------------------------------------------------- filters


def keyword_patterns(words):
    """Whole-word matchers. Lookarounds instead of \\b so C++ and .NET still match."""
    return [re.compile(rf"(?<!\w){re.escape(word.lower())}(?!\w)") for word in words if word]


def _location_match(needle, places, record):
    if needle == "remote" and record.get("remote"):
        return True
    return any(needle in place for place in places)


def keep_job(record, config):
    places = [item.lower() for item in record.get("locations") or []]
    if config.get("locations"):
        if not any(_location_match(needle, places, record) for needle in config["locations"]):
            return False
    remote = config.get("remote") or "any"
    if remote == "remote" and not record.get("remote"):
        return False
    if remote == "exclude" and record.get("remote"):
        return False
    if config.get("keywords"):
        haystack = f"{record.get('title') or ''} {record.get('department') or ''}".lower()
        patterns = config.get("keyword_patterns") or keyword_patterns(config["keywords"])
        if not any(pattern.search(haystack) for pattern in patterns):
            return False
    return True


# ---------------------------------------------------------------- rows


def _blank_row(status, error, scraped_at, ats="", slug="", url="", decision="skipped"):
    row = {key: "" for key in TEXT_FIELDS}
    row.update({
        "ats": ats,
        "company": slug,
        "companySlug": slug,
        "url": url,
        "locations": [],
        "remote": False,
        "salary": None,
        "sourceStatus": status,
        "decision": decision,
        "ok": False,
        "error": error,
        "scrapedAt": scraped_at,
    })
    return row


def _dataset_row(record, first_seen, decision, scraped_at):
    row = _blank_row("found", "", scraped_at)
    row.update({key: record.get(key) for key in record})
    row["firstSeen"] = first_seen
    row["sourceStatus"] = "found"
    row["decision"] = decision
    row["ok"] = True
    row["error"] = ""
    return row


def billable_row(row):
    row = row or {}
    return row.get("sourceStatus") == "found" and row.get("ok") is True and bool(row.get("jobId"))


def _host(url):
    return urlparse(url or "").netloc


def outcome(result):
    """ok, not_found, blocked, robots, or error for one board response."""
    if not result:
        return "error"
    if result.get("error") == "robots_disallowed":
        return "robots"
    if result.get("error") == "robots_unavailable":
        return "error"
    if is_block(result):
        return "blocked"
    status = int(result.get("status") or 0)
    if status == 404:
        return "not_found"
    if result.get("error") or status >= 400 or status == 0:
        return "error"
    if not looks_json(result):
        text = (result.get("text") or "").lstrip()[:500].lower()
        if "html" in (result.get("content_type") or "").lower() or text.startswith("<"):
            return "blocked"
        return "error"
    return "ok"


def _failure_message(result):
    if result.get("error") == "robots_unavailable":
        return f"robots.txt could not be read: {result.get('detail') or 'fetch failed'}"
    if result.get("error"):
        return str(result["error"])
    status = int(result.get("status") or 0)
    if 200 <= status < 300:
        return "invalid_json: the board answered without a JSON body."
    return f"HTTP {status}" if status else "fetch_failed"


def _blocked_message(result):
    status = int(result.get("status") or 0)
    what = f"HTTP {status}" if status and status != 200 else "a challenge page instead of JSON"
    return (
        f"Blocked by {_host(result.get('url'))} ({what}). This Actor does not use a proxy "
        "or a CAPTCHA solver, so later boards on this host were skipped. Other hosts "
        "still ran. This row is not charged."
    )


def scrape(config, fetch, seen=None, now=None):
    """Return (rows, summary, new_seen). new_seen maps pushed job keys to firstSeen."""
    scraped_at = now or iso_now()
    seen = seen or {}
    status_rows = []
    for ats, item in config.get("invalid") or []:
        status_rows.append(_blank_row("error", f"Not a valid {ats} board slug: {item!r}", scraped_at, ats=ats))
    if config.get("error"):
        row = _blank_row("error", config["error"], scraped_at)
        return [row], _summarize([row], config, {}, [], "", False, scraped_at), {}

    kept = []
    keys = set()
    counts = {"duplicates": 0, "filtered": 0, "skippedSeen": 0, "skippedBlockedHost": 0}
    blocked_hosts = set()
    reports = []
    truncated = False
    stopped = ""

    for target in config["targets"]:
        if len(kept) >= config["max_items"]:
            truncated = True
            break
        ats, slug = target["ats"], target["slug"]
        url = board_url(ats, slug, target.get("eu"))
        report = {"ats": ats, "slug": slug, "status": "ok", "fetched": 0, "kept": 0}
        if _host(url) in blocked_hosts:
            report["status"] = "skipped_blocked_host"
            counts["skippedBlockedHost"] += 1
            reports.append(report)
            _log_company(report)
            continue
        result = fetch(url)
        kind = outcome(result)
        if kind == "ok":
            try:
                payload = json.loads(result.get("text") or "null")
            except json.JSONDecodeError:
                kind, result = "error", {"error": "invalid_json", "url": url}
            else:
                jobs = PARSERS[ats](payload, slug)
                if jobs is None:
                    kind, result = "error", {"error": "unexpected_payload", "url": url}
        if kind != "ok":
            report["status"] = kind
            reports.append(report)
            _log_company(report)
            if kind == "blocked":
                status_rows.append(_blank_row("blocked", _blocked_message(result), scraped_at, ats, slug, url, "stopped"))
                blocked_hosts.add(_host(url))
                stopped = "blocked"
                continue
            if kind == "not_found":
                status_rows.append(_blank_row(
                    "not_found", f"{ATS[ats]['title']} has no public board named {slug!r} (HTTP 404).",
                    scraped_at, ats, slug, url,
                ))
            elif kind == "robots":
                status_rows.append(_blank_row("robots_disallowed", "robots.txt disallows this board.", scraped_at, ats, slug, url))
            else:
                status_rows.append(_blank_row("error", _failure_message(result), scraped_at, ats, slug, url))
            continue

        report["fetched"] = len(jobs)
        for record in jobs:
            key = job_key(ats, slug, record["jobId"])
            if key in keys:
                counts["duplicates"] += 1
                continue
            keys.add(key)
            if not keep_job(record, config):
                counts["filtered"] += 1
                continue
            first = seen.get(key) or ""
            if first and config.get("new_since_last_run"):
                counts["skippedSeen"] += 1
                continue
            if len(kept) >= config["max_items"]:
                truncated = True
                break
            record["_key"] = key
            record["_first"] = first or scraped_at
            record["_decision"] = "repeat" if first else "new"
            kept.append(record)
            report["kept"] += 1
        if not jobs:
            report["status"] = "empty"
        reports.append(report)
        _log_company(report)

    rows = []
    new_seen = {}
    for record in kept:
        key, first, decision = record.pop("_key"), record.pop("_first"), record.pop("_decision")
        rows.append(_dataset_row(record, first, decision, scraped_at))
        if decision == "new":
            new_seen[key] = first
    rows.extend(status_rows)
    if not kept and not status_rows:
        message = "No jobs matched these boards and filters."
        if counts["skippedSeen"]:
            message = "No new jobs since the last run for these boards and filters."
        rows.append(_blank_row("not_found", message, scraped_at))
    counts["duplicateTargets"] = config.get("duplicate_targets") or 0
    summary = _summarize(rows, config, counts, reports, stopped, truncated, scraped_at)
    log.critical(
        "ATS jobs SUMMARY: status=%s found=%s new=%s companies=%s",
        summary["status"],
        summary["found"],
        summary["newJobs"],
        len(reports),
    )
    return rows, summary, new_seen


def _log_company(report):
    log.critical(
        "ATS board %s/%s: status=%s fetched=%s kept=%s",
        report.get("ats"),
        report.get("slug"),
        report.get("status"),
        report.get("fetched"),
        report.get("kept"),
    )


def _summarize(rows, config, counts, reports, stopped, truncated, scraped_at):
    tally = {}
    for row in rows or []:
        key = row.get("sourceStatus") or "error"
        tally[key] = tally.get(key, 0) + 1
    found = tally.get("found", 0)
    if found and tally.get("blocked"):
        status = "partial"
    elif found:
        status = "ok"
    elif tally.get("blocked"):
        status = "blocked"
    elif tally.get("error"):
        status = "error"
    elif tally.get("robots_disallowed"):
        status = "robots_disallowed"
    else:
        status = "not_found"
    price = PRICES_USD[JOB_EVENT]
    max_spend = config.get("max_spend_usd", 5.0)
    affordable = min(found, int(round(max_spend * 1_000_000)) // int(round(price * 1_000_000)))
    return {
        "status": status,
        "pushed": len(rows or []),
        "found": found,
        "newJobs": sum(1 for row in rows or [] if row.get("decision") == "new"),
        "repeatJobs": sum(1 for row in rows or [] if row.get("decision") == "repeat"),
        "billedJobs": affordable,
        "notFound": tally.get("not_found", 0),
        "blocked": tally.get("blocked", 0),
        "errors": tally.get("error", 0),
        "robots": tally.get("robots_disallowed", 0),
        "mergedDuplicates": counts.get("duplicates", 0),
        "duplicateCompanies": counts.get("duplicateTargets", 0),
        "filteredOut": counts.get("filtered", 0),
        "skippedSeen": counts.get("skippedSeen", 0),
        "skippedBlockedHost": counts.get("skippedBlockedHost", 0),
        "truncated": bool(truncated),
        "maxItems": config.get("max_items"),
        "newSinceLastRun": bool(config.get("new_since_last_run")),
        "stateStore": config.get("state_store") or STATE_STORE,
        "chargeCapped": affordable < found,
        "maxSpendUsd": max_spend,
        "spendUsd": round(affordable * price, 6),
        "pricesUsd": dict(PRICES_USD),
        "companies": reports,
        "stopped": stopped,
        "scrapedAt": scraped_at,
    }
