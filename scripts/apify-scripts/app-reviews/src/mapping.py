"""Map Actor input onto iTunes customer-review rows.

The RSS feed is most-recent first. The first entry is often the app itself
and has no im:rating, so it is skipped. Pages stop when the page is empty,
a page repeats review ids, maxItems is filled, or the oldest review on the
page is before ``since``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    from .runtime import is_block, iso_now, looks_json
    from .sources import MAX_PAGES, lookup_url, normalize_app_id, reviews_url
    from .spend import PRICES_USD, REVIEW_EVENT, SENTIMENT_EVENT, to_micros
except ImportError:
    from runtime import is_block, iso_now, looks_json
    from sources import MAX_PAGES, lookup_url, normalize_app_id, reviews_url
    from spend import PRICES_USD, REVIEW_EVENT, SENTIMENT_EVENT, to_micros


log = logging.getLogger("apify")

MAX_IDS = 20
_COUNTRY = re.compile(r"^[a-z]{2}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WORD = re.compile(r"[a-z']+")

TEXT_FIELDS = (
    "app",
    "appId",
    "store",
    "country",
    "reviewId",
    "title",
    "text",
    "version",
    "date",
    "author",
    "url",
)

POSITIVE = frozenset(
    "amazing awesome best excellent fantastic good great happy helpful love "
    "nice perfect recommend wonderful".split()
)
NEGATIVE = frozenset(
    "annoying awful bad broken bug bugs crash crashes disappointing hate "
    "horrible poor slow terrible useless waste worst".split()
)

_CONSENT = (
    "consent.google.com",
    "before you continue to google",
    "we value your privacy",
)


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


def _flag(value):
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    return [text] if text else []


def _country(raw):
    if raw.get("country") is None or str(raw.get("country")).strip() == "":
        return "us", ""
    text = str(raw.get("country")).strip().lower()
    if not _COUNTRY.fullmatch(text):
        return "", f"country must be a 2-letter storefront like us, not {raw.get('country')!r}."
    return text, ""


def _since(raw):
    value = raw.get("since")
    if value is None or str(value).strip() == "":
        return None, ""
    text = str(value).strip()
    if not _DAY.fullmatch(text):
        return None, f"since must be YYYY-MM-DD, not {value!r}."
    return text, ""


def _app_ids(raw):
    ids = []
    invalid = []
    seen = set()
    duplicates = 0
    for item in _as_list(raw.get("appStoreIds")):
        app_id = normalize_app_id(item)
        if not app_id:
            invalid.append(item)
            continue
        if app_id in seen:
            duplicates += 1
            continue
        seen.add(app_id)
        ids.append(app_id)
    return ids, invalid, duplicates


def _play_ids(raw):
    ids = []
    seen = set()
    duplicates = 0
    for item in _as_list(raw.get("playIds")):
        text = str(item).strip()
        if not text:
            continue
        if text in seen:
            duplicates += 1
            continue
        seen.add(text)
        ids.append(text)
    return ids, duplicates


def actor_input_to_config(actor_input):
    raw = actor_input or {}
    country, country_error = _country(raw)
    since, since_error = _since(raw)
    app_ids, invalid, duplicate_ids = _app_ids(raw)
    play_ids, duplicate_play = _play_ids(raw)
    error = country_error or since_error
    if not error:
        if not app_ids and not play_ids and not invalid:
            error = "Add at least one App Store id under appStoreIds, or a Play package under playIds."
        elif len(app_ids) > MAX_IDS:
            error = f"At most {MAX_IDS} App Store ids per run. This input has {len(app_ids)}."
        elif len(play_ids) > MAX_IDS:
            error = f"At most {MAX_IDS} Play packages per run. This input has {len(play_ids)}."
    return {
        "app_ids": app_ids,
        "invalid_ids": invalid,
        "play_ids": play_ids,
        "duplicate_ids": duplicate_ids + duplicate_play,
        "country": country,
        "since": since,
        "sentiment": _flag(raw.get("sentiment")),
        "max_items": _bounded_int(raw.get("maxItems"), 100, 1, 1000),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 1.0, 1.0, 10.0),
        "max_spend_usd": _bounded_float(raw.get("maxSpendUsd"), 5.0, 0.01, 100.0),
        "error": error,
    }


# ---------------------------------------------------------------- helpers


def _clean(value):
    return str(value or "").replace("\xa0", " ").strip()


def _clip(value, limit):
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _label(node):
    if isinstance(node, dict):
        value = node.get("label")
    else:
        value = node
    if value is None:
        return ""
    return _clean(value)


def calendar_day(value):
    """Calendar date in the value's own offset, or the UTC date when it has none."""
    text = _clean(value)
    if not text:
        return ""
    if _DAY.fullmatch(text):
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
        return match.group(1) if match else ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.date().isoformat()


