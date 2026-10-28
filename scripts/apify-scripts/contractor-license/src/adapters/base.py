"""Shared license-row shape, name matching, and challenge detection.

Challenge markers match opp_finder_v2.browser.detection. A hit stops the
adapter. Nothing in this package solves a CAPTCHA or retries through a browser.
"""

from __future__ import annotations

import csv
import io
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

COMPANY_SUFFIXES = (
    "llc",
    "l.l.c",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "pllc",
    "lp",
    "llp",
    "pc",
    "p.c",
)

# Checked against the first slice of a response, not a whole license file.
CAPTCHA_MARKERS = (
    "verify you are human",
    "verify you are a human",
    "recaptcha",
    "hcaptcha",
    "cf-turnstile",
    "challenges.cloudflare.com",
    "cf-challenge",
    "attention required! | cloudflare",
    "cf-turnstile-response",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTI_SPACE = re.compile(r"\s+")
_CODE_PART = re.compile(r"[A-Za-z0-9]+")


class LicenseQuery:
    def __init__(self, state, license_no, name, trade, max_results):
        self.state = state or ""
        self.license_no = license_no or ""
        self.name = name or ""
        self.trade = trade or ""
        self.max_results = max_results


def license_key(value):
    text = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    if text.isdigit():
        text = text.lstrip("0") or "0"
    return text


def normalize_name(value):
    text = (value or "").strip().lower()
    text = _NON_ALNUM.sub(" ", text)
    tokens = _MULTI_SPACE.sub(" ", text).strip().split()
    while tokens and tokens[-1] in COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_matches(query_name, candidate):
    if not (query_name or "").strip():
        return True
    left = normalize_name(query_name)
    right = normalize_name(candidate)
    if len(left) < 2 or not right:
        return False
    if left in right:
        return True
    left_tokens = left.split()
    right_tokens = set(right.split())
    return bool(left_tokens) and all(token in right_tokens for token in left_tokens)


def _codes(text):
    parts = _CODE_PART.findall(text or "")
    codes = {part.upper() for part in parts if re.search(r"[A-Za-z]", part)}
    if len(parts) >= 2 and parts[0].isalpha() and parts[1].isdigit():
        codes.add((parts[0] + parts[1]).upper())
    return codes


def trade_matches(query_trade, class_text):
    """Match a classification code (B-1 == B1) or every word of a class name."""
    if not (query_trade or "").strip():
        return True
    if _codes(query_trade) & _codes(class_text):
        return True
    query_tokens = normalize_name(query_trade).split()
    class_tokens = set(normalize_name(class_text).split())
    if len(query_tokens) >= 2 and all(token in class_tokens for token in query_tokens):
        return True
    return False


def record_matches(query, license_no, names, class_text):
    if query.license_no and license_key(query.license_no) != license_key(license_no):
        return False
    if query.name and not any(name_matches(query.name, name) for name in names):
        return False
    if query.trade and not trade_matches(query.trade, class_text):
        return False
    if not query.license_no and not query.name and not query.trade:
        return False
    return True


def is_challenge(text, content_type=""):
    if content_type and "csv" in content_type.lower():
        return False
    sample = (text or "")[:8000].lower()
    if not sample:
        return False
    first = sample.splitlines()[0] if sample.splitlines() else sample
    if first.startswith("licenseno") or first.startswith('"licenseno"'):
        return False
    return any(marker in sample for marker in CAPTCHA_MARKERS)


def classify_transport(result):
    """Return a sourceStatus when the body cannot be parsed, else None."""
    result = result or {}
    error = result.get("error") or ""
    text = result.get("text") or ""
    content_type = result.get("content_type") or ""
    status = result.get("status")
    if error == "captcha" or is_challenge(text, content_type):
        return "captcha"
    if error == "robots_disallowed":
        return "robots_disallowed"
    if error:
        return "error"
    try:
        code = int(status) if status is not None else 200
    except (TypeError, ValueError):
        code = 0
    if code >= 400:
        return "captcha" if is_challenge(text, content_type) else "error"
    return None


def empty_fields():
    return {
        "license_no": "",
        "name": "",
        "status": "",
        "class": "",
        "issue_date": "",
        "expiry_date": "",
        "bond": "",
        "insurance": "",
        "address": "",
        "source_url": "",
    }


def status_row(query, source_status, error="", source_url=""):
    row = empty_fields()
    row.update({
        "state": query.state,
        "license_no": query.license_no,
        "name": query.name,
        "source_url": source_url,
        "sourceStatus": source_status,
        "ok": False,
        "error": error,
    })
    return row


def found_row(query, **fields):
    row = status_row(query, "found", "")
    row["ok"] = True
    row["error"] = ""
    for key, value in fields.items():
        row[key] = value or ""
    return row


def transport_row(query, result, messages, source_url=""):
    """Map a failed fetch to one dataset row, or return None when it is usable."""
    kind = classify_transport(result)
    if kind is None:
        return None
    if kind == "captcha":
        return status_row(query, "captcha", messages.get("captcha") or "captcha", source_url)
    if kind == "robots_disallowed":
        return status_row(query, "robots_disallowed", "robots_disallowed", source_url)
    error = (result or {}).get("error") or ""
    if error == "request_cap":
        message = "Request cap reached before the source answered."
    elif error:
        message = str(error)[:300]
    else:
        message = f"HTTP {(result or {}).get('status')}"
    return status_row(query, "error", message, source_url)


def outcome(rows, truncated=False):
    return {"rows": rows, "truncated": truncated}


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href")
        self._chunks = []

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append((self._href, "".join(self._chunks).strip()))
        self._href = None
        self._chunks = []

    def handle_data(self, data):
        if self._href is not None:
            self._chunks.append(data)


def html_links(html, page_url):
    parser = _LinkParser()
    parser.feed(html or "")
    parser.close()
    resolved = []
    for href, text in parser.links:
        if not href:
            continue
        resolved.append((urljoin(page_url, href), text))
    return resolved


def csv_dicts(text, header_marker):
    """Yield row dicts, skipping preamble lines before the real header."""
    lines = (text or "").splitlines()
    start = None
    marker = (header_marker or "").lower()
    for index, line in enumerate(lines):
        if marker and marker in line.lower():
            start = index
            break
    if start is None:
        return
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    for raw in reader:
        if not raw:
            continue
        yield {
            (key or "").strip(): (value or "").strip()
            for key, value in raw.items()
            if key is not None
        }


def join_address(*parts):
    return ", ".join(part.strip() for part in parts if part and str(part).strip())


def take_match(found, seen, query, row):
    """Append a matching license unless the cap is already full.

    Returns True when this match proves there are more rows than max_results.
    """
    key = license_key(row.get("license_no"))
    if key and key in seen:
        for index, current in enumerate(found):
            if license_key(current.get("license_no")) == key:
                try:
                    from ..dedupe import merge_license_rows
                except ImportError:
                    from dedupe import merge_license_rows
                found[index] = merge_license_rows(current, row)
                break
        return False
    if len(found) >= query.max_results:
        return True
    if key:
        seen.add(key)
    found.append(row)
    return False
