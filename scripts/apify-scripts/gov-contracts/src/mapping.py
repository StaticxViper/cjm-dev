"""Map Actor input onto SAM.gov opportunity rows and USAspending award rows.

Official APIs only. A missing SAM key skips opportunities and still reads
awards. A block stops that source and the other source still runs. maxItems
caps successful rows after dedupe. Status rows are not part of the cap.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

try:
    from .runtime import is_block, iso_now, looks_json
    from .sources import (
        DATE_WINDOW_DAYS,
        DEFAULT_ITEMS,
        MAX_ITEMS,
        MAX_NAICS,
        MAX_PAGES,
        PAGE_SIZE,
        SET_ASIDES,
        SOURCES,
        STATES,
        award_request,
        award_url,
        opportunity_url,
        redact,
        sam_request,
    )
    from .spend import AWARD_EVENT, OPPORTUNITY_EVENT, PRICES_USD, LeadLedger
except ImportError:
    from runtime import is_block, iso_now, looks_json
    from sources import (
        DATE_WINDOW_DAYS,
        DEFAULT_ITEMS,
        MAX_ITEMS,
        MAX_NAICS,
        MAX_PAGES,
        PAGE_SIZE,
        SET_ASIDES,
        SOURCES,
        STATES,
        award_request,
        award_url,
        opportunity_url,
        redact,
        sam_request,
    )
    from spend import AWARD_EVENT, OPPORTUNITY_EVENT, PRICES_USD, LeadLedger


log = logging.getLogger("apify")

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NAICS = re.compile(r"^\d{2,6}$")

TEXT_FIELDS = (
    "id",
    "recordType",
    "source",
    "agency",
    "subAgency",
    "title",
    "naics",
    "deadline",
    "awardee",
    "contactName",
    "contactEmail",
    "contactPhone",
    "uei",
    "setAside",
    "state",
    "noticeType",
    "solicitationNumber",
    "postedDate",
    "periodStart",
    "url",
    "sourceStatus",
    "decision",
    "error",
    "scrapedAt",
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
    text = str(value or "").strip()
    if not _DAY.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _dates(raw, today):
    start_raw = raw.get("postedFrom")
    end_raw = raw.get("postedTo")
    start_blank = start_raw is None or str(start_raw).strip() == ""
    end_blank = end_raw is None or str(end_raw).strip() == ""
    if start_blank and end_blank:
        end = today
        start = end - timedelta(days=DATE_WINDOW_DAYS)
        return start.isoformat(), end.isoformat(), ""
    if start_blank or end_blank:
        return "", "", "postedFrom and postedTo must both be set, as YYYY-MM-DD, or both left empty."
    start = _parse_day(start_raw)
    end = _parse_day(end_raw)
    if start is None or end is None:
        return "", "", "postedFrom and postedTo must be real YYYY-MM-DD dates."
    if start > end:
        return "", "", "postedFrom must be on or before postedTo."
    if (end - start).days > 366:
        return "", "", "postedFrom and postedTo must span at most 366 days. SAM.gov rejects a longer posted range."
    return start.isoformat(), end.isoformat(), ""


def _naics(raw):
    codes = []
    seen = set()
    for item in _as_list(raw.get("naics")):
        text = item.strip()
        if not _NAICS.fullmatch(text):
            return [], f"NAICS codes must be 2 to 6 digits, not {item!r}."
        if text in seen:
            continue
        seen.add(text)
        codes.append(text)
    if len(codes) > MAX_NAICS:
        return [], f"At most {MAX_NAICS} NAICS codes per run. This input has {len(codes)}."
    return codes, ""


def _state(raw):
    if raw.get("state") is None or str(raw.get("state")).strip() == "":
        return "", ""
    text = str(raw.get("state")).strip().upper()
    if text not in STATES:
        return "", f"state must be a 2-letter USPS code such as VA, not {raw.get('state')!r}."
    return text, ""


def _set_aside(raw):
    if raw.get("setAside") is None or str(raw.get("setAside")).strip() == "":
        return "", ""
    text = str(raw.get("setAside")).strip().upper()
    # Sole-source codes are case-sensitive in the GSA table (8A, BICiv).
    # Uppercasing BICiv would miss. Match the published code, then the upper form.
    published = str(raw.get("setAside")).strip()
    if published in SET_ASIDES:
        return published, ""
    if text in SET_ASIDES:
        return text, ""
    for code in SET_ASIDES:
        if code.upper() == text:
            return code, ""
    return "", f"setAside must be a SAM.gov set-aside code such as SBA or WOSB, not {raw.get('setAside')!r}."


def _sources(raw):
    if raw.get("sources") is None or raw.get("sources") == "":
        return list(SOURCES), ""
    chosen = []
    for item in _as_list(raw.get("sources")):
        name = item.strip().lower()
        if name not in SOURCES:
            return [], f"sources must be opportunities and/or awards, not {item!r}."
        if name not in chosen:
            chosen.append(name)
    if not chosen:
        return [], "Choose at least one source: opportunities, awards, or both."
    return chosen, ""


def actor_input_to_config(actor_input, today=None):
    raw = actor_input or {}
    today = today or date.today()
    sources, sources_error = _sources(raw)
    naics, naics_error = _naics(raw)
    state, state_error = _state(raw)
    set_aside, set_aside_error = _set_aside(raw)
    posted_from, posted_to, date_error = _dates(raw, today)
    error = sources_error or naics_error or state_error or set_aside_error or date_error
    if not error and not naics and not state:
        error = "Add a NAICS code or a state. An empty federal search is not sent."
    key = str(raw.get("samApiKey") or "").strip()
    return {
        "sources": sources,
        "naics": naics,
        "state": state,
        "set_aside": set_aside,
        "posted_from": posted_from,
        "posted_to": posted_to,
        "sam_api_key": key,
        "max_items": _bounded_int(raw.get("maxItems"), DEFAULT_ITEMS, 1, MAX_ITEMS),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 1.0, 1.0, 10.0),
        "max_spend_usd": _bounded_float(raw.get("maxSpendUsd"), 5.0, 0.01, 100.0),
        "error": error,
    }


# ---------------------------------------------------------------- rows


def _clean(value):
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip()
    if text.lower() in ("null", "none"):
        return ""
    return text


def _clip(value, limit):
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _naics_text(value):
    text = _clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _money(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = _clean(value).replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _blank_row(status, error, scraped_at, **extra):
    row = {name: "" for name in TEXT_FIELDS}
    row["value"] = None
    row["sourceStatus"] = status
    row["decision"] = extra.pop("decision", status)
    row["ok"] = status == "ok"
    row["error"] = error
    row["scrapedAt"] = scraped_at
    row.update(extra)
    return row


def _ok_row(fields, scraped_at):
    row = _blank_row("ok", "", scraped_at, decision=fields["recordType"])
    row.update(fields)
    row["sourceStatus"] = "ok"
    row["decision"] = fields["recordType"]
    row["ok"] = True
    row["error"] = ""
    row["scrapedAt"] = scraped_at
    return row


def billable_row(row):
    return bool(
        row.get("ok")
        and row.get("id")
        and row.get("recordType") in ("opportunity", "award")
        and row.get("sourceStatus") == "ok"
    )


def event_for(row):
    if row.get("recordType") == "award":
        return AWARD_EVENT
    return OPPORTUNITY_EVENT


def _contact(points):
    if isinstance(points, dict):
        points = [points]
    if not isinstance(points, list):
        return "", "", ""
    chosen = None
    for item in points:
        if isinstance(item, dict) and _clean(item.get("type")).lower() == "primary":
            chosen = item
            break
    if chosen is None:
        for item in points:
            if isinstance(item, dict):
                chosen = item
                break
    if not chosen:
        return "", "", ""
    name = _clean(chosen.get("fullName") or chosen.get("fullname"))
    return name, _clean(chosen.get("email")), _clean(chosen.get("phone"))


def _state_code(place):
    if not isinstance(place, dict):
        return ""
    state = place.get("state")
    if isinstance(state, dict):
        return _clean(state.get("code")).upper()
    return _clean(state).upper()


def parse_opportunity(raw):
    """One SAM notice, or None when the object has no notice id."""
    if not isinstance(raw, dict):
        return None
    notice = _clean(raw.get("noticeId"))
    if not notice:
        return None
    award = raw.get("award") if isinstance(raw.get("award"), dict) else {}
    awardee = award.get("awardee") if isinstance(award.get("awardee"), dict) else {}
    name, email, phone = _contact(raw.get("pointOfContact"))
    agency = _clean(raw.get("fullParentPathName")) or _clean(raw.get("department"))
    fields = {
        "id": notice,
        "recordType": "opportunity",
        "source": "sam.gov",
        "agency": agency,
        "subAgency": _clean(raw.get("subTier")),
        "title": _clip(raw.get("title"), 500),
        "naics": _naics_text(raw.get("naicsCode")),
        "value": _money(award.get("amount")),
        "deadline": _clean(raw.get("responseDeadLine")),
        "awardee": _clean(awardee.get("name")),
        "contactName": name,
        "contactEmail": email,
        "contactPhone": phone,
        "uei": _clean(awardee.get("ueiSAM")),
        "setAside": _clean(raw.get("typeOfSetAside")),
        "state": _state_code(raw.get("placeOfPerformance")),
        "noticeType": _clean(raw.get("type")),
        "solicitationNumber": _clean(raw.get("solicitationNumber")),
        "postedDate": _clean(raw.get("postedDate")),
        "periodStart": "",
        "url": opportunity_url(notice),
    }
    return fields, ("sam.gov", "opportunity", notice)


def parse_award(raw):
    """One USAspending award, or None when it has no award id."""
    if not isinstance(raw, dict):
        return None
    award_id = _clean(raw.get("Award ID"))
    generated = _clean(raw.get("generated_internal_id"))
    if not award_id and not generated:
        return None
    identity = generated or award_id
    fields = {
        "id": award_id or generated,
        "recordType": "award",
        "source": "usaspending.gov",
        "agency": _clean(raw.get("Awarding Agency")),
        "subAgency": _clean(raw.get("Awarding Sub Agency")),
        "title": _clip(raw.get("Description"), 500),
        "naics": _naics_text(raw.get("NAICS Code")),
        "value": _money(raw.get("Award Amount")),
        "deadline": _clean(raw.get("End Date")),
        "awardee": _clean(raw.get("Recipient Name")),
        "contactName": "",
        "contactEmail": "",
        "contactPhone": "",
        "uei": _clean(raw.get("Recipient UEI")),
        "setAside": "",
        "state": "",
        "noticeType": "",
        "solicitationNumber": "",
        "postedDate": "",
        "periodStart": _clean(raw.get("Start Date")),
        "url": award_url(generated),
    }
    return fields, ("usaspending.gov", "award", identity)


def _api_message(payload):
    if not isinstance(payload, dict):
        return ""
    for key in ("message", "errorMessage", "detail"):
        if payload.get(key):
            return _clean(payload.get(key))
    err = payload.get("error")
    if isinstance(err, dict):
        return _clean(err.get("message") or err.get("code"))
    if isinstance(err, str):
        return _clean(err)
    return ""


def outcome(result):
    error = (result or {}).get("error")
    if error in ("robots_disallowed", "robots_unavailable"):
        return "robots"
    if is_block(result):
        return "blocked"
    status = int((result or {}).get("status") or 0)
    if result and (result.get("error") or status >= 400 or status == 0):
        return "error"
    if not looks_json(result):
        return "error"
    return "ok"


def _host(url):
    return urlparse(url or "").netloc or "the API"


def _blocked_message(result):
    status = int((result or {}).get("status") or 0)
    if status in (401, 403, 429):
        what = f"HTTP {status}"
    else:
        what = "a challenge page"
    return (
        f"Blocked by {_host((result or {}).get('url'))} ({what}). "
        "This Actor does not use a proxy or a CAPTCHA solver, so this source stopped. "
        "This row is not charged."
    )


def _robots_message(result):
    if (result or {}).get("error") == "robots_unavailable":
        detail = redact(result.get("detail") or "fetch failed")
        return (
            f"robots.txt could not be read ({detail}). This host is skipped for the run. "
            "This row is not charged."
        )
    return "robots.txt disallows this URL. This row is not charged."


def _failure_message(result, secret):
    message = ""
    if looks_json(result):
        try:
            message = _api_message(json.loads(result.get("text") or "null"))
        except json.JSONDecodeError:
            message = ""
    if not message:
        if result.get("error"):
            message = str(result["error"])
        else:
            status = int(result.get("status") or 0)
            if 200 <= status < 300:
                message = "invalid_json: the API answered without a JSON body."
            else:
                message = f"HTTP {status}" if status else "fetch_failed"
    return _clip(redact(message, secret), 300)


def _load_json(result):
    try:
        return json.loads(result.get("text") or "null")
    except json.JSONDecodeError:
        return None


def _accept(kept, seen, counts, config, parsed):
    fields, key = parsed
    if key in seen:
        counts["duplicates"] += 1
        return "duplicate"
    if len(kept) >= config["max_items"]:
        return "full"
    seen.add(key)
    return "room", fields, key


def _take(kept, seen, counts, config, parsed, scraped_at, report):
    """Append one parsed record. Returns ``full`` when maxItems is already met."""
    if len(kept) >= config["max_items"]:
        return "full"
    decision = _accept(kept, seen, counts, config, parsed)
    if decision == "duplicate":
        return "duplicate"
    if decision == "full":
        return "full"
    _, fields, _key = decision
    kept.append(_ok_row(fields, scraped_at))
    report["kept"] += 1
    return "kept"


def _status(status_rows, kind, result, scraped_at, secret, source):
    if kind == "robots":
        status_rows.append(_blank_row("robots", _robots_message(result), scraped_at, source=source))
        return
    if kind == "blocked":
        status_rows.append(_blank_row(
            "blocked", _blocked_message(result), scraped_at, source=source, decision="blocked",
        ))
        return
    status_rows.append(_blank_row(
        "error", _failure_message(result, secret), scraped_at, source=source,
    ))


def _page_limit(config, kept):
    return max(1, min(PAGE_SIZE, config["max_items"] - len(kept)))


def _collect_opportunities(config, fetch, kept, status_rows, seen, counts, reports, scraped_at):
    secret = config.get("sam_api_key") or ""
    report = {"source": "sam.gov", "status": "ok", "fetched": 0, "kept": 0}
    if not secret:
        report["status"] = "skipped"
        reports.append(report)
        status_rows.append(_blank_row(
            "skipped",
            "samApiKey is required for SAM.gov opportunities. No request was sent to api.sam.gov. "
            "USAspending awards do not use this key. This row is not charged.",
            scraped_at,
            source="sam.gov",
            decision="skipped",
        ))
        return False
    codes = config["naics"] or [""]
    truncated = False
    for naics in codes:
        if len(kept) >= config["max_items"]:
            truncated = True
            break
        offset = 0
        while offset < MAX_PAGES and len(kept) < config["max_items"]:
            limit = _page_limit(config, kept)
            request = sam_request(config, naics, offset, limit)
            result = fetch(request)
            kind = outcome(result)
            if kind != "ok":
                report["status"] = kind
                _status(status_rows, kind, result, scraped_at, secret, "sam.gov")
                reports.append(report)
                return truncated
            payload = _load_json(result)
            records = payload.get("opportunitiesData") if isinstance(payload, dict) else None
            if not isinstance(records, list):
                report["status"] = "error"
                status_rows.append(_blank_row(
                    "error",
                    _clip(redact(_api_message(payload) or "unexpected_payload", secret), 300),
                    scraped_at,
                    source="sam.gov",
                ))
                reports.append(report)
                return truncated
            if not records:
                break
            report["fetched"] += len(records)
            fresh = 0
            for raw in records:
                parsed = parse_opportunity(raw)
                if parsed is None:
                    continue
                decision = _take(kept, seen, counts, config, parsed, scraped_at, report)
                if decision == "full":
                    truncated = True
                    break
                if decision == "kept":
                    fresh += 1
            if truncated or fresh == 0 or len(records) < limit:
                break
            offset += 1
        else:
            if offset >= MAX_PAGES and len(kept) < config["max_items"]:
                truncated = True
    reports.append(report)
    return truncated


def _collect_awards(config, fetch, kept, status_rows, seen, counts, reports, scraped_at):
    report = {"source": "usaspending.gov", "status": "ok", "fetched": 0, "kept": 0}
    truncated = False
    page = 1
    while page <= MAX_PAGES and len(kept) < config["max_items"]:
        limit = _page_limit(config, kept)
        request = award_request(config, page, limit)
        result = fetch(request)
        kind = outcome(result)
        if kind != "ok":
            report["status"] = kind
            _status(status_rows, kind, result, scraped_at, config.get("sam_api_key") or "", "usaspending.gov")
            reports.append(report)
            return truncated
        payload = _load_json(result)
        records = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            report["status"] = "error"
            status_rows.append(_blank_row(
                "error",
                _clip(redact(_api_message(payload) or "unexpected_payload", ""), 300),
                scraped_at,
                source="usaspending.gov",
            ))
            reports.append(report)
            return truncated
        if not records:
            break
        report["fetched"] += len(records)
        fresh = 0
        for raw in records:
            parsed = parse_award(raw)
            if parsed is None:
                continue
            fields, key = parsed
            if not fields["state"]:
                fields["state"] = config.get("state") or ""
            decision = _take(kept, seen, counts, config, (fields, key), scraped_at, report)
            if decision == "full":
                truncated = True
                break
            if decision == "kept":
                fresh += 1
        meta = payload.get("page_metadata") if isinstance(payload, dict) else None
        has_next = bool(isinstance(meta, dict) and meta.get("hasNext"))
        if truncated or fresh == 0 or len(records) < limit or not has_next:
            break
        page += 1
    else:
        if page > MAX_PAGES and len(kept) < config["max_items"]:
            truncated = True
    reports.append(report)
    return truncated


def scrape(config, fetch, now=None):
    """Return ``(rows, summary)``. Lead rows come first, then free status rows."""
    scraped_at = now or iso_now()
    if config.get("error"):
        row = _blank_row("error", config["error"], scraped_at)
        return [row], _summarize([row], config, {}, [], "", False, scraped_at)

    kept = []
    status_rows = []
    seen = set()
    counts = {"duplicates": 0}
    reports = []
    truncated = False
    secret = config.get("sam_api_key") or ""

    if "opportunities" in config["sources"]:
        truncated = _collect_opportunities(
            config, fetch, kept, status_rows, seen, counts, reports, scraped_at,
        ) or truncated
    if "awards" in config["sources"]:
        if len(kept) >= config["max_items"]:
            truncated = True
        else:
            truncated = _collect_awards(
                config, fetch, kept, status_rows, seen, counts, reports, scraped_at,
            ) or truncated

    if not kept and not status_rows:
        status_rows.append(_blank_row(
            "not_found",
            "No opportunities or awards matched this search.",
            scraped_at,
        ))
    rows = list(kept)
    rows.extend(status_rows)
    summary = _summarize(rows, config, counts, reports, "", truncated, scraped_at)
    # The key is input, never output.
    if secret and secret in json.dumps(summary):
        raise RuntimeError("SAM API key leaked into the run summary")
    if secret and secret in json.dumps(rows):
        raise RuntimeError("SAM API key leaked into a dataset row")
    log.critical(
        "Federal contracts SUMMARY: status=%s found=%s sources=%s",
        summary["status"],
        summary["found"],
        len(reports),
    )
    return rows, summary


def _summarize(rows, config, counts, reports, stopped, truncated, scraped_at):
    tally = {}
    for row in rows or []:
        key = row.get("sourceStatus") or "error"
        tally[key] = tally.get(key, 0) + 1
    found_rows = [row for row in rows or [] if billable_row(row)]
    found = len(found_rows)
    if found and any(tally.get(name) for name in ("blocked", "error", "robots", "skipped")):
        status = "partial"
    elif found:
        status = "ok"
    elif tally.get("blocked"):
        status = "blocked"
    elif tally.get("error"):
        status = "error"
    elif tally.get("robots"):
        status = "robots"
    elif tally.get("skipped"):
        status = "skipped"
    else:
        status = "not_found"
    ledger = LeadLedger(config.get("max_spend_usd", 5.0))
    billed = {OPPORTUNITY_EVENT: 0, AWARD_EVENT: 0}
    for row in found_rows:
        event = event_for(row)
        if not ledger.fits([event]):
            break
        ledger.commit(event)
        billed[event] += 1
    billed_total = billed[OPPORTUNITY_EVENT] + billed[AWARD_EVENT]
    return {
        "status": status,
        "pushed": len(rows or []),
        "found": found,
        "billedOpportunities": billed[OPPORTUNITY_EVENT],
        "billedAwards": billed[AWARD_EVENT],
        "skipped": tally.get("skipped", 0),
        "notFound": tally.get("not_found", 0),
        "blocked": tally.get("blocked", 0),
        "errors": tally.get("error", 0),
        "robots": tally.get("robots", 0),
        "mergedDuplicates": counts.get("duplicates", 0),
        "truncated": bool(truncated) or billed_total < found,
        "maxItems": config.get("max_items"),
        "chargeCapped": billed_total < found,
        "heldBack": max(0, found - billed_total),
        "maxSpendUsd": config.get("max_spend_usd", 5.0),
        "spendUsd": ledger.spend_usd,
        "pricesUsd": dict(PRICES_USD),
        "sources": list(config.get("sources") or []),
        "naics": list(config.get("naics") or []),
        "state": config.get("state") or "",
        "setAside": config.get("set_aside") or "",
        "postedFrom": config.get("posted_from") or "",
        "postedTo": config.get("posted_to") or "",
        "reports": reports,
        "stopped": stopped,
        "scrapedAt": scraped_at,
    }