def sentiment_of(title, text):
    """Local lexicon score in -1..1. No network and no model call."""
    words = _WORD.findall(f"{title or ''} {text or ''}".lower())
    pos = sum(1 for word in words if word in POSITIVE)
    neg = sum(1 for word in words if word in NEGATIVE)
    total = pos + neg
    if not total:
        return "neutral", 0.0
    score = max(-1.0, min(1.0, round((pos - neg) / total, 4)))
    if score > 0:
        return "positive", score
    if score < 0:
        return "negative", score
    return "neutral", score


def _entries(payload):
    if not isinstance(payload, dict):
        return None
    feed = payload.get("feed")
    if not isinstance(feed, dict):
        return None
    entry = feed.get("entry")
    if entry is None:
        return []
    if isinstance(entry, dict):
        return [entry]
    if isinstance(entry, list):
        return [item for item in entry if isinstance(item, dict)]
    return None


def _rating(entry):
    raw = _label(entry.get("im:rating"))
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if 1 <= value <= 5:
        return value
    return None


def _author(entry):
    author = entry.get("author")
    if isinstance(author, dict):
        return _label(author.get("name"))
    return _label(author)


def _href(entry):
    link = entry.get("link")
    if isinstance(link, dict):
        return _clean((link.get("attributes") or {}).get("href"))
    if isinstance(link, list):
        for item in link:
            if isinstance(item, dict):
                href = _clean((item.get("attributes") or {}).get("href"))
                if href:
                    return href
    return ""


def parse_lookup(payload, app_id):
    """App name and store URL, or ``{'found': False}`` when resultCount is 0."""
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if payload.get("resultCount") == 0 or results == []:
        return {"found": False}
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    first = results[0]
    return {
        "found": True,
        "app": _clip(first.get("trackName"), 200) or str(app_id),
        "url": _clean(first.get("trackViewUrl")),
    }


def parse_reviews(payload):
    """Review dicts in feed order. Entries without im:rating are skipped."""
    entries = _entries(payload)
    if entries is None:
        return None
    reviews = []
    for entry in entries:
        rating = _rating(entry)
        if rating is None:
            continue
        review_id = _clip(_label(entry.get("id")), 200)
        if not review_id:
            continue
        reviews.append({
            "reviewId": review_id,
            "rating": rating,
            "title": _clip(_label(entry.get("title")), 300),
            "text": _clip(_label(entry.get("content")), 8000),
            "version": _clip(_label(entry.get("im:version")), 80),
            "date": _label(entry.get("updated")),
            "author": _clip(_author(entry), 200),
            "url": _clip(_href(entry), 500),
        })
    return reviews


# ---------------------------------------------------------------- rows


def _blank_row(status, error, scraped_at, store="", app_id="", country="", url="", decision=""):
    row = {key: "" for key in TEXT_FIELDS}
    row.update({
        "store": store,
        "appId": app_id,
        "country": country,
        "url": url,
        "rating": None,
        "sourceStatus": status,
        "decision": decision or status,
        "ok": False,
        "error": error,
        "scrapedAt": scraped_at,
    })
    return row


