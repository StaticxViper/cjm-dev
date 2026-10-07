"""Soft newness signals from public Google result pages.

www.google.com/robots.txt disallows /search for User-agent: *. check_access
returns robots_disallowed and fetch does not request that path. Dry-run reads
a saved fixture only.
"""
from __future__ import annotations

from new_business_sources.base import (
    ACCESS_ROBOTS,
    NewBusinessRecord,
    SourceAdapter,
    evidence,
    load_fixture_text,
    robots_allowed,
    utc_now,
)
from email_discovery import parse_google_results

QUERY_TEMPLATES = (
    ('"grand opening" "{city}, {state}"', "grand_opening"),
    ('"now open" "{city}" {keyword}', "now_open"),
    ('"ribbon cutting" "{city}"', "ribbon_cutting"),
    ('"new business" "{city}" chamber', "new_chamber_member"),
)


class GoogleSearchAdapter(SourceAdapter):
    def check_access(self, html=None, robots_txt=None, target_url=None):
        target = target_url or "https://www.google.com/search?q=new+business"
        if html is None and robots_txt is None and (
            not self.enabled or self.status in ("disabled", "candidate", "blocked")
        ):
            return "blocked" if self.status == "blocked" else "disabled"
        if robots_txt is None and html is None:
            from new_business_sources.base import fetch_robots
            robots_txt = fetch_robots("https://www.google.com/search?q=new+business")
        if robots_txt is not None and not robots_allowed(robots_txt, target):
            return ACCESS_ROBOTS
        return super().check_access(html=html, robots_txt=robots_txt, target_url=target)

    def parse_html(self, html, *, city="", state="", evidence_type="grand_opening", query=""):
        records = []
        for result in parse_google_results(html or ""):
            title = (result.get("title") or "").strip()
            snippet = (result.get("snippet") or "").strip()
            if not title and not snippet:
                continue
            name = title.split(" - ")[0].split("|")[0].strip() or "Unknown business"
            record = NewBusinessRecord(
                business_name=name,
                description=snippet,
                city=city,
                state=state,
                source_name=self.id,
                source_url="https://www.google.com/search",
                source_record_url=result.get("url") or "",
                source_category=self.category,
                retrieved_at=utc_now(),
                website=result.get("url") or "",
                fields_provided=["business_name", "description"],
            )
            record.newness_evidence.append({
                "type": evidence_type,
                "date": None,
                "source_name": self.id,
                "source_url": result.get("url") or query,
                "confidence": "low",
            })
            # evidence() drops empty dates; soft signals may not have a date.
            if record.newness_evidence[-1]["date"] is None:
                record.newness_evidence[-1]["date"] = None
            records.append(record)
        return records

    def fetch(self, geo, since_date, limit, dry_run=False):
        if not dry_run:
            access = self.check_access()
            if access != "ok":
                raise PermissionError(access)
        html = load_fixture_text(self.id, "page.html") if dry_run else ""
        if dry_run:
            city = ""
            state = ""
            locations = getattr(geo, "locations", None) or []
            if locations:
                state, city, _coords = locations[0]
            return self.parse_html(
                html,
                city=city,
                state=state,
                evidence_type="grand_opening",
            )[: int(limit or 50)]
        return []


def build_search_queries(city, state, keyword, limit):
    queries = []
    for template, evidence_type in QUERY_TEMPLATES:
        if "{keyword}" in template and not keyword:
            continue
        text = template.format(city=city or "", state=state or "", keyword=keyword or "")
        text = " ".join(text.split())
        queries.append((text, evidence_type))
        if len(queries) >= int(limit):
            break
    return queries
