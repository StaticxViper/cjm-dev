"""Salary, employment, date, and text parsing for listings.

SALARY_RE and EMPLOYMENT_RE started from the opp_finder job extractors and
were extended for hourly ranges, k-suffix annual pay, freelance, and monthly.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

SALARY_RE = re.compile(
    r"(\$?\d{2,3}(?:,\d{3})?(?:\.\d+)?\s*(?:-|to)\s*\$?\d{2,3}(?:,\d{3})?(?:\.\d+)?"
    r"(?:\s*(?:an hour|/hr|per hour|a year|/yr|per year|k))?|"
    r"\$?\d{2,3}(?:,\d{3})?\s*(?:an hour|/hr|per hour|a year|/yr|per year|k))",
    re.I,
)
EMPLOYMENT_RE = re.compile(
    r"\b(full[-\s]?time|part[-\s]?time|contract(?:or)?|freelance|temporary|temp|"
    r"intern(?:ship)?|seasonal)\b",
    re.I,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# A leading currency symbol is optional. Comma-grouped amounts ($80,000) and
# plain amounts ($60, 20k) both match. The k suffix is its own group.
_AMOUNT = r"[$€£]?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?"
_MONEY_RANGE_RE = re.compile(
    _AMOUNT + r"\s*(?:-|–|—|to)\s*" + _AMOUNT,
    re.I,
)
_MONEY_ONE_RE = re.compile(_AMOUNT, re.I)

_UNIT_MAP = {
    "hour": "hour",
    "hourly": "hour",
    "hr": "hour",
    "year": "year",
    "yearly": "year",
    "annual": "year",
    "annually": "year",
    "yr": "year",
    "month": "month",
    "monthly": "month",
    "project": "project",
}

_EMPLOYMENT_MAP = {
    "fulltime": "full_time",
    "full-time": "full_time",
    "full time": "full_time",
    "parttime": "part_time",
    "part-time": "part_time",
    "part time": "part_time",
    "contract": "contract",
    "contractor": "contract",
    "freelance": "freelance",
    "temporary": "temporary",
    "temp": "temporary",
    "internship": "internship",
    "intern": "internship",
    "seasonal": "temporary",
}

HOURS_PER_YEAR = 2080


def html_to_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<\s*p[^>]*>", "\n", text, flags=re.I)
    text = _TAG_RE.sub(" ", text)
    return text


def collapse_ws(value: str | None) -> str:
    return _WS_RE.sub(" ", (value or "").replace("\xa0", " ")).strip()


def snippet_text(value: str | None, limit: int = 500) -> str | None:
    text = collapse_ws(html_to_text(value))
    if not text:
        return None
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def normalize_unit(value: str | None) -> str | None:
    if not value:
        return None
    key = collapse_ws(str(value)).lower()
    return _UNIT_MAP.get(key)


def _detect_unit(text: str) -> str | None:
    low = text.lower()
    if re.search(r"\b(an hour|per hour|/hr|hourly)\b", low):
        return "hour"
    if re.search(r"\b(a month|per month|/mo|monthly)\b", low):
        return "month"
    if re.search(r"\b(a year|per year|/yr|annual(?:ly)?|yearly)\b", low):
        return "year"
    if re.search(r"\b(per project|project basis)\b", low):
        return "project"
    return None


def _money_number(token: str, k_suffix: str | None) -> float | None:
    cleaned = token.replace("$", "").replace("€", "").replace("£", "")
    cleaned = cleaned.replace(",", "").replace(" ", "")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if k_suffix:
        number *= 1000
    return number


def _currency_from_text(text: str) -> str | None:
    if "$" in text or re.search(r"\busd\b", text, re.I):
        return "USD"
    if "€" in text or re.search(r"\beur\b", text, re.I):
        return "EUR"
    if "£" in text or re.search(r"\bgbp\b", text, re.I):
        return "GBP"
    return None


def parse_salary_text(text: str | None) -> dict[str, object] | None:
    raw = collapse_ws(html_to_text(text))
    if not raw or not re.search(r"\d", raw):
        return None
    if not (
        SALARY_RE.search(raw)
        or _MONEY_RANGE_RE.search(raw)
        or _MONEY_ONE_RE.search(raw)
    ):
        return None
    unit = _detect_unit(raw)
    currency = _currency_from_text(raw)
    match = _MONEY_RANGE_RE.search(raw)
    k_used = False
    if match:
        lo = _money_number(match.group(1), match.group(2))
        hi = _money_number(match.group(3), match.group(4))
        k_used = bool(match.group(2) or match.group(4))
    else:
        one = _MONEY_ONE_RE.search(raw)
        if not one:
            return None
        lo = hi = _money_number(one.group(1), one.group(2))
        k_used = bool(one.group(2))
    if lo is None or hi is None:
        return None
    if hi < lo:
        lo, hi = hi, lo
    if unit is None:
        if k_used or hi >= 10000:
            unit = "year"
        elif hi <= 400:
            unit = "hour"
    if currency is None and unit in {"hour", "year", "month"}:
        currency = "USD"
    return {
        "salary_text": raw,
        "rate_min": lo,
        "rate_max": hi,
        "rate_unit": unit,
        "currency": currency,
    }


def positive_number(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def normalize_employment(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        found = [normalize_employment(item) for item in value]
        preferred = [item for item in found if item]
        if not preferred:
            return None
        for kind in ("contract", "freelance", "part_time", "full_time", "temporary", "internship"):
            if kind in preferred:
                return kind
        return preferred[0]
    text = collapse_ws(str(value)).lower().replace("_", "-")
    if text in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[text]
    match = EMPLOYMENT_RE.search(text)
    if not match:
        return None
    token = match.group(1).lower().replace("_", " ")
    token = re.sub(r"\s+", " ", token)
    compact = token.replace(" ", "").replace("-", "")
    if compact in _EMPLOYMENT_MAP:
        return _EMPLOYMENT_MAP[compact]
    return _EMPLOYMENT_MAP.get(token)


def infer_remote(location: str | None, tags: list[str] | None, snippet: str | None) -> bool | None:
    blob = " ".join(
        part for part in [location or "", " ".join(tags or []), snippet or ""] if part
    )
    low = blob.lower()
    if re.search(r"\b(remote|anywhere|worldwide|work from home|wfh)\b", low):
        return True
    if re.search(r"\b(on-?site|in[- ]office|in person)\b", low):
        return False
    return None


def parse_posted_date(value: object, scraped_at: datetime) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and value > 10_000_000:
        return _to_date(datetime.fromtimestamp(float(value), tz=timezone.utc))
    text = collapse_ws(str(value))
    if not text:
        return None
    if re.fullmatch(r"\d{10,13}", text):
        stamp = float(text)
        if len(text) >= 13:
            stamp /= 1000
        return _to_date(datetime.fromtimestamp(stamp, tz=timezone.utc))
    iso = text.replace("Z", "+00:00")
    try:
        return _to_date(datetime.fromisoformat(iso))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
        if parsed is not None:
            return _to_date(parsed)
    except (TypeError, ValueError, IndexError):
        pass
    relative = _relative_date(text, scraped_at)
    if relative:
        return relative
    return None


def _to_date(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _relative_date(text: str, scraped_at: datetime) -> str | None:
    low = text.lower()
    if low in {"today", "just now", "just posted"}:
        return _to_date(scraped_at)
    if low == "yesterday":
        return _to_date(scraped_at - timedelta(days=1))
    match = re.search(
        r"\b(\d+|a|an)\s+(minute|hour|day|week|month)s?\s+ago\b",
        low,
    )
    if not match:
        return None
    count_raw = match.group(1)
    count = 1 if count_raw in {"a", "an"} else int(count_raw)
    unit = match.group(2)
    if unit == "minute":
        delta = timedelta(minutes=count)
    elif unit == "hour":
        delta = timedelta(hours=count)
    elif unit == "day":
        delta = timedelta(days=count)
    elif unit == "week":
        delta = timedelta(days=7 * count)
    else:
        delta = timedelta(days=30 * count)
    return _to_date(scraped_at - delta)


def as_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for item in value:
            text = collapse_ws(str(item))
            if text:
                out.append(text)
        return out
    text = collapse_ws(str(value))
    return [text] if text else []


def join_location(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [collapse_ws(str(item)) for item in value if collapse_ws(str(item))]
        return ", ".join(parts) or None
    text = collapse_ws(str(value))
    return text or None