def _dataset_row(review, app_name, app_id, country, app_url, scraped_at, sentiment):
    row = _blank_row("ok", "", scraped_at, "appstore", app_id, country, decision="review")
    row.update({
        "app": app_name,
        "reviewId": review["reviewId"],
        "rating": review["rating"],
        "title": review["title"],
        "text": review["text"],
        "version": review["version"],
        "date": review["date"],
        "author": review["author"],
        "url": review["url"] or app_url,
        "sourceStatus": "ok",
        "decision": "review",
        "ok": True,
        "error": "",
    })
    if sentiment:
        label, score = sentiment_of(review["title"], review["text"])
        row["sentiment"] = label
        row["sentimentScore"] = score
    return row


def billable_row(row):
    row = row or {}
    return row.get("sourceStatus") == "ok" and row.get("ok") is True and bool(row.get("reviewId"))


def is_hard_block(result):
    """401, 403, 429, a challenge page, or a clear consent wall. robots is not a block."""
    if is_block(result):
        return True
    if looks_json(result):
        return False
    text = ((result or {}).get("text") or "").lower()
    return any(marker in text for marker in _CONSENT)


def outcome(result):
    """ok, not_found, blocked, robots, or error for one response."""
    if not result:
        return "error"
    if result.get("error") in ("robots_disallowed", "robots_unavailable"):
        return "robots"
    if is_hard_block(result):
        return "blocked"
    status = int(result.get("status") or 0)
    if status == 404:
        return "not_found"
    if result.get("error") or status >= 400 or status == 0:
        return "error"
    if not looks_json(result):
        return "error"
    return "ok"


def _host(url):
    return urlparse(url or "").netloc or "the store"


def _blocked_message(result):
    status = int((result or {}).get("status") or 0)
    if status in (401, 403, 429):
        what = f"HTTP {status}"
    else:
        what = "a consent, CAPTCHA, or challenge page"
    return (
        f"Blocked by {_host((result or {}).get('url'))} ({what}). This Actor does not use a proxy "
        "or a CAPTCHA solver, so the run stopped. This row is not charged."
    )


def _robots_message(result):
    if (result or {}).get("error") == "robots_unavailable":
        detail = result.get("detail") or "fetch failed"
        return (
            f"robots.txt could not be read ({detail}). This host is skipped for the run. "
            "This row is not charged."
        )
    return "robots.txt disallows this URL. This row is not charged."


def _failure_message(result):
    if result.get("error"):
        return str(result["error"])
    status = int(result.get("status") or 0)
    if 200 <= status < 300:
        return "invalid_json: the store answered without a JSON body."
    return f"HTTP {status}" if status else "fetch_failed"


def _play_message(play_ids):
    shown = ", ".join(play_ids[:5])
    more = f" and {len(play_ids) - 5} more" if len(play_ids) > 5 else ""
    return (
        "Google Play reviews are deferred because unproxied Play blocks at volume. "
        f"No Play request was sent for {shown}{more}. "
        "This Actor does not use a proxy, a browser, cookies, or a batchexecute session."
    )


def _charge_events(config):
    if config.get("sentiment"):
        return (REVIEW_EVENT, SENTIMENT_EVENT)
    return (REVIEW_EVENT,)


