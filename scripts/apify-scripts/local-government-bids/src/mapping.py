"""Map Actor input onto local bid rows.

Los Angeles and Montgomery County are the verified feeds. Any other source
id returns one free status row and is not requested. The date window is the
posted or issuance date. The JSON array is read until maxItems bids are
complete, then the body stream is closed.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta

try:
    from .runtime import is_block, iso_now
    from .sources import (
        DATE_WINDOW_DAYS,
        DEFAULT_SOURCE,
        MAX_PAGES,
        MAX_SOURCES,
        MAX_SPAN_DAYS,
        PAGE_SIZE,
        POSTAL,
        VERIFIED,
        soda_url,
        unsupported_reason,
        where_clause,
    )
    from .state import opportunity_key
    from .stream import MAX_STREAM_BYTES, ArrayReader
except ImportError:
    from runtime import is_block, iso_now
    from sources import (
        DATE_WINDOW_DAYS,
        DEFAULT_SOURCE,
        MAX_PAGES,
        MAX_SOURCES,
        MAX_SPAN_DAYS,
        PAGE_SIZE,
        POSTAL,
        VERIFIED,
        soda_url,
        unsupported_reason,
        where_clause,
    )
    from state import opportunity_key
    from stream import MAX_STREAM_BYTES, ArrayReader


log = logging.getLogger("apify")

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DESCRIPTION_LIMIT = 500
TITLE_LIMIT = 300

REVIEW_ASK = (
    "If these local bid leads were useful, a short Apify Store rating helps other contractors find this feed."
)

BID_FIELDS = (
    "source",
    "sourceUrl",
    "agency",
    "title",
    "solicitationId",
    "category",
    "naics",
    "state",
    "city",
    "postedDate",
    "dueDate",
    "estimatedValue",
    "status",
    "description",
    "contactName",
    "contactEmail",
    "decision",
    "error",
    "scrapedAt",
)


def clean(value):
    return " ".join(str(value or "").split())


def clip(value, limit):
    text = clean(value)
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def iso_day(value):
    text = clean(value)
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return ""
    day = text[:10]
    if not _DAY.match(day) or day.startswith("9999"):
        return ""
    return day


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


def _parse_day(value):
    text = clean(value)
    if not text:
        return None, ""
    if not _DAY.match(text):
        return None, "dateFrom and dateTo must be YYYY-MM-DD."
    try:
        return date.fromisoformat(text), ""
    except ValueError:
        return None, "dateFrom and dateTo must be YYYY-MM-DD."


def _sources(raw):
    if raw is None:
        incoming = [DEFAULT_SOURCE]
    else:
        incoming = _as_list(raw)
    chosen = []
    for item in incoming:
        source_id = "".join(ch for ch in item.lower() if ch.isalnum() or ch in "-_")
        if source_id and source_id not in chosen:
            chosen.append(source_id)
        if len(chosen) >= MAX_SOURCES:
            break
    return chosen or [DEFAULT_SOURCE]


def _keywords(raw):
    chosen = []
    for item in _as_list(raw)[:8]:
        safe = "".join(ch for ch in item.upper() if ch.isalnum() or ch == " ")
        safe = " ".join(safe.split())[:40]
        if len(safe) >= 2 and safe not in chosen:
            chosen.append(safe)
    return chosen


def _state_filter(raw):
    text = clean(raw).upper()
    if not text:
        return "", ""
    if text not in POSTAL:
        return "", "state must be a two-letter US postal code."
    return text, ""


def _store_name(value):
    text = clean(value) or "local-government-bids-state"
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch in "-_")
    return (cleaned or "local-government-bids-state")[:63]


def _token(raw):
    raw = raw or {}
    if "appToken" in raw:
        return clean(raw.get("appToken"))[:80]
    return clean(os.environ.get("SOCRATA_APP_TOKEN"))[:80]


def actor_input_to_config(raw, today=None):
    raw = raw or {}
    today = today or date.today()
    start, start_error = _parse_day(raw.get("dateFrom"))
    end, end_error = _parse_day(raw.get("dateTo"))
    state, state_error = _state_filter(raw.get("state"))
    error = start_error or end_error or state_error
    if not error:
        if (start is None) ^ (end is None):
            error = "Set both dateFrom and dateTo, or leave both empty for the last 14 days."
        elif start is None:
            end = today
            start = today - timedelta(days=DATE_WINDOW_DAYS - 1)
        elif end < start:
            error = "dateTo is before dateFrom."
        elif (end - start).days + 1 > MAX_SPAN_DAYS:
            error = f"The date window cannot exceed {MAX_SPAN_DAYS} days."
    return {
        "sources": _sources(raw.get("sources") if "sources" in raw else None),
        "state": state,
        "keywords": _keywords(raw.get("keywords")),
        "date_from": start.isoformat() if start else "",
        "date_to": end.isoformat() if end else "",
        "max_items": _bounded_int(raw.get("maxItems"), 25, 1, 500),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 1.0, 1.0, 10.0),
        "max_spend_usd": _bounded_float(raw.get("maxSpendUsd"), 0.50, 0.0, 100.0),
        "new_since_last_run": bool(raw.get("newSinceLastRun")),
        "state_store": _store_name(raw.get("stateStoreName")),
        "app_token": _token(raw),
        "error": error,
        "_page_size": PAGE_SIZE,
        "_max_bytes": MAX_STREAM_BYTES,
    }


def billable_row(row):
    row = row or {}
    return row.get("decision") == "opportunity" and bool(row.get("solicitationId")) and row.get("ok") is True


def _base_row(stamp):
    row = {field: "" for field in BID_FIELDS}
    row["ok"] = False
    row["scrapedAt"] = stamp
    return row


def status_row(state, status, message, stamp, source="", source_url="", city=""):
    row = _base_row(stamp)
    row.update({
        "state": state or "",
        "city": city or "",
        "source": source or "",
        "sourceUrl": source_url or "",
        "status": status,
        "decision": status,
        "error": message or "",
        "ok": False,
    })
    return row


def _link(value):
    if isinstance(value, dict):
        return clean(value.get("url"))
    return clean(value)


def _contact(value):
    """A published name stays a name. A single email token stays an email."""
    text = clean(value)
    if text.count("@") == 1 and " " not in text:
        return "", text
    return text, ""


def _category(*values):
    chosen = []
    for value in values:
        text = clean(value)
        if text and text.lower() != "none" and text not in chosen:
            chosen.append(text)
    return "; ".join(chosen)


def matches_keywords(feed, obj, keywords):
    if not keywords:
        return True
    blob = " ".join(clean(obj.get(column)) for column in feed["text_columns"]).upper()
    return all(word in blob for word in keywords)


def build_row(feed, obj, stamp):
    kind = feed["kind"]
    if kind == "la":
        solicitation_id = clean(obj.get("rampid"))
        title = clip(obj.get("title"), TITLE_LIMIT)
        description = ""
        category = _category(obj.get("type"), obj.get("category"))
        posted = iso_day(obj.get("bidpost"))
        due = iso_day(obj.get("closedate"))
        bid_status = clean(obj.get("stagename"))
        agency = clean(obj.get("department"))
        contact_name, contact_email = "", ""
        source_url = _link(obj.get("url")) or feed["page"]
        estimated = ""
    elif kind == "montgomery":
        solicitation_id = clean(obj.get("number"))
        text = clean(obj.get("description"))
        title = clip(text, TITLE_LIMIT)
        description = clip(text, DESCRIPTION_LIMIT)
        category = _category(obj.get("type"))
        posted = iso_day(obj.get("issuancedate"))
        due = iso_day(obj.get("closingdate"))
        bid_status = clean(obj.get("cancelledpostponed")) or clean(obj.get("status"))
        agency = clean(obj.get("department"))
        contact_name, contact_email = _contact(obj.get("deptcontact") or obj.get("buyer"))
        source_url = _link(obj.get("bidtab")) or feed["page"]
        estimated = ""
    else:
        return None
    if not solicitation_id or not title:
        return None
    row = _base_row(stamp)
    row.update({
        "source": feed["source"],
        "sourceUrl": source_url,
        "agency": agency,
        "title": title,
        "solicitationId": solicitation_id,
        "category": category,
        "naics": "",
        "state": feed["state"],
        "city": feed.get("city") or "",
        "postedDate": posted,
        "dueDate": due,
        "estimatedValue": estimated,
        "status": bid_status,
        "description": description,
        "contactName": contact_name,
        "contactEmail": contact_email,
        "decision": "opportunity",
        "error": "",
        "ok": True,
    })
    return row


def _close_chunks(chunks):
    closer = getattr(chunks, "close", None)
    if closer:
        try:
            closer()
        except Exception:
            log.info("Closing the bid stream raised; the read already stopped.")


def collect_source(feed, config, fetch, seen, want, stamp):
    """Return ``(rows, report)``. ``rows`` is bids or one status row."""
    page_size = int(config.get("_page_size") or PAGE_SIZE)
    max_bytes = int(config.get("_max_bytes") or MAX_STREAM_BYTES)
    start = config["date_from"]
    end = config["date_to"]
    where = where_clause(feed, start, end, config["keywords"])
    kept = []
    skipped = 0
    seen_now = set()
    offset = 0
    truncated = False
    stop_early = False
    pages = 0
    failure = None

    while pages < MAX_PAGES and len(kept) < want and not stop_early:
        pages += 1
        url = soda_url(feed["endpoint"], where, page_size, offset, feed["order"])
        result = fetch({"url": url, "stream": True}) or {}
        error = result.get("error")
        if error in {"robots_disallowed", "robots_unavailable"}:
            message = (
                "robots.txt disallows this open-data URL, so the source was skipped."
                if error == "robots_disallowed"
                else "robots.txt could not be read, so the source was skipped."
            )
            return [status_row(
                feed["state"], "robots", message, stamp, feed["source"], feed["page"], feed.get("city") or "",
            )], {"source": feed["id"], "status": "robots", "bids": 0, "skippedSeen": 0}
        if error in {"statewide_export", "missing_limit"}:
            return [status_row(
                feed["state"], "error",
                "The request was refused because it was not a bounded open-data page.",
                stamp, feed["source"], feed["page"], feed.get("city") or "",
            )], {"source": feed["id"], "status": "error", "bids": 0, "skippedSeen": 0}
        if is_block(result):
            return [status_row(
                feed["state"], "blocked",
                "The open-data server blocked the request. No proxy retry is attempted.",
                stamp, feed["source"], feed["page"], feed.get("city") or "",
            )], {"source": feed["id"], "status": "blocked", "bids": 0, "skippedSeen": 0}
        status = int(result.get("status") or 0)
        if error or not 200 <= status < 300:
            failure = error or result.get("detail") or f"Open data answered HTTP {status}."
            truncated = bool(kept)
            break
        chunks = result.get("chunks")
        if chunks is None and result.get("text"):
            chunks = [result["text"].encode("utf-8")]
        reader = ArrayReader(chunks, max_bytes)
        rows_on_page = 0
        try:
            for obj in reader:
                rows_on_page += 1
                if not isinstance(obj, dict) or not matches_keywords(feed, obj, config["keywords"]):
                    continue
                row = build_row(feed, obj, stamp)
                if row is None:
                    continue
                key = opportunity_key(row["source"], row["solicitationId"])
                if key in seen_now:
                    continue
                if seen is not None and key in seen:
                    skipped += 1
                    continue
                seen_now.add(key)
                kept.append(row)
                if len(kept) >= want:
                    stop_early = True
                    break
        finally:
            _close_chunks(chunks)
        if reader.error and not kept:
            failure = reader.error
            break
        if reader.truncated:
            truncated = True
            break
        if stop_early or rows_on_page < page_size:
            break
        offset += rows_on_page
    else:
        if pages >= MAX_PAGES and len(kept) < want:
            truncated = True

    if failure and not kept:
        return [status_row(
            feed["state"], "error", clean(failure)[:300], stamp, feed["source"], feed["page"], feed.get("city") or "",
        )], {"source": feed["id"], "status": "error", "bids": 0, "skippedSeen": skipped}
    if not kept:
        if skipped:
            message = f"No new bids in {feed['name']} since the last run."
        else:
            message = f"No bids in {feed['name']} from {start} through {end}."
        return [status_row(
            feed["state"], "not_found", message, stamp, feed["source"], feed["page"], feed.get("city") or "",
        )], {"source": feed["id"], "status": "not_found", "bids": 0, "skippedSeen": skipped}
    return kept, {
        "source": feed["id"],
        "status": "ok",
        "bids": len(kept),
        "skippedSeen": skipped,
        "truncated": truncated,
    }


def _summarize(rows, reports, config, skipped, truncated, stamp):
    bids = [row for row in rows if billable_row(row)]
    statuses = [row.get("status") for row in rows if not billable_row(row)]

    def count(name):
        return sum(1 for status in statuses if status == name)

    if bids:
        status = "ok"
    elif count("error"):
        status = "error"
    elif count("blocked"):
        status = "blocked"
    elif count("robots"):
        status = "robots"
    elif count("unsupported") and not count("not_found"):
        status = "unsupported"
    elif count("not_found"):
        status = "not_found"
    else:
        status = "ok"
    summary = {
        "status": status,
        "opportunities": len(bids),
        "skippedSeen": skipped,
        "truncated": truncated,
        "unsupported": count("unsupported"),
        "skipped": count("skipped"),
        "notFound": count("not_found"),
        "blocked": count("blocked"),
        "robots": count("robots"),
        "errors": count("error"),
        "sources": reports,
        "dateFrom": config.get("date_from") or "",
        "dateTo": config.get("date_to") or "",
        "state": config.get("state") or "",
        "keywords": list(config.get("keywords") or []),
        "newSinceLastRun": bool(config.get("new_since_last_run")),
        "stateStore": config.get("state_store") or "",
        "maxItems": config.get("max_items"),
        "scrapedAt": stamp,
    }
    return summary


def scrape(config, fetch, seen=None, now=None):
    stamp = now or iso_now()
    if config.get("error"):
        row = status_row("", "error", config["error"], stamp)
        summary = _summarize([row], [], config, 0, False, stamp)
        summary["status"] = "error"
        summary["errors"] = 1
        return [row], summary
    rows = []
    reports = []
    skipped = 0
    truncated = False
    want = config["max_items"]
    for source_id in config["sources"]:
        feed = VERIFIED.get(source_id)
        if feed is None:
            rows.append(status_row("", "unsupported", unsupported_reason(source_id), stamp, source_id))
            reports.append({"source": source_id, "status": "unsupported", "bids": 0, "skippedSeen": 0})
            continue
        if feed.get("requires_token") and not config.get("app_token"):
            message = (
                f"{feed['name']} needs a Socrata app token. It was skipped, and the run continued."
            )
            rows.append(status_row(
                feed["state"], "skipped", message, stamp, feed["source"], feed["page"], feed.get("city") or "",
            ))
            reports.append({"source": source_id, "status": "skipped", "bids": 0, "skippedSeen": 0})
            continue
        wanted_state = config.get("state") or ""
        if wanted_state and feed["state"] != wanted_state:
            message = (
                f"{feed['name']} covers {feed['state']}. This run asked for {wanted_state}, so it was not fetched."
            )
            rows.append(status_row(
                feed["state"], "skipped", message, stamp, feed["source"], feed["page"], feed.get("city") or "",
            ))
            reports.append({"source": source_id, "status": "skipped", "bids": 0, "skippedSeen": 0})
            continue
        have = sum(1 for row in rows if billable_row(row))
        if have >= want:
            truncated = True
            reports.append({"source": source_id, "status": "maxItems", "bids": 0, "skippedSeen": 0})
            continue
        try:
            got, report = collect_source(feed, config, fetch, seen, want - have, stamp)
        except Exception as exc:
            log.critical("Bid source %s failed: %s", source_id, exc)
            got = [status_row(
                feed["state"], "error", "The source feed failed before it finished.", stamp,
                feed["source"], feed["page"], feed.get("city") or "",
            )]
            report = {"source": source_id, "status": "error", "bids": 0, "skippedSeen": 0}
        rows.extend(got)
        skipped += int(report.get("skippedSeen") or 0)
        truncated = truncated or bool(report.get("truncated"))
        reports.append({key: value for key, value in report.items() if key != "truncated"})
        log.info("Bids %s -> %s (%s)", source_id, report.get("status"), report.get("bids", 0))
    summary = _summarize(rows, reports, config, skipped, truncated, stamp)
    return rows, summary
