"""Actor input, dataset rows, and the pay-per-event decision.

Discovery, dedupe, website classification, and email acceptance stay in the
lead_automation modules. This file only maps Actor input onto those calls.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta

try:
    from .fetch import is_block
    from .runtime import iso_now, prepare_imports
    from .sources import entity_sources
    from .spend import ENRICHMENT_EVENT, PRICES_USD
except ImportError:
    from fetch import is_block
    from runtime import iso_now, prepare_imports
    from sources import entity_sources
    from spend import ENRICHMENT_EVENT, PRICES_USD


log = logging.getLogger("apify")

STATE_NAMES = {
    "new york": "NY",
    "pennsylvania": "PA",
    "colorado": "CO",
}

# Short labels users type. Matching is on the expanded phrase, not a raw
# substring, so "lp" does not swallow "llp".
TYPE_ALIASES = {
    "llc": "limited liability company",
    "l l c": "limited liability company",
    "dllc": "limited liability company",
    "corp": "corporation",
    "inc": "corporation",
    "incorporated": "corporation",
    "lp": "limited partnership",
    "llp": "limited liability partnership",
    "pllc": "professional limited liability company",
    "pc": "professional corporation",
    "nonprofit": "nonprofit",
    "non profit": "nonprofit",
    "not for profit": "nonprofit",
}

VERIFIED_SITE = frozenset({"website_found", "good_website"})
BROKEN_SITE_ISSUES = frozenset({"error", "empty", "domain_or_hosting_error"})
STOP_MESSAGES = {
    "budget": "Blocked. The spend cap was reached before a proxy or CAPTCHA retry.",
    "proxy_unavailable": "Blocked. The direct request was rejected and Apify Proxy is not configured.",
    "captcha_disabled": "Blocked by a challenge. CAPTCHA solving is off for this run.",
    "captcha_unavailable": "Blocked by a challenge. No CAPTCHA solver is configured, so nothing was billed for a solve.",
    "challenge": "Blocked. The proxy retry was still rejected.",
}


def _bounded_int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < low:
        return low
    if number > high:
        return high
    return number


def _bounded_float(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < low:
        return low
    if number > high:
        return high
    return number


def _flag(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y")
    return bool(value)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            text = str(item or "").strip()
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def normalize_state(value):
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return ""
    named = STATE_NAMES.get(text.lower())
    if named:
        return named
    if re.fullmatch(r"[A-Za-z]{2}", text):
        return text.upper()
    return ""


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _contains(haystack, needle):
    if not needle:
        return False
    if len(needle) <= 4:
        return f" {needle} " in f" {haystack} "
    return needle in haystack


def type_matches(category, requested):
    if not requested:
        return True
    haystack = _norm(category)
    if not haystack:
        return False
    for item in requested:
        needle = _norm(item)
        if not needle:
            continue
        expanded = TYPE_ALIASES.get(needle, needle)
        if _contains(haystack, needle) or _contains(haystack, expanded) or _contains(expanded, haystack):
            return True
    return False


def _county_key(value):
    text = _norm(value)
    if text.endswith(" county"):
        text = text[: -len(" county")].strip()
    return text


def county_matches(county, requested):
    if not requested:
        return True
    key = _county_key(county)
    if not key:
        return False
    return key in {_county_key(item) for item in requested}


def _parse_since(value, today):
    if value is None or str(value).strip() == "":
        return today - timedelta(days=365)
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def actor_input_to_config(actor_input, today=None):
    raw = actor_input or {}
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    provided = _as_list(raw.get("states") if raw.get("states") is not None else raw.get("state"))
    states = []
    bad = []
    for item in provided:
        code = normalize_state(item)
        if not code:
            bad.append(item)
        elif code not in states:
            states.append(code)
    formed = _parse_since(raw.get("formedSince"), today)
    error = ""
    if not provided:
        error = "At least one state is required."
    elif bad:
        error = "Use a two-letter state code. Verified feeds today are NY, PA, and CO."
    elif formed is None:
        error = "formedSince must be YYYY-MM-DD."
    max_spend = _bounded_float(raw.get("maxSpendUsd"), 5.0, 0.0, 100.0)
    max_proxy = _bounded_float(raw.get("maxProxyCostUsd"), 0.5, 0.0, 20.0)
    if max_proxy > max_spend:
        max_proxy = max_spend
    return {
        "states": states,
        "counties": _as_list(raw.get("counties")),
        "entity_types": _as_list(raw.get("entityTypes") if raw.get("entityTypes") is not None else raw.get("entity_types")),
        "formed_since": formed,
        "enrich_website": _flag(raw.get("enrichWebsite"), False),
        "max_results": _bounded_int(raw.get("maxResults"), 50, 1, 200),
        "max_requests": _bounded_int(raw.get("maxRequests"), 12, 1, 40),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 3.0, 1.0, 10.0),
        "max_spend_usd": max_spend,
        "max_proxy_usd": max_proxy,
        "allow_captcha": _flag(raw.get("allowCaptcha"), False),
        "headless": True if raw.get("headless") is None else bool(raw.get("headless")),
        "error": error,
    }


def billable_business(row):
    row = row or {}
    return row.get("sourceStatus") == "found" and bool(row.get("entity_id"))


def billable_enrichment(row):
    row = row or {}
    if not billable_business(row) or not row.get("enrichmentFound"):
        return False
    return bool((row.get("website") or "").strip() or (row.get("email") or "").strip())


def _blank_row(status, error, scraped_at, state="", source_url=""):
    return {
        "entity_id": "",
        "name": "",
        "formation_date": "",
        "type": "",
        "address": "",
        "county": "",
        "state": state,
        "website": "",
        "email": "",
        "source_url": source_url,
        "sourceStatus": status,
        "ok": False,
        "error": error,
        "scrapedAt": scraped_at,
        "enrichmentFound": False,
    }


def _formation_date(row):
    for key in ("formation_date", "filing_date", "registration_date"):
        value = str(row.get(key) or "")[:10]
        if len(value) == 10:
            return value
    return ""


def _site_verified(row):
    status = row.get("website_status") or ""
    issues = [str(item) for item in (row.get("website_issues") or [])]
    if status in VERIFIED_SITE:
        return True
    if status != "poor_website":
        return False
    if any(issue in BROKEN_SITE_ISSUES or issue.startswith("http_") for issue in issues):
        return False
    return True


class _NoGoogle:
    """Email session that refuses Google web search."""

    def __init__(self):
        self.google_blocked = True
        self.cache = {}

    def persistent_result(self, lead, city=None, state=None):
        return None

    def remember_result(self, lead, city=None, state=None):
        return None

    def search(self, query):
        raise AssertionError("Google web search is not used by this Actor")

    def close(self):
        return None


def _enrich_row(row, fetch, today):
    import new_business_email
    import new_business_pipeline as pipeline
    import new_business_website

    website = (row.get("website") or "").strip()
    if website:
        probed = fetch(website)
        if probed.get("error") == "robots_disallowed":
            row["website_status"] = "robots_disallowed"
        else:
            original = pipeline.classify_website

            def _fetched(**kwargs):
                kwargs["fetch_fn"] = fetch.website
                return new_business_website.classify_website(**kwargs)

            pipeline.classify_website = _fetched
            try:
                pipeline.apply_website(
                    row,
                    mode="deep",
                    today=today,
                    threshold=41,
                    dry_run=False,
                )
            finally:
                pipeline.classify_website = original

    def inspect(url):
        result = fetch(url)
        if result.get("error") or is_block(result) or int(result.get("status") or 0) >= 400:
            return {"emails": [], "html": "", "page_url": url, "page_text": ""}
        html = result.get("text") or ""
        from email_discovery import extract_emails_from_html

        return {
            "emails": extract_emails_from_html(html),
            "html": html,
            "page_url": url,
            "page_text": html[:4000],
        }

    new_business_email.enrich_new_business_lead(
        row,
        city=row.get("city"),
        state=row.get("state"),
        session=_NoGoogle(),
        inspect_fn=inspect,
        allow_google=False,
    )
    email = (row.get("email") or "").strip()
    if email and row.get("email_confidence") not in ("high", "medium"):
        email = ""
    site_ok = _site_verified(row)
    status = row.get("website_status") or ""
    if not site_ok and status not in ("", "robots_disallowed", "unknown"):
        row["website"] = ""
    row["email"] = email
    row["enrichmentFound"] = bool(site_ok or email)


def _drop_unbilled_enrichment(row):
    """Do not return an enrichment add-on that this run cannot bill."""
    if not row.get("enrichmentFound"):
        return
    row["website"] = ""
    row["email"] = ""
    row["enrichmentFound"] = False


def _assign_charges(rows, ledger):
    billed_business = 0
    billed_enrichment = 0
    capped = False
    for row in rows:
        row["_chargeBusiness"] = False
        row["_chargeEnrichment"] = False
        if not billable_business(row):
            continue
        if capped or not ledger.can("business"):
            capped = True
            _drop_unbilled_enrichment(row)
            continue
        ledger.commit("business")
        row["_chargeBusiness"] = True
        billed_business += 1
        if not billable_enrichment(row):
            continue
        if not ledger.can(ENRICHMENT_EVENT):
            capped = True
            _drop_unbilled_enrichment(row)
            continue
        ledger.commit(ENRICHMENT_EVENT)
        row["_chargeEnrichment"] = True
        billed_enrichment += 1
    return billed_business, billed_enrichment, capped


def _outcome(result):
    if not result:
        return "error"
    if result.get("error") == "robots_disallowed":
        return "robots"
    if result.get("error") == "request_cap":
        return "cap"
    if result.get("stop") or result.get("error") == "blocked":
        return "blocked"
    status = int(result.get("status") or 0)
    if status >= 400 or result.get("error"):
        return "error"
    return "ok"


def _load_modules():
    prepare_imports()
    from new_business_dedupe import dedupe_new_businesses
    from new_business_sources.base import resolve_fixture_dates
    from new_business_sources.open_data import OpenDataAdapter

    return OpenDataAdapter, resolve_fixture_dates, dedupe_new_businesses


def _fetch_source(adapter, fetch, since, limit, resolve_fixture_dates):
    rate_limit = adapter.entry.get("rate_limit") or {}
    page_size = min(int(limit), int(rate_limit.get("page_size") or 200))
    max_pages = int(rate_limit.get("max_requests_per_run") or 4)
    records = []
    for page in range(max_pages):
        url = adapter._page_url(since, page_size, offset=page * page_size)
        result = fetch(url)
        kind = _outcome(result)
        if kind != "ok":
            return records, result
        try:
            payload = json.loads(result.get("text") or "null")
        except json.JSONDecodeError:
            return records, {"error": "invalid_json", "status": result.get("status") or 0, "text": "", "url": url}
        payload = resolve_fixture_dates(payload)
        batch = adapter.parse_payload(payload, since_date=since, limit=None)
        if not batch:
            break
        records.extend(batch)
        if len(records) >= limit or len(batch) < page_size:
            break
    return records[:limit], None


def _source_url(record):
    """Dedupe keeps the record URL on the sources list, not the top-level row."""
    for source in record.get("sources") or []:
        if source.get("source_record_url"):
            return source["source_record_url"]
    for source in record.get("sources") or []:
        if source.get("source_url"):
            return source["source_url"]
    return record.get("source_record_url") or record.get("source_url") or ""


def _dataset_row(record, scraped_at):
    website = (record.get("website") or "").strip()
    email = (record.get("email") or "").strip()
    return {
        "entity_id": record.get("entity_id") or "",
        "name": record.get("business_name") or "",
        "formation_date": _formation_date(record),
        "type": record.get("category") or "",
        "address": record.get("address") or "",
        "county": record.get("county") or "",
        "state": record.get("state") or "",
        "website": website,
        "email": email,
        "source_url": _source_url(record),
        "sourceStatus": "found",
        "ok": True,
        "error": "",
        "scrapedAt": scraped_at,
        "enrichmentFound": bool(record.get("enrichmentFound")),
    }


def scrape(config, fetch, entries=None, today=None):
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    scraped_at = iso_now()
    if config.get("error"):
        row = _blank_row("error", config["error"], scraped_at)
        summary = _summarize([row], fetch, merged=0, truncated=False, capped=False, sources=[])
        return [row], summary

    OpenDataAdapter, resolve_fixture_dates, dedupe_new_businesses = _load_modules()
    selected, missing = entity_sources(config["states"], entries)
    collected = []
    status_rows = []
    source_reports = []
    stopped = ""
    for entry in selected:
        if stopped:
            break
        adapter = OpenDataAdapter(entry)
        records, failure = _fetch_source(
            adapter,
            fetch,
            config["formed_since"],
            config["max_results"],
            resolve_fixture_dates,
        )
        report = {"id": adapter.id, "status": "ok", "records": len(records)}
        if failure is not None:
            kind = _outcome(failure)
            report["status"] = kind
            source_reports.append(report)
            state = ((entry.get("coverage") or {}).get("states") or [""])[0]
            if kind == "robots":
                status_rows.append(_blank_row(
                    "robots_disallowed",
                    "robots.txt disallows this feed.",
                    scraped_at,
                    state=state,
                    source_url=adapter.url,
                ))
                continue
            if kind == "blocked":
                stopped = failure.get("stop") or "challenge"
                status_rows.append(_blank_row(
                    "blocked",
                    STOP_MESSAGES.get(stopped, STOP_MESSAGES["challenge"]),
                    scraped_at,
                    state=state,
                    source_url=adapter.url,
                ))
                break
            status_rows.append(_blank_row(
                "error",
                failure.get("error") or f"HTTP {failure.get('status') or 0}",
                scraped_at,
                state=state,
                source_url=adapter.url,
            ))
            if kind == "cap":
                stopped = "request_cap"
                break
            continue
        source_reports.append(report)
        for record in records:
            row = record.as_dict()
            if not county_matches(row.get("county"), config["counties"]):
                continue
            if not type_matches(row.get("category"), config["entity_types"]):
                continue
            collected.append(row)

    for state in missing:
        if stopped:
            break
        status_rows.append(_blank_row(
            "unsupported",
            f"No verified Secretary of State open-data feed for {state}.",
            scraped_at,
            state=state,
        ))

    merged, stats = dedupe_new_businesses(collected)
    truncated = len(merged) > config["max_results"]
    merged = merged[: config["max_results"]]
    can_enrich = (
        config["enrich_website"]
        and getattr(fetch, "ledger", None) is not None
        and fetch.ledger.can(ENRICHMENT_EVENT)
    )
    if can_enrich:
        for row in merged:
            try:
                _enrich_row(row, fetch, today)
            except Exception as exc:
                log.critical("Enrichment skipped for %s: %s", row.get("entity_id") or "", exc)
                row["website"] = ""
                row["email"] = ""
                row["enrichmentFound"] = False
    elif config["enrich_website"]:
        for row in merged:
            row["website"] = ""
            row["email"] = ""
            row["enrichmentFound"] = False
    else:
        for row in merged:
            row["enrichmentFound"] = False

    rows = [_dataset_row(row, scraped_at) for row in merged]
    rows.extend(status_rows)
    if not any(row.get("sourceStatus") == "found" for row in rows) and not status_rows:
        rows.append(_blank_row(
            "not_found",
            "No entities matched this state, county, date, and type filter.",
            scraped_at,
            state=config["states"][0] if config["states"] else "",
        ))
    ledger = getattr(fetch, "ledger", None)
    capped = False
    if ledger is not None:
        _billed_business, _billed_enrichment, capped = _assign_charges(rows, ledger)
    else:
        for row in rows:
            row["_chargeBusiness"] = billable_business(row)
            row["_chargeEnrichment"] = billable_enrichment(row)
    summary = _summarize(
        rows,
        fetch,
        merged=stats.get("merged_duplicates", 0),
        truncated=truncated,
        capped=capped,
        sources=source_reports,
    )
    summary["stopped"] = stopped
    return rows, summary


def _summarize(rows, fetch, merged, truncated, capped, sources):
    counts = {}
    for row in rows or []:
        key = row.get("sourceStatus") or "error"
        counts[key] = counts.get(key, 0) + 1
    found = counts.get("found", 0)
    if found and counts.get("blocked"):
        status = "partial"
    elif found:
        status = "ok"
    elif counts.get("blocked"):
        status = "blocked"
    elif counts.get("error"):
        status = "error"
    elif counts.get("robots_disallowed"):
        status = "robots_disallowed"
    elif counts.get("unsupported") and not found:
        status = "unsupported"
    else:
        status = "not_found"
    ledger = getattr(fetch, "ledger", None)
    counts_paid = ledger.counts if ledger is not None else {
        "business": sum(1 for row in rows or [] if row.get("_chargeBusiness")),
        "enrichment": sum(1 for row in rows or [] if row.get("_chargeEnrichment")),
        "proxy": 0,
        "captcha": 0,
    }
    return {
        "status": status,
        "pushed": len(rows or []),
        "found": found,
        "billedBusiness": counts_paid.get("business", 0),
        "billedEnrichment": counts_paid.get("enrichment", 0),
        "proxyCharges": counts_paid.get("proxy", 0),
        "captchaCharges": counts_paid.get("captcha", 0),
        "blocked": counts.get("blocked", 0),
        "errors": counts.get("error", 0),
        "robots": counts.get("robots_disallowed", 0),
        "unsupported": counts.get("unsupported", 0),
        "notFound": counts.get("not_found", 0),
        "mergedDuplicates": merged,
        "truncated": bool(truncated),
        "chargeCapped": bool(capped),
        "spendUsd": ledger.spend_usd if ledger is not None else 0,
        "pricesUsd": dict(PRICES_USD),
        "sources": sources,
        "stopped": "",
    }