def scrape(config, fetch, now=None):
    """Return (rows, summary). Review rows come first, then free status rows."""
    scraped_at = now or iso_now()
    if config.get("error"):
        row = _blank_row("error", config["error"], scraped_at)
        return [row], _summarize([row], config, {}, [], "", False, scraped_at)

    kept = []
    status_rows = []
    seen = set()
    counts = {"duplicates": 0, "filtered": 0}
    reports = []
    truncated = False
    stopped = ""
    country = config.get("country") or ""
    sentiment = bool(config.get("sentiment"))

    for item in config.get("invalid_ids") or []:
        status_rows.append(_blank_row(
            "error", f"Not an App Store id: {item!r}", scraped_at, "appstore", "", country,
        ))

    for app_id in config.get("app_ids") or []:
        if stopped:
            break
        if len(kept) >= config["max_items"]:
            truncated = True
            break
        report = {"store": "appstore", "appId": app_id, "status": "ok", "fetched": 0, "kept": 0}
        lookup = lookup_url(app_id, country)
        result = fetch(lookup)
        kind = outcome(result)
        if kind == "blocked":
            status_rows.append(_blank_row(
                "blocked", _blocked_message(result), scraped_at, "appstore", app_id, country, lookup, "blocked",
            ))
            report["status"] = "blocked"
            reports.append(report)
            _log_app(report)
            stopped = "blocked"
            break
        if kind != "ok":
            report["status"] = kind
            reports.append(report)
            _log_app(report)
            _append_miss(status_rows, kind, result, scraped_at, app_id, country, lookup)
            continue

        try:
            payload = json.loads(result.get("text") or "null")
        except json.JSONDecodeError:
            report["status"] = "error"
            reports.append(report)
            _log_app(report)
            status_rows.append(_blank_row(
                "error", "invalid_json", scraped_at, "appstore", app_id, country, lookup,
            ))
            continue
        parsed = parse_lookup(payload, app_id)
        if parsed is None:
            report["status"] = "error"
            reports.append(report)
            _log_app(report)
            status_rows.append(_blank_row(
                "error", "unexpected_payload", scraped_at, "appstore", app_id, country, lookup,
            ))
            continue
        if not parsed["found"]:
            report["status"] = "not_found"
            reports.append(report)
            _log_app(report)
            status_rows.append(_blank_row(
                "not_found",
                f"iTunes lookup returned no app for id {app_id} in the {country} storefront.",
                scraped_at, "appstore", app_id, country, lookup,
            ))
            continue

        app_name = parsed["app"]
        app_url = parsed["url"]
        page = 1
        app_status = "ok"
        while len(kept) < config["max_items"] and page <= MAX_PAGES:
            page_url = reviews_url(app_id, country, page)
            result = fetch(page_url)
            kind = outcome(result)
            if kind == "blocked":
                status_rows.append(_blank_row(
                    "blocked", _blocked_message(result), scraped_at,
                    "appstore", app_id, country, page_url, "blocked",
                ))
                app_status = "blocked"
                stopped = "blocked"
                break
            if kind != "ok":
                app_status = kind
                _append_miss(status_rows, kind, result, scraped_at, app_id, country, page_url, app_name)
                break
            try:
                payload = json.loads(result.get("text") or "null")
            except json.JSONDecodeError:
                app_status = "error"
                status_rows.append(_blank_row(
                    "error", "invalid_json", scraped_at, "appstore", app_id, country, page_url,
                ))
                break
            reviews = parse_reviews(payload)
            if reviews is None:
                app_status = "error"
                status_rows.append(_blank_row(
                    "error", "unexpected_payload", scraped_at, "appstore", app_id, country, page_url,
                ))
                break
            if not reviews:
                if page == 1 and report["kept"] == 0:
                    app_status = "empty"
                break

            report["fetched"] += len(reviews)
            days = []
            repeated = False
            for review in reviews:
                day = calendar_day(review["date"])
                if day:
                    days.append(day)
                key = ("appstore", app_id, review["reviewId"])
                if key in seen:
                    repeated = True
                    counts["duplicates"] += 1
                    continue
                seen.add(key)
                if config.get("since") and day and day < config["since"]:
                    counts["filtered"] += 1
                    continue
                if len(kept) >= config["max_items"]:
                    truncated = True
                    break
                kept.append(_dataset_row(
                    review, app_name, app_id, country, app_url, scraped_at, sentiment,
                ))
                report["kept"] += 1
            oldest = min(days) if days else ""
            if len(kept) >= config["max_items"]:
                truncated = True
                break
            if repeated:
                break
            if config.get("since") and oldest and oldest < config["since"]:
                break
            page += 1
        else:
            if page > MAX_PAGES and len(kept) < config["max_items"]:
                truncated = True
        if app_status == "ok" and report["fetched"] == 0:
            app_status = "empty"
        if app_status == "empty" and report["kept"] == 0:
            status_rows.append(_blank_row(
                "not_found",
                f"No customer reviews for {app_name}.",
                scraped_at, "appstore", app_id, country, app_url,
            ))
            app_status = "not_found"
        report["status"] = app_status
        reports.append(report)
        _log_app(report)
        if stopped:
            break

    if not stopped and config.get("play_ids"):
        play_ids = config["play_ids"]
        status_rows.append(_blank_row(
            "blocked", _play_message(play_ids), scraped_at, "play",
            play_ids[0] if len(play_ids) == 1 else "", country, decision="blocked",
        ))
        reports.append({
            "store": "play",
            "appId": play_ids[0] if len(play_ids) == 1 else "",
            "status": "blocked",
            "fetched": 0,
            "kept": 0,
        })
        stopped = "blocked"

    rows = list(kept)
    rows.extend(status_rows)
    if not rows:
        rows.append(_blank_row("not_found", "No reviews matched these apps.", scraped_at, country=country))
    summary = _summarize(rows, config, counts, reports, stopped, truncated, scraped_at)
    log.critical(
        "App reviews SUMMARY: status=%s found=%s apps=%s",
        summary["status"],
        summary["found"],
        len(reports),
    )
    return rows, summary


