"""Map Actor input onto UCC filing rows.

Connecticut and Oregon are the verified feeds. Every other state returns one
free status row and is not requested. Party rows are folded into one filing.
The JSON array is read until maxItems filings are complete, then the body
stream is closed.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

try:
    from .runtime import is_block, iso_now
    from .sources import (
        CT_UCC3,
        DATE_WINDOW_DAYS,
        DEFAULT_STATE,
        MAX_PAGES,
        MAX_SPAN_DAYS,
        MAX_STATES,
        PAGE_SIZE,
        VERIFIED,
        soda_url,
        unsupported_reason,
        where_clause,
    )
    from .state import filing_key
    from .stream import MAX_STREAM_BYTES, ArrayReader
except ImportError:
    from runtime import is_block, iso_now
    from sources import (
        CT_UCC3,
        DATE_WINDOW_DAYS,
        DEFAULT_STATE,
        MAX_PAGES,
        MAX_SPAN_DAYS,
        MAX_STATES,
        PAGE_SIZE,
        VERIFIED,
        soda_url,
        unsupported_reason,
        where_clause,
    )
    from state import filing_key
    from stream import MAX_STREAM_BYTES, ArrayReader


log = logging.getLogger("apify")

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COLLATERAL_LIMIT = 2000
TEXT_LIMIT = 500

REVIEW_ASK = (
    "If these UCC filings were useful, a short Apify Store rating helps other lenders find this feed."
)

FILING_FIELDS = (
    "state",
    "filingNumber",
    "filingType",
    "filingDate",
    "lapseDate",
    "debtorName",
    "debtorAddress",
    "securedPartyName",
    "securedPartyAddress",
    "collateral",
    "source",
    "sourceUrl",
    "status",
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


def join_unique(values, limit):
    chosen = []
    for value in values:
        text = clean(value)
        if text and text not in chosen:
            chosen.append(text)
    return clip("; ".join(chosen), limit)


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


def _filing_types(raw):
    chosen = []
    incoming = _as_list(raw if raw is not None else ["UCC-1"])
    if not incoming:
        incoming = ["UCC-1"]
    for item in incoming:
        label = item.upper().replace(" ", "")
        if label in {"UCC-1", "UCC1"}:
            label = "UCC-1"
        elif label in {"UCC-3", "UCC3"}:
            label = "UCC-3"
        else:
            continue
        if label not in chosen:
            chosen.append(label)
    return chosen or ["UCC-1"]


def _states(raw):
    chosen = []
    for item in _as_list(raw):
        code = item.upper()
        if not code or code in chosen:
            continue
        chosen.append(code)
        if len(chosen) >= MAX_STATES:
            break
    return chosen or [DEFAULT_STATE]


def _store_name(value):
    text = clean(value) or "ucc-filing-state"
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch in "-_")
    return (cleaned or "ucc-filing-state")[:63]


def actor_input_to_config(raw, today=None):
    raw = raw or {}
    today = today or date.today()
    start, start_error = _parse_day(raw.get("dateFrom"))
    end, end_error = _parse_day(raw.get("dateTo"))
    error = start_error or end_error
    if not error:
        if (start is None) ^ (end is None):
            error = "Set both dateFrom and dateTo, or leave both empty for the last 7 days."
        elif start is None:
            end = today
            start = today - timedelta(days=DATE_WINDOW_DAYS - 1)
        elif end < start:
            error = "dateTo is before dateFrom."
        elif (end - start).days + 1 > MAX_SPAN_DAYS:
            error = f"The date window cannot exceed {MAX_SPAN_DAYS} days."
    return {
        "states": _states(raw.get("states")),
        "filing_types": _filing_types(raw.get("filingTypes")),
        "date_from": start.isoformat() if start else "",
        "date_to": end.isoformat() if end else "",
        "max_items": _bounded_int(raw.get("maxItems"), 25, 1, 500),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 1.0, 1.0, 10.0),
        "max_spend_usd": _bounded_float(raw.get("maxSpendUsd"), 0.50, 0.0, 100.0),
        "new_since_last_run": bool(raw.get("newSinceLastRun")),
        "state_store": _store_name(raw.get("stateStoreName")),
        "error": error,
        "_page_size": PAGE_SIZE,
        "_max_bytes": MAX_STREAM_BYTES,
    }


def billable_row(row):
    row = row or {}
    return row.get("status") == "ok" and bool(row.get("filingNumber")) and row.get("ok") is True


def _base_row(stamp):
    row = {field: "" for field in FILING_FIELDS}
    row["ok"] = False
    row["scrapedAt"] = stamp
    return row


def status_row(state, status, message, stamp, source="", source_url=""):
    row = _base_row(stamp)
    row.update({
        "state": state or "",
        "source": source or "",
        "sourceUrl": source_url or "",
        "status": status,
        "decision": status,
        "error": message or "",
        "ok": False,
    })
    return row


def _party_name(row, prefix):
    bus = clean(row.get(f"{prefix}_nm_bus"))
    if bus:
        return bus
    parts = [clean(row.get(f"{prefix}_nm_{part}")) for part in ("first", "mid", "last", "suff")]
    return " ".join(part for part in parts if part)


def _ct_address(row, prefix):
    region = " ".join(part for part in (clean(row.get(f"{prefix}_ad_state")), clean(row.get(f"{prefix}_ad_zip"))) if part)
    return ", ".join(
        part for part in (
            clean(row.get(f"{prefix}_ad_str1")),
            clean(row.get(f"{prefix}_ad_str2")),
            clean(row.get(f"{prefix}_ad_city")),
            region,
        ) if part
    )


def _or_address(row):
    region = " ".join(part for part in (clean(row.get("st_cd_txt")), clean(row.get("zip_code_txt"))) if part)
    return ", ".join(
        part for part in (
            clean(row.get("mail_addr_1")),
            clean(row.get("mail_addr_2")),
            clean(row.get("city_descr")),
            region,
        ) if part
    )


def _image_url(row):
    link = row.get("image_link")
    if isinstance(link, dict):
        return clean(link.get("url"))
    return clean(link)


def _collateral(rows):
    for row in rows:
        text = row.get("collateral") or row.get("collateral_text")
        if clean(text):
            return clip(text, COLLATERAL_LIMIT)
    return ""


def _ct_label(row):
    if clean(row.get("tx_lien_descript")).upper() != "OFS":
        return ""
    form = clean(row.get("cd_flng_type")).upper()
    if form == "ORIG FIN STMT":
        return "UCC-1"
    if form in CT_UCC3:
        return "UCC-3"
    return ""


def _or_label(row):
    if clean(row.get("lien_type")).upper() != "UCC":
        return ""
    form = clean(row.get("file_type")).upper()
    if form == "INITIAL":
        return "UCC-1"
    if form == "AMENDMENT":
        return "UCC-3"
    return ""


def group_key(feed, row):
    if feed["kind"] == "ct":
        number = clean(row.get("id_ucc_flng_nbr"))
        label = _ct_label(row)
        form = clean(row.get("cd_flng_type")).upper()
        if not number or not label:
            return None
        return (number, label, form)
    number = clean(row.get("file_number"))
    label = _or_label(row)
    if not number or not label:
        return None
    return (number, label)


def build_row(feed, party_rows, stamp):
    if not party_rows:
        return None
    first = party_rows[0]
    if feed["kind"] == "ct":
        label = _ct_label(first)
        number = clean(first.get("id_ucc_flng_nbr"))
        debtors = [_party_name(row, "debtor") for row in party_rows]
        debtor_addresses = [_ct_address(row, "debtor") for row in party_rows]
        secured = [_party_name(row, "sec_party") for row in party_rows]
        secured_addresses = [_ct_address(row, "sec_party") for row in party_rows]
        filed = iso_day(first.get("dt_accept"))
        lapse = iso_day(first.get("dt_lapse"))
        source_url = feed["page"]
    else:
        label = _or_label(first)
        number = clean(first.get("file_number"))
        debtors, debtor_addresses, secured, secured_addresses = [], [], [], []
        for row in party_rows:
            party = clean(row.get("party_type")).upper()
            if party == "DB":
                debtors.append(clean(row.get("entity")))
                debtor_addresses.append(_or_address(row))
            elif party == "SP":
                secured.append(clean(row.get("entity")))
                secured_addresses.append(_or_address(row))
        filed = iso_day(first.get("filing_date"))
        lapse = iso_day(first.get("lapse_date"))
        source_url = next((url for url in (_image_url(row) for row in party_rows) if url), feed["page"])
    if not number or not label:
        return None
    row = _base_row(stamp)
    row.update({
        "state": feed["state"],
        "filingNumber": number,
        "filingType": label,
        "filingDate": filed,
        "lapseDate": lapse,
        "debtorName": join_unique(debtors, TEXT_LIMIT),
        "debtorAddress": join_unique(debtor_addresses, TEXT_LIMIT),
        "securedPartyName": join_unique(secured, TEXT_LIMIT),
        "securedPartyAddress": join_unique(secured_addresses, TEXT_LIMIT),
        "collateral": _collateral(party_rows),
        "source": feed["source"],
        "sourceUrl": source_url,
        "status": "ok",
        "decision": "filing",
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
            log.info("Closing the filing stream raised; the read already stopped.")


def _finish_group(feed, open_rows, stamp, seen, kept, skipped, want):
    row = build_row(feed, open_rows, stamp)
    if row is None:
        return skipped, False
    key = filing_key(row["state"], row["filingNumber"], row["filingType"])
    if seen is not None and key in seen:
        return skipped + 1, False
    kept.append(row)
    return skipped, len(kept) >= want


def collect_state(feed, config, fetch, seen, want, stamp):
    """Return ``(rows, report)``. ``rows`` is filings or one status row."""
    page_size = int(config.get("_page_size") or PAGE_SIZE)
    max_bytes = int(config.get("_max_bytes") or MAX_STREAM_BYTES)
    start = config["date_from"]
    end = config["date_to"]
    where = where_clause(feed, config["filing_types"], start, end)
    kept = []
    skipped = 0
    offset = 0
    open_key = None
    open_rows = []
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
                "robots.txt disallows this open-data URL, so the state was skipped."
                if error == "robots_disallowed"
                else "robots.txt could not be read, so the state was skipped."
            )
            return [status_row(feed["state"], "robots", message, stamp, feed["source"], feed["page"])], {
                "state": feed["state"], "status": "robots", "filings": 0, "skippedSeen": 0,
            }
        if error in {"statewide_export", "missing_limit"}:
            return [status_row(
                feed["state"], "error",
                "The request was refused because it was not a bounded open-data page.",
                stamp, feed["source"], feed["page"],
            )], {"state": feed["state"], "status": "error", "filings": 0, "skippedSeen": 0}
        if is_block(result):
            return [status_row(
                feed["state"], "blocked",
                "The open-data server blocked the request. No proxy retry is attempted.",
                stamp, feed["source"], feed["page"],
            )], {"state": feed["state"], "status": "blocked", "filings": 0, "skippedSeen": 0}
        status = int(result.get("status") or 0)
        if error or not 200 <= status < 300:
            failure = error or result.get("detail") or f"Open data answered HTTP {status}."
            truncated = bool(kept or open_rows)
            break
        chunks = result.get("chunks")
        if chunks is None and result.get("text"):
            chunks = [result["text"].encode("utf-8")]
        reader = ArrayReader(chunks, max_bytes)
        rows_on_page = 0
        try:
            for obj in reader:
                rows_on_page += 1
                key = group_key(feed, obj)
                if key is None:
                    continue
                if open_key is None:
                    open_key, open_rows = key, [obj]
                    continue
                if key == open_key:
                    open_rows.append(obj)
                    continue
                skipped, done = _finish_group(feed, open_rows, stamp, seen, kept, skipped, want)
                open_key, open_rows = None, []
                if done:
                    stop_early = True
                    break
                open_key, open_rows = key, [obj]
        finally:
            _close_chunks(chunks)
        if reader.error and not kept and open_key is None:
            failure = reader.error
            break
        if reader.truncated:
            truncated = True
            break
        if stop_early:
            break
        if rows_on_page < page_size:
            break
        offset += rows_on_page
    else:
        if pages >= MAX_PAGES and len(kept) < want:
            truncated = True

    if open_rows and len(kept) < want and not stop_early:
        skipped, _done = _finish_group(feed, open_rows, stamp, seen, kept, skipped, want)

    if failure and not kept:
        return [status_row(feed["state"], "error", clean(failure)[:300], stamp, feed["source"], feed["page"])], {
            "state": feed["state"], "status": "error", "filings": 0, "skippedSeen": skipped,
        }
    if truncated and not kept and failure is None and pages and not stop_early:
        # Byte cap or page cap with nothing complete.
        if not open_rows:
            return [status_row(
                feed["state"], "error",
                "The response exceeded the read cap. The statewide file was not loaded.",
                stamp, feed["source"], feed["page"],
            )], {"state": feed["state"], "status": "error", "filings": 0, "skippedSeen": skipped}
    if not kept:
        if skipped:
            message = f"No new {' or '.join(config['filing_types'])} filings in {feed['state']} since the last run."
        else:
            message = (
                f"No {' or '.join(config['filing_types'])} filings in {feed['state']} "
                f"from {start} through {end}."
            )
        return [status_row(feed["state"], "not_found", message, stamp, feed["source"], feed["page"])], {
            "state": feed["state"], "status": "not_found", "filings": 0, "skippedSeen": skipped,
        }
    return kept, {
        "state": feed["state"],
        "status": "ok",
        "filings": len(kept),
        "skippedSeen": skipped,
        "truncated": truncated,
    }


def _summarize(rows, reports, config, skipped, truncated, stamp):
    filings = [row for row in rows if billable_row(row)]
    statuses = [row.get("status") for row in rows if not billable_row(row)]

    def count(name):
        return sum(1 for status in statuses if status == name)

    if filings:
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
    return {
        "status": status,
        "filings": len(filings),
        "skippedSeen": skipped,
        "truncated": truncated,
        "unsupported": count("unsupported"),
        "notFound": count("not_found"),
        "blocked": count("blocked"),
        "robots": count("robots"),
        "errors": count("error"),
        "states": reports,
        "dateFrom": config.get("date_from") or "",
        "dateTo": config.get("date_to") or "",
        "filingTypes": list(config.get("filing_types") or []),
        "newSinceLastRun": bool(config.get("new_since_last_run")),
        "stateStore": config.get("state_store") or "",
        "maxItems": config.get("max_items"),
        "scrapedAt": stamp,
    }


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
    for state in config["states"]:
        feed = VERIFIED.get(state)
        if feed is None:
            rows.append(status_row(state, "unsupported", unsupported_reason(state), stamp))
            reports.append({"state": state, "status": "unsupported", "filings": 0, "skippedSeen": 0})
            continue
        have = sum(1 for row in rows if billable_row(row))
        if have >= want:
            truncated = True
            reports.append({"state": state, "status": "maxItems", "filings": 0, "skippedSeen": 0})
            continue
        try:
            got, report = collect_state(feed, config, fetch, seen, want - have, stamp)
        except Exception as exc:
            log.critical("UCC %s failed: %s", state, exc)
            got = [status_row(
                state, "error", "The state feed failed before it finished.", stamp,
                feed["source"], feed["page"],
            )]
            report = {"state": state, "status": "error", "filings": 0, "skippedSeen": 0}
        rows.extend(got)
        skipped += int(report.get("skippedSeen") or 0)
        truncated = truncated or bool(report.get("truncated"))
        reports.append({key: value for key, value in report.items() if key != "truncated"})
        log.info(
            "UCC %s -> %s (%s)",
            state,
            report.get("status"),
            report.get("filings", 0),
        )
    summary = _summarize(rows, reports, config, skipped, truncated, stamp)
    return rows, summary
