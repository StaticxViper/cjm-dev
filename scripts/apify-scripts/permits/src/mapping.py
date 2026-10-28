"""Map Actor input onto permit rows.

Socrata and Carto page URLs come from ``OpenDataAdapter``. HTML tables use
``HttpTableAdapter`` for the row walk. Field mapping for permits stays here
because those adapters emit new-business records.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote

try:
    from .runtime import (
        access_summary,
        iso_now,
        prepare_imports,
        read_access_settings,
        stop_message,
    )
    from .sources import select_sources
    from .spend import PERMIT_EVENT, PRICES_USD
except ImportError:
    from runtime import (
        access_summary,
        iso_now,
        prepare_imports,
        read_access_settings,
        stop_message,
    )
    from sources import select_sources
    from spend import PERMIT_EVENT, PRICES_USD


prepare_imports()
from new_business_sources.http_table import HttpTableAdapter
from new_business_sources.open_data import OpenDataAdapter, _rows_from_payload


log = logging.getLogger("apify")

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Preset labels expand to words that show up in permit type and description
# fields. A label the catalog does not know is matched as itself.
TYPE_KEYWORDS = {
    "roof": ("roof", "reroof", "re-roof", "shingle"),
    "siding": ("siding",),
    "pool": ("pool",),
    "deck": ("deck",),
    "solar": ("solar", "photovoltaic"),
    "new construction": ("new construction", "new building"),
}

TEXT_FIELDS = (
    "permit_id",
    "issued_date",
    "type",
    "description",
    "address",
    "city",
    "state",
    "zip",
    "contractor_name",
    "contractor_license",
    "owner_name",
    "source",
    "source_url",
)


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


def _parse_day(value, default):
    if value is None or str(value).strip() == "":
        return default
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _day(value):
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def _ident(name):
    text = str(name or "").strip()
    if _IDENT.fullmatch(text):
        return text
    return ""


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _clip(value, limit):
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _date(value):
    text = _clean(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not match:
        return ""
    month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if month < 1 or month > 12 or day < 1 or day > 31:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _money(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).strip().replace(",", "").replace("$", "").replace(" ", "")
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _coord(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return round(number, 6)


def _lat_lng_ok(lat, lng):
    if lat is None or lng is None:
        return lat, lng
    if abs(lat) > 90 or abs(lng) > 180:
        return None, None
    return lat, lng


def _state(value, fallback):
    text = _clean(value) or _clean(fallback)
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return text


def _zip5(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:5]


def _norm_label(value):
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def type_terms(requested):
    terms = []
    for item in requested or []:
        label = _norm_label(item)
        if not label:
            continue
        expanded = TYPE_KEYWORDS.get(label)
        if expanded:
            terms.extend(expanded)
        else:
            terms.append(label)
    unique = []
    for term in terms:
        if term not in unique:
            unique.append(term)
    return unique


def _term_in(text, term):
    if any(ch in term for ch in " -"):
        return term in text
    return re.search(r"\b" + re.escape(term) + r"\b", text) is not None


def type_matches(haystack, requested):
    if not requested:
        return True
    text = _norm_label(haystack)
    if not text:
        return False
    return any(_term_in(text, term) for term in type_terms(requested))


def _value_ok(amount, minimum):
    if minimum <= 0:
        return True
    if amount is None:
        return False
    return amount + 1e-9 >= float(minimum)


def _text_clause(columns, permit_types, style):
    terms = []
    for term in type_terms(permit_types):
        cleaned = re.sub(r"[^A-Za-z0-9 \-]", "", term).strip().upper()
        if cleaned:
            terms.append(cleaned)
    cols = [ident for ident in (_ident(col) for col in columns) if ident]
    if not terms or not cols:
        return ""
    fn = "UPPER" if style == "arcgis" else "upper"
    parts = [f"{fn}({col}) like '%{term}%'" for col in cols for term in terms]
    return "(" + " OR ".join(parts) + ")"


def actor_input_to_config(actor_input, today=None):
    raw = actor_input or {}
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    date_from = _parse_day(raw.get("dateFrom"), today - timedelta(days=30))
    date_to = _parse_day(raw.get("dateTo"), today)
    error = ""
    if date_from is None:
        error = "dateFrom must be YYYY-MM-DD."
    elif date_to is None:
        error = "dateTo must be YYYY-MM-DD."
    elif date_from > date_to:
        error = "dateFrom must be on or before dateTo."
    access = read_access_settings(raw, prices_usd=PRICES_USD)
    return {
        "sources": _as_list(raw.get("sources")),
        "date_from": date_from,
        "date_to": date_to,
        "permit_types": _as_list(raw.get("permitTypes") if raw.get("permitTypes") is not None else raw.get("permit_types")),
        "min_value": _bounded_float(raw.get("minValue"), 0.0, 0.0, 1_000_000_000.0),
        "max_items": _bounded_int(raw.get("maxItems"), 50, 1, 200),
        "max_requests": _bounded_int(raw.get("maxRequests"), 24, 1, 80),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 2.0, 1.0, 10.0),
        "max_spend_usd": access["max_spend_usd"],
        "max_proxy_usd": access["max_proxy_usd"],
        "allow_captcha": access["allow_captcha"],
        "proxy_groups": access["proxy_groups"],
        "proxy_configuration": access["proxy_configuration"],
        "headless": True if raw.get("headless") is None else bool(raw.get("headless")),
        "error": error,
    }


def _prepare_entry(entry, config):
    prepared = json.loads(json.dumps(entry))
    query = prepared.setdefault("query", {})
    style = (query.get("style") or "socrata").lower()
    extras = []
    existing = (query.get("extra_where") or "").strip()
    if existing:
        extras.append(f"({existing})")
    column = _ident(query.get("date_column"))
    end = _day(config.get("date_to"))
    if style == "arcgis":
        query["date_to"] = end
    elif column and end:
        if style == "carto":
            extras.append(f"{column} <= '{end}'")
        else:
            extras.append(f"{column} <= '{end}T23:59:59.999'")
    clause = _text_clause(query.get("text_columns") or [], config.get("permit_types") or [], style)
    if clause:
        extras.append(clause)
    query["extra_where"] = " AND ".join(extras)
    return prepared


def _cell(adapter, row, spec):
    if not spec:
        return ""
    if isinstance(spec, str):
        value = row.get(spec)
        if isinstance(value, dict) and value.get("url"):
            return str(value.get("url") or "").strip()
    return adapter._lookup(row, spec)


def _slots(entry):
    contacts = entry.get("contacts")
    if isinstance(contacts, list) and contacts:
        return contacts
    try:
        count = int(entry.get("contact_slots") or 0)
    except (TypeError, ValueError):
        return []
    if count < 1:
        return []
    name_field = entry.get("contact_name_field") or "contact_{n}_name"
    role_field = entry.get("contact_role_field") or "contact_{n}_type"
    return [
        {"name": name_field.format(n=n), "role": role_field.format(n=n)}
        for n in range(1, count + 1)
    ]


def _people(adapter, row, entry):
    field_map = entry.get("field_map") or {}
    slots = _slots(entry)
    if slots:
        contractor = ""
        license_no = ""
        owner = ""
        for slot in slots:
            role = _cell(adapter, row, slot.get("role")).lower()
            name = _cell(adapter, row, slot.get("name"))
            lic = _cell(adapter, row, slot.get("license"))
            if "contractor" in role:
                if name and not contractor:
                    contractor = name
                if lic and not license_no:
                    license_no = lic
            elif role and "owner" in role and name and not owner:
                owner = name
        return contractor, license_no, owner
    contractor = _cell(adapter, row, field_map.get("contractor_name"))
    license_no = _cell(adapter, row, field_map.get("contractor_license"))
    owner = _cell(adapter, row, field_map.get("owner_name")) if "owner_name" in field_map else ""
    return contractor, license_no, owner


def _type_text(adapter, row, entry):
    fields = entry.get("type_fields") or []
    if fields:
        parts = []
        for field in fields:
            text = _cell(adapter, row, field)
            if text and text not in parts:
                parts.append(text)
        return " - ".join(parts)
    return _cell(adapter, row, (entry.get("field_map") or {}).get("type"))


def _search_text(adapter, row, entry):
    parts = []
    for field in (entry.get("query") or {}).get("text_columns") or []:
        text = _cell(adapter, row, field)
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


def _point(row):
    lat = _coord(row.get("_geom_lat"))
    lng = _coord(row.get("_geom_lng"))
    for key in ("location", "location1", "geolocation"):
        point = row.get(key)
        if not isinstance(point, dict):
            continue
        coords = point.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            if lng is None:
                lng = _coord(coords[0])
            if lat is None:
                lat = _coord(coords[1])
        if lat is None and point.get("latitude") is not None:
            lat = _coord(point.get("latitude"))
        if lng is None and point.get("longitude") is not None:
            lng = _coord(point.get("longitude"))
    return lat, lng


def _format_record_url(entry, permit_id):
    template = entry.get("record_url") or ""
    if template and permit_id and "{id}" in template:
        return template.format(id=quote(str(permit_id), safe=""))
    return entry.get("url") or entry.get("endpoint") or ""


def _record(entry, **fields):
    permit_id = _clip(fields.get("permit_id"), 80)
    if not permit_id:
        return None
    constants = entry.get("constants") or {}
    lat, lng = _lat_lng_ok(_coord(fields.get("lat")), _coord(fields.get("lng")))
    source_url = _clean(fields.get("source_url"))
    if not source_url.lower().startswith("http"):
        source_url = _format_record_url(entry, permit_id)
    return {
        "permit_id": permit_id,
        "issued_date": _date(fields.get("issued_date")),
        "type": _clip(fields.get("type"), 300),
        "description": _clip(fields.get("description"), 1000),
        "value_usd": _money(fields.get("value_usd")),
        "address": _clip(fields.get("address"), 300),
        "city": _clip(fields.get("city") or constants.get("city"), 80),
        "state": _state(fields.get("state"), constants.get("state")),
        "zip": _zip5(fields.get("zip")),
        "lat": lat,
        "lng": lng,
        "contractor_name": _clip(fields.get("contractor_name"), 200),
        "contractor_license": _clip(fields.get("contractor_license"), 80),
        "owner_name": _clip(fields.get("owner_name"), 200),
        "source": entry.get("id") or "",
        "source_url": source_url,
        "_search": _clean(fields.get("search")),
    }


def permit_from_row(adapter, row):
    entry = adapter.entry
    field_map = entry.get("field_map") or {}
    contractor, license_no, owner = _people(adapter, row, entry)
    lat = _coord(_cell(adapter, row, field_map.get("lat")))
    lng = _coord(_cell(adapter, row, field_map.get("lng")))
    if lat is None or lng is None:
        point_lat, point_lng = _point(row)
        if lat is None:
            lat = point_lat
        if lng is None:
            lng = point_lng
    source_url = _cell(adapter, row, field_map.get("source_url"))
    return _record(
        entry,
        permit_id=_cell(adapter, row, field_map.get("permit_id")),
        issued_date=_cell(adapter, row, field_map.get("issued_date")),
        type=_type_text(adapter, row, entry),
        description=_cell(adapter, row, field_map.get("description")),
        value_usd=_cell(adapter, row, field_map.get("value_usd")),
        address=_cell(adapter, row, field_map.get("address")),
        city=_cell(adapter, row, field_map.get("city")),
        state=_cell(adapter, row, field_map.get("state")),
        zip=_cell(adapter, row, field_map.get("zip")),
        lat=lat,
        lng=lng,
        contractor_name=contractor,
        contractor_license=license_no,
        owner_name=owner,
        source_url=source_url,
        search=_search_text(adapter, row, entry),
    )


def _payload_rows(payload):
    if isinstance(payload, dict) and isinstance(payload.get("features"), list):
        rows = []
        for item in payload["features"]:
            if not isinstance(item, dict):
                continue
            attrs = dict(item.get("attributes") or {})
            geom = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
            if geom.get("y") is not None:
                attrs["_geom_lat"] = geom.get("y")
            if geom.get("x") is not None:
                attrs["_geom_lng"] = geom.get("x")
            rows.append(attrs)
        return rows
    return _rows_from_payload(payload)


def _payload_error(payload):
    if not isinstance(payload, dict) or isinstance(payload.get("features"), list):
        return ""
    if isinstance(payload.get("error"), dict):
        return str(payload["error"].get("message") or payload["error"])
    if payload.get("error") in (True, "true") or payload.get("errorCode"):
        return str(payload.get("message") or payload.get("error") or "query_error")
    return ""


def parse_open_payload(adapter, payload):
    message = _payload_error(payload)
    if message:
        return [], message
    records = []
    for row in _payload_rows(payload):
        if not isinstance(row, dict):
            continue
        record = permit_from_row(adapter, row)
        if record:
            records.append(record)
    return records, ""


def _parse_table(entry, html):
    from bs4 import BeautifulSoup

    config = entry.get("table") or {}
    columns = config.get("columns") or {}
    publishes_owner = "owner_name" in columns
    soup = BeautifulSoup(html or "", "html.parser")
    header_map = {}
    records = []

    def cell(values, field_name):
        spec = columns.get(field_name)
        if spec is None:
            return ""
        if isinstance(spec, int):
            return values[spec] if spec < len(values) else ""
        index = header_map.get(str(spec).lower())
        if index is None or index >= len(values):
            return ""
        return values[index]

    for row in soup.select(config.get("row_selector") or "table tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        values = [item.get_text(" ", strip=True) for item in cells]
        if row.find("th") and not header_map:
            header_map = {name.lower(): index for index, name in enumerate(values)}
            continue
        if not any(values):
            continue
        record = _record(
            entry,
            permit_id=cell(values, "permit_id"),
            issued_date=cell(values, "issued_date"),
            type=cell(values, "type"),
            description=cell(values, "description"),
            value_usd=cell(values, "value_usd"),
            address=cell(values, "address"),
            city=cell(values, "city"),
            state=cell(values, "state"),
            zip=cell(values, "zip"),
            lat=cell(values, "lat"),
            lng=cell(values, "lng"),
            contractor_name=cell(values, "contractor_name"),
            contractor_license=cell(values, "contractor_license"),
            owner_name=cell(values, "owner_name") if publishes_owner else "",
            source_url=cell(values, "source_url"),
            search=" ".join(part for part in (cell(values, "type"), cell(values, "description")) if part),
        )
        if record is None:
            continue
        records.append(record)
        if len(records) >= 1000:
            break
    return records


class PermitOpenData(OpenDataAdapter):
    """Open-data page URLs, plus an ArcGIS query string the base adapter does not build."""

    def _page_url(self, since_date, limit, offset):
        query = self.entry.get("query") or {}
        style = (query.get("style") or "socrata").lower()
        if style != "arcgis":
            return super()._page_url(since_date, limit, offset)
        date_column = _ident(query.get("date_column"))
        clauses = []
        start = _day(since_date)
        end = _day(query.get("date_to"))
        if date_column and start:
            clauses.append(f"{date_column} >= DATE '{start}'")
        if date_column and end:
            clauses.append(f"{date_column} <= DATE '{end}'")
        extra = (query.get("extra_where") or "").strip()
        if extra:
            clauses.append(f"({extra})")
        where = " AND ".join(clauses) if clauses else "1=1"
        fields = [_ident(field) for field in (query.get("select") or [])]
        fields = [field for field in fields if field]
        out_fields = ",".join(fields) if fields else "*"
        order = ""
        if date_column:
            order = "&orderByFields=" + quote(f"{date_column} DESC", safe="")
        joiner = "&" if "?" in self.url else "?"
        return (
            self.url
            + joiner
            + "where=" + quote(where, safe="")
            + "&outFields=" + quote(out_fields, safe=",*")
            + "&returnGeometry=true&f=json"
            + f"&resultRecordCount={int(limit)}&resultOffset={int(offset)}"
            + order
        )


class PermitTable(HttpTableAdapter):
    def parse_html(self, html, since_date=None, limit=None):
        del since_date, limit
        return _parse_table(self.entry, html)


def _blank_row(status, error, scraped_at, source="", source_url=""):
    row = {key: "" for key in TEXT_FIELDS}
    row.update({
        "value_usd": None,
        "lat": None,
        "lng": None,
        "source": source,
        "source_url": source_url,
        "sourceStatus": status,
        "ok": False,
        "error": error,
        "scrapedAt": scraped_at,
    })
    return row


def _dataset_row(record, scraped_at):
    row = _blank_row("found", "", scraped_at, source=record.get("source") or "", source_url=record.get("source_url") or "")
    for key in TEXT_FIELDS:
        if key in ("source", "source_url"):
            continue
        row[key] = record.get(key) or ""
    row["value_usd"] = record.get("value_usd")
    row["lat"] = record.get("lat")
    row["lng"] = record.get("lng")
    row["sourceStatus"] = "found"
    row["ok"] = True
    row["error"] = ""
    return row


def billable_row(row):
    row = row or {}
    return row.get("sourceStatus") == "found" and row.get("ok") is True and bool(row.get("permit_id"))


def affordable_permits(ledger, rows):
    billable = sum(1 for row in rows or [] if billable_row(row))
    if ledger is None:
        return billable
    price = ledger.prices.get(PERMIT_EVENT)
    if not price:
        return billable
    room = ledger.max_spend - ledger.spent
    if room < 0:
        room = 0
    return min(billable, room // price)


def _keep(record, config):
    issued = record.get("issued_date") or ""
    start = _day(config.get("date_from"))
    end = _day(config.get("date_to"))
    if start and (not issued or issued < start):
        return False
    if end and (not issued or issued > end):
        return False
    if not _value_ok(record.get("value_usd"), config.get("min_value") or 0):
        return False
    haystack = " ".join([
        record.get("type") or "",
        record.get("description") or "",
        record.get("_search") or "",
    ])
    return type_matches(haystack, config.get("permit_types") or [])


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


def _failure_message(failure):
    if not failure:
        return "fetch_failed"
    if failure.get("error") and failure.get("error") not in ("blocked",):
        return str(failure.get("error"))
    status = int(failure.get("status") or 0)
    if status:
        return f"HTTP {status}"
    return "fetch_failed"


def _make_adapter(entry):
    if entry.get("adapter") == "http_table":
        return PermitTable(entry)
    return PermitOpenData(entry)


def _log_source(report):
    log.critical(
        "Permits source %s: status=%s fetched=%s kept=%s",
        report.get("id") or "",
        report.get("status") or "",
        report.get("fetched") or 0,
        report.get("kept") or 0,
    )


def scrape(config, fetch, entries=None):
    scraped_at = iso_now()
    if config.get("error"):
        row = _blank_row("error", config["error"], scraped_at)
        summary = _summarize([row], fetch, merged=0, truncated=False, sources=[], stopped="")
        return [row], summary

    selected, error = select_sources(config.get("sources"), entries)
    if error:
        row = _blank_row("error", error, scraped_at)
        summary = _summarize([row], fetch, merged=0, truncated=False, sources=[], stopped="")
        return [row], summary

    kept = []
    seen = set()
    dupes = 0
    truncated = False
    stopped = ""
    reports = []
    status_rows = []

    for entry in selected:
        if stopped or len(kept) >= config["max_items"]:
            truncated = truncated or len(kept) >= config["max_items"]
            break
        prepared = _prepare_entry(entry, config)
        adapter = _make_adapter(prepared)
        report = {"id": adapter.id, "status": "ok", "fetched": 0, "kept": 0, "duplicates": 0}
        failure = None

        def take(batch):
            nonlocal truncated, dupes
            report["fetched"] += len(batch)
            for record in batch:
                if len(kept) >= config["max_items"]:
                    truncated = True
                    return True
                if not _keep(record, config):
                    continue
                key = (record.get("source") or "", record.get("permit_id") or "")
                if key in seen:
                    dupes += 1
                    report["duplicates"] += 1
                    continue
                seen.add(key)
                kept.append(record)
                report["kept"] += 1
            return len(kept) >= config["max_items"]

        if entry.get("adapter") == "http_table":
            result = fetch(adapter.url)
            kind = _outcome(result)
            if kind != "ok":
                failure = result
            else:
                take(adapter.parse_html(result.get("text") or ""))
        else:
            rate = entry.get("rate_limit") or {}
            page_size = max(1, int(rate.get("page_size") or 50))
            max_pages = max(1, int(rate.get("max_requests_per_run") or 3))
            for page in range(max_pages):
                if len(kept) >= config["max_items"]:
                    truncated = True
                    break
                url = adapter._page_url(config["date_from"], page_size, page * page_size)
                result = fetch(url)
                kind = _outcome(result)
                if kind != "ok":
                    failure = result
                    break
                try:
                    payload = json.loads(result.get("text") or "null")
                except json.JSONDecodeError:
                    failure = {"error": "invalid_json", "status": result.get("status") or 0, "text": "", "url": url}
                    break
                batch, message = parse_open_payload(adapter, payload)
                if message:
                    failure = {"error": message, "status": result.get("status") or 200, "text": "", "url": url}
                    break
                if not batch:
                    break
                filled = take(batch)
                if filled or len(batch) < page_size:
                    break

        if failure is not None:
            kind = _outcome(failure)
            report["status"] = kind
            reports.append(report)
            _log_source(report)
            if kind == "robots":
                status_rows.append(_blank_row(
                    "robots_disallowed",
                    "robots.txt disallows this feed.",
                    scraped_at,
                    source=adapter.id,
                    source_url=adapter.url,
                ))
                continue
            if kind == "blocked":
                stopped = failure.get("stop") or "challenge"
                status_rows.append(_blank_row(
                    "blocked",
                    stop_message(stopped),
                    scraped_at,
                    source=adapter.id,
                    source_url=adapter.url,
                ))
                break
            status_rows.append(_blank_row(
                "error",
                _failure_message(failure),
                scraped_at,
                source=adapter.id,
                source_url=adapter.url,
            ))
            if kind == "cap":
                stopped = "request_cap"
                break
            continue

        reports.append(report)
        _log_source(report)

    rows = [_dataset_row(record, scraped_at) for record in kept]
    rows.extend(status_rows)
    if not any(row.get("sourceStatus") == "found" for row in rows) and not status_rows:
        rows.append(_blank_row(
            "not_found",
            "No permits matched this source, date, type, and value filter.",
            scraped_at,
            source=selected[0].get("id") if selected else "",
        ))
    summary = _summarize(
        rows,
        fetch,
        merged=dupes,
        truncated=truncated,
        sources=reports,
        stopped=stopped,
    )
    log.critical(
        "Permits SUMMARY: status=%s found=%s billedPermits=%s sources=%s",
        summary["status"],
        summary["found"],
        summary["billedPermits"],
        ",".join(item.get("id") or "" for item in reports),
    )
    return rows, summary


def _summarize(rows, fetch, merged, truncated, sources, stopped):
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
    elif counts.get("not_found"):
        status = "not_found"
    else:
        status = "ok" if found else "not_found"
    ledger = getattr(fetch, "ledger", None)
    settings = getattr(fetch, "settings", None)
    billed = affordable_permits(ledger, rows)
    price = PRICES_USD[PERMIT_EVENT]
    spent = ledger.spend_usd if ledger is not None else 0
    summary = {
        "status": status,
        "pushed": len(rows or []),
        "found": found,
        "billedPermits": billed,
        "blocked": counts.get("blocked", 0),
        "errors": counts.get("error", 0),
        "robots": counts.get("robots_disallowed", 0),
        "notFound": counts.get("not_found", 0),
        "mergedDuplicates": merged,
        "truncated": bool(truncated),
        "chargeCapped": billed < sum(1 for row in rows or [] if billable_row(row)),
        "spendUsd": round(spent + billed * price, 2),
        "pricesUsd": dict(PRICES_USD),
        "sources": sources,
        "stopped": stopped,
    }
    if settings is not None and ledger is not None:
        summary.update(access_summary(settings, ledger))
        summary["billedPermits"] = billed
        summary["spendUsd"] = round(ledger.spend_usd + billed * price, 2)
        summary["proxyCharges"] = ledger.counts.get("proxy", 0)
        summary["captchaCharges"] = ledger.counts.get("captcha", 0)
    return summary