def _append_miss(status_rows, kind, result, scraped_at, app_id, country, url, app_name=""):
    if kind == "robots":
        status_rows.append(_blank_row(
            "robots", _robots_message(result), scraped_at, "appstore", app_id, country, url,
        ))
        return
    if kind == "not_found":
        status_rows.append(_blank_row(
            "not_found", _failure_message(result), scraped_at, "appstore", app_id, country, url,
        ))
        return
    status_rows.append(_blank_row(
        "error", _failure_message(result), scraped_at, "appstore", app_id, country, url,
    ))
    if app_name:
        status_rows[-1]["app"] = app_name


def _log_app(report):
    log.critical(
        "App %s/%s: status=%s fetched=%s kept=%s",
        report.get("store"),
        report.get("appId"),
        report.get("status"),
        report.get("fetched"),
        report.get("kept"),
    )


def _summarize(rows, config, counts, reports, stopped, truncated, scraped_at):
    tally = {}
    for row in rows or []:
        key = row.get("sourceStatus") or "error"
        tally[key] = tally.get(key, 0) + 1
    found = tally.get("ok", 0)
    if found and tally.get("blocked"):
        status = "partial"
    elif found:
        status = "ok"
    elif tally.get("blocked"):
        status = "blocked"
    elif tally.get("error"):
        status = "error"
    elif tally.get("robots"):
        status = "robots"
    else:
        status = "not_found"
    events = _charge_events(config)
    unit = sum(to_micros(PRICES_USD[name]) for name in events)
    room = to_micros(config.get("max_spend_usd", 5.0))
    affordable = found if not unit else min(found, room // unit)
    sentiment_on = bool(config.get("sentiment"))
    return {
        "status": status,
        "pushed": len(rows or []),
        "found": found,
        "billedReviews": affordable,
        "billedSentiment": affordable if sentiment_on else 0,
        "notFound": tally.get("not_found", 0),
        "blocked": tally.get("blocked", 0),
        "errors": tally.get("error", 0),
        "robots": tally.get("robots", 0),
        "mergedDuplicates": counts.get("duplicates", 0),
        "duplicateApps": counts.get("duplicateTargets", config.get("duplicate_ids", 0)),
        "filteredOut": counts.get("filtered", 0),
        "truncated": bool(truncated),
        "maxItems": config.get("max_items"),
        "sentiment": sentiment_on,
        "chargeCapped": affordable < found,
        "heldBackReviews": max(0, found - affordable),
        "maxSpendUsd": config.get("max_spend_usd", 5.0),
        "spendUsd": round(affordable * unit / 1_000_000, 6),
        "pricesUsd": dict(PRICES_USD),
        "apps": reports,
        "stopped": stopped,
        "scrapedAt": scraped_at,
    }
