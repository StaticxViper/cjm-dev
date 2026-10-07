"""Generic adapter for a public HTML table of business records."""
from __future__ import annotations

from bs4 import BeautifulSoup

from new_business_sources.base import (
    NewBusinessRecord,
    SourceAdapter,
    compose_address,
    evidence,
    load_fixture_text,
    polite_get,
    utc_now,
)


class HttpTableAdapter(SourceAdapter):
    def parse_html(self, html, since_date=None, limit=None):
        config = self.entry.get("table") or {}
        soup = BeautifulSoup(html or "", "html.parser")
        selector = config.get("row_selector") or "table tr"
        rows = soup.select(selector)
        header_map = {}
        records = []
        columns = config.get("columns") or {}
        for row in rows:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            values = [cell.get_text(" ", strip=True) for cell in cells]
            if row.find("th") and not header_map:
                header_map = {name.lower(): index for index, name in enumerate(values)}
                continue
            if not any(values):
                continue
            record = self._record_from_cells(values, header_map, columns)
            if record is None:
                continue
            if since_date and record.formation_date and record.formation_date < str(since_date)[:10]:
                if not _any_date_on_or_after(record, since_date):
                    continue
            records.append(record)
            if limit and len(records) >= int(limit):
                break
        return records

    def _record_from_cells(self, values, header_map, columns):
        def cell(field_name):
            spec = columns.get(field_name)
            if spec is None:
                return ""
            if isinstance(spec, int):
                return values[spec] if spec < len(values) else ""
            index = header_map.get(str(spec).lower())
            if index is None or index >= len(values):
                return ""
            return values[index]

        name = cell("business_name")
        if not name:
            return None
        newness_field = self.entry.get("newness_field") or "filing_date"
        newness_type = self.entry.get("newness_type") or "filing_date"
        newness_value = cell(newness_field) or cell("date")
        newness_value = (newness_value or "")[:10]
        record = NewBusinessRecord(
            business_name=name,
            category=cell("category"),
            city=cell("city"),
            state=cell("state") or (self.entry.get("constants") or {}).get("state") or "",
            county=cell("county"),
            zip=cell("zip"),
            phone=cell("phone"),
            website=cell("website"),
            address=cell("address") or compose_address([cell("address"), cell("city"), cell("state"), cell("zip")]),
            business_status=cell("business_status") or "active",
            entity_id=cell("entity_id"),
            source_name=self.id,
            source_url=self.url,
            source_record_url=cell("source_record_url") or self.url,
            source_category=self.category,
            retrieved_at=utc_now(),
            phone_origin="registry" if cell("phone") else "",
            fields_provided=[key for key, spec in columns.items() if cell(key)],
        )
        if newness_value and len(newness_value) >= 10:
            if newness_type in ("registration_date", "formation_date", "filing_date", "opening_date"):
                setattr(record, newness_type, newness_value[:10])
            item = evidence(newness_type, newness_value, self.id, record.source_record_url)
            if item:
                record.newness_evidence.append(item)
        return record

    def fetch(self, geo, since_date, limit, dry_run=False):
        if dry_run:
            return self.parse_html(load_fixture_text(self.id, "page.html"), since_date=since_date, limit=limit)
        response = polite_get(self.url, rate_limit=dict(self.entry.get("rate_limit") or {}))
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code} from {self.url}")
        return self.parse_html(response.text, since_date=since_date, limit=limit)


def _any_date_on_or_after(record, since_date):
    cutoff = str(since_date)[:10]
    for field_name in ("registration_date", "formation_date", "filing_date", "opening_date"):
        value = getattr(record, field_name, None)
        if value and str(value)[:10] >= cutoff:
            return True
    for item in record.newness_evidence:
        if item.get("date") and item["date"] >= cutoff:
            return True
    return False
