"""Generic adapter for public Socrata and Carto/ArcGIS-style open-data endpoints."""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from new_business_sources.base import (
    NewBusinessRecord,
    SourceAdapter,
    compose_address,
    evidence,
    load_fixture_json,
    polite_get,
    resolve_fixture_dates,
    utc_now,
)


class OpenDataAdapter(SourceAdapter):
    def parse_payload(self, payload, since_date=None, limit=None):
        rows = _rows_from_payload(payload)
        records = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            record = self._record_from_row(row)
            if record is None:
                continue
            if since_date and not _on_or_after(record, since_date):
                continue
            records.append(record)
            if limit and len(records) >= int(limit):
                break
        return records

    def _lookup(self, row, spec):
        if spec is None:
            return ""
        if isinstance(spec, list):
            parts = [self._lookup(row, item) for item in spec]
            return " ".join(part for part in parts if part).strip()
        value = row.get(spec)
        if value is None:
            return ""
        if isinstance(value, dict):
            return ""
        return str(value).strip()

    def _record_from_row(self, row):
        field_map = self.entry.get("field_map") or {}
        constants = self.entry.get("constants") or {}
        name = self._lookup(row, field_map.get("business_name"))
        if not name:
            return None
        newness_field = self.entry.get("newness_field")
        newness_type = self.entry.get("newness_type") or "filing_date"
        newness_raw = self._lookup(row, newness_field) if newness_field else ""
        newness_date = _iso_date(newness_raw)
        city = self._lookup(row, field_map.get("city")) or constants.get("city") or ""
        state = self._lookup(row, field_map.get("state")) or constants.get("state") or ""
        postal = _zip5(self._lookup(row, field_map.get("zip")))
        street = self._lookup(row, field_map.get("address"))
        address = compose_address([street, city, state, postal])
        entity_id = self._lookup(row, field_map.get("entity_id"))
        status = self._lookup(row, field_map.get("business_status")) or constants.get("business_status") or ""
        phone = self._lookup(row, field_map.get("phone"))
        website = self._lookup(row, field_map.get("website"))
        email = self._lookup(row, field_map.get("email"))
        category = self._lookup(row, field_map.get("category"))
        record_url = self._record_url(entity_id)
        record = NewBusinessRecord(
            business_name=name,
            category=category,
            description=self._lookup(row, field_map.get("description")),
            business_status=status,
            state=state,
            county=self._lookup(row, field_map.get("county")),
            city=city,
            zip=postal,
            address=address,
            phone=phone,
            website=website,
            email=email,
            entity_id=entity_id,
            source_name=self.id,
            source_url=self.url,
            source_record_url=record_url,
            source_category=self.category,
            retrieved_at=utc_now(),
            phone_origin="registry" if phone else "",
            raw={},
        )
        for date_field in ("registration_date", "formation_date", "filing_date", "opening_date"):
            mapped = field_map.get(date_field)
            if mapped:
                setattr(record, date_field, _iso_date(self._lookup(row, mapped)) or None)
        if newness_date:
            if newness_type in ("registration_date", "formation_date", "filing_date", "opening_date"):
                if not getattr(record, newness_type):
                    setattr(record, newness_type, newness_date)
            item = evidence(newness_type, newness_date, self.id, record_url or self.url)
            if item:
                record.newness_evidence.append(item)
        contact_name = self._lookup(row, field_map.get("contact_name"))
        if contact_name:
            record.public_contacts.append({
                "name": contact_name,
                "role": field_map.get("contact_role") or "public_contact",
                "source_url": record_url or self.url,
            })
        record.fields_provided = [
            key for key in (
                "business_name", "category", "registration_date", "formation_date",
                "filing_date", "opening_date", "business_status", "state", "county",
                "city", "zip", "address", "phone", "website", "email", "entity_id",
            )
            if getattr(record, key, None)
        ]
        return record

    def _record_url(self, entity_id):
        template = self.entry.get("record_url") or ""
        if template and entity_id:
            return template.format(id=quote(str(entity_id), safe=""))
        return self.url

    def fetch(self, geo, since_date, limit, dry_run=False):
        if dry_run:
            payload = resolve_fixture_dates(load_fixture_json(self.id) or [])
            return self.parse_payload(payload, since_date=since_date, limit=limit)
        rate_limit = dict(self.entry.get("rate_limit") or {})
        max_requests = int(rate_limit.get("max_requests_per_run") or 4)
        page_size = min(int(limit or 200), int(rate_limit.get("page_size") or 200))
        records = []
        for page in range(max_requests):
            url = self._page_url(since_date, page_size, offset=page * page_size)
            response = polite_get(url, rate_limit=rate_limit)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code} from {self.id}")
            batch = self.parse_payload(response.json(), since_date=since_date, limit=None)
            if not batch:
                break
            records.extend(batch)
            if limit and len(records) >= int(limit):
                return records[: int(limit)]
            if len(batch) < page_size:
                break
        return records[: int(limit)] if limit else records

    def _page_url(self, since_date, limit, offset):
        query = self.entry.get("query") or {}
        style = (query.get("style") or "socrata").lower()
        cutoff = _since_stamp(since_date, style)
        if style == "carto":
            table = query.get("table")
            columns = ", ".join(query.get("select") or ["*"])
            clauses = []
            date_column = query.get("date_column")
            if date_column and cutoff:
                clauses.append(f"{date_column} >= '{cutoff}'")
            extra = (query.get("extra_where") or "").strip()
            if extra:
                clauses.append(f"({extra})")
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            order = f" ORDER BY {date_column} DESC" if date_column else ""
            sql = f"SELECT {columns} FROM {table}{where}{order} LIMIT {int(limit)} OFFSET {int(offset)}"
            return self.url + quote(sql, safe="")
        where_parts = []
        date_column = query.get("date_column")
        if date_column and cutoff:
            where_parts.append(f"{date_column} >= '{cutoff}'")
        extra = (query.get("extra_where") or "").strip()
        if extra:
            where_parts.append(f"({extra})")
        params = [f"$limit={int(limit)}", f"$offset={int(offset)}"]
        if where_parts:
            params.append("$where=" + quote(" AND ".join(where_parts), safe=""))
        if date_column:
            params.append("$order=" + quote(f"{date_column} DESC", safe=""))
        select = query.get("select") or []
        if select:
            params.append("$select=" + quote(",".join(select), safe=","))
        joiner = "&" if "?" in self.url else "?"
        return self.url + joiner + "&".join(params)


def _rows_from_payload(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            return payload["rows"]
        if isinstance(payload.get("features"), list):
            return [item.get("attributes") or item for item in payload["features"]]
        if isinstance(payload.get("results"), list):
            return payload["results"]
    return []


def _iso_date(value):
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def _zip5(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:5]


def _since_stamp(since_date, style):
    if not since_date:
        return ""
    if isinstance(since_date, datetime):
        parsed = since_date.date()
    elif isinstance(since_date, date):
        parsed = since_date
    else:
        parsed = datetime.strptime(str(since_date)[:10], "%Y-%m-%d").date()
    if style == "carto":
        return parsed.isoformat()
    return parsed.isoformat() + "T00:00:00.000"


def _on_or_after(record, since_date):
    cutoff = str(since_date)[:10]
    dates = [
        record.registration_date,
        record.formation_date,
        record.filing_date,
        record.opening_date,
    ]
    dates.extend(item.get("date") for item in record.newness_evidence)
    present = [value for value in dates if value]
    if not present:
        return True
    return any(str(value)[:10] >= cutoff for value in present)
