#!/usr/bin/env python3
"""Enrich CRM leads over the pipeline MCP server.

Picks a venture and batch, fills empty fields from Playwright Google Maps
(and an optional official Places API adapter), and writes only high-confidence
values back through update_lead. Google web search result pages are not used.

  python crm_enrich.py --venture SLUG --batch BATCH --fields email,phone --dry-run
"""
from __future__ import annotations

from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import argparse
import csv
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

from helper_scripts.utils.logger.logger import setup_logger
from crm_enrich_match import (
    address_is_empty,
    build_search_queries,
    field_is_empty,
    load_npa_state,
    load_zip_county,
    parse_lead_location,
    select_match,
)
from crm_enrich_robots import ACCESS_ROBOTS, apply_robots_gate
from crm_enrich_sources import (
    MapsPlaywrightSource,
    PlacesApiSource,
    collect_website,
    email_confidence_value,
    estimate_places_cost,
    format_places_cost,
    usable_phone,
    website_is_rejected,
)
from website_quality import normalize_website_url
from crm_mcp_client import (
    AUTH_MESSAGE,
    NEVER_WRITE_FIELDS,
    UPDATE_LEAD_WRITABLE,
    URL_MESSAGE,
    CrmAuthError,
    CrmClient,
    CrmConfigError,
    CrmConnectionError,
    CrmToolError,
    redact_url,
)

logger = setup_logger(
    name="crm_enrich",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)
logger.propagate = False

SUPPORTED_FIELDS = (
    "email",
    "phone",
    "website",
    "address",
    "google_maps_uri",
    "rating",
    "business_status",
    "contact_name",
)
DEFAULT_FIELDS = ("email", "phone", "website", "address")
DEFAULT_OUTPUT = _SCRIPT_DIR / "output" / "crm_enrich"
DISCOVERY_SOURCES = ("maps_playwright", "places_api")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_MCP = 3
EXIT_BLOCKED = 4
EXIT_INTERRUPTED = 130


@dataclass
class RunConfig:
    venture: str = ""
    batches: list = field(default_factory=list)
    fields: list = field(default_factory=lambda: list(DEFAULT_FIELDS))
    filters: dict = field(default_factory=dict)
    limit: int = 0
    dry_run: bool = False
    resume: bool = False
    force_resume: bool = False
    min_confidence: int = 80
    low_confidence_floor: int = 60
    overwrite: bool = False
    headless: bool = True
    sources: list = field(default_factory=lambda: ["maps_playwright", "website"])
    max_searches: int = 200
    write_delay: float = 0.5
    output_dir: Path = DEFAULT_OUTPUT
    audit_existing: bool = False
    drop_no_email_tag: bool = False
    tag_enriched: str = "enriched"
    tag_low_confidence: str = "enrich_low_confidence"
    tag_no_match: str = "enrich_no_match"
    tag_suspect: str = "enrich_suspect"
    non_interactive: bool = False
    clock: object = None

    def now(self):
        if self.clock is not None:
            return self.clock()
        return datetime.now(timezone.utc)


def config_hash(config):
    payload = {
        "fields": list(config.fields),
        "filters": config.filters,
        "min_confidence": config.min_confidence,
        "sources": list(config.sources),
        "overwrite": bool(config.overwrite),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_filters(text):
    """Parse ``k=v;k=v`` filters. ``tags`` and ``missing`` are comma lists."""
    if text is None or not str(text).strip():
        return {}
    found = {}
    for part in str(text).split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise CrmConfigError(f"Bad filter {part!r}; expected key=value")
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "tags":
            found["tags"] = [item.strip() for item in value.split(",") if item.strip()]
        elif key == "missing":
            found["missing"] = [item.strip() for item in value.split(",") if item.strip()]
        elif key == "has_email":
            found["has_email"] = value.lower() in {"1", "true", "yes", "y"}
        elif key in {"min_score", "max_score"}:
            found[key] = int(value)
        elif key in {"status", "search"}:
            found[key] = value
        else:
            raise CrmConfigError(f"Unknown filter {key!r}")
    unknown = [name for name in found.get("missing") or [] if name not in SUPPORTED_FIELDS]
    if unknown:
        raise CrmConfigError("Unknown missing field(s): " + ", ".join(unknown))
    return found


def parse_index_selection(raw, count):
    """Accept ``1,3-4`` style menus. Returns 1-based indexes."""
    chosen = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if end < start:
                start, end = end, start
            numbers = range(start, end + 1)
        else:
            numbers = (int(part),)
        for number in numbers:
            if number < 1 or number > count:
                raise CrmConfigError(f"Selection {number} is out of range 1-{count}")
            if number not in chosen:
                chosen.append(number)
    if not chosen:
        raise CrmConfigError("Select at least one item")
    return chosen


def _prompt(input_fn, text):
    return input_fn(text)


def print_table(headers, rows):
    widths = [len(str(header)) for header in headers]
    rendered = [[str(cell) for cell in row] for row in rows]
    for row in rendered:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    def emit(cells):
        print(" | ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)))
    emit([str(header) for header in headers])
    print("-+-".join("-" * width for width in widths))
    for row in rendered:
        emit(row)


def field_writable(field_name, writable):
    if field_name == "contact_name":
        return "contact_first_name" in writable and "contact_last_name" in writable
    if field_name in {"google_maps_uri", "rating", "business_status"}:
        return field_name in writable
    return field_name in writable


def lead_field_empty(lead, field_name):
    if field_name == "contact_name":
        return not (str(lead.get("contact_first_name") or "").strip() or str(lead.get("contact_last_name") or "").strip())
    if field_name == "rating":
        return lead.get("rating") in (None, "")
    return field_is_empty(field_name, lead.get(field_name))


def missing_counts(leads, writable):
    total = len(leads)
    rows = []
    for name in SUPPORTED_FIELDS:
        missing = sum(1 for lead in leads if lead_field_empty(lead, name))
        flag = "yes" if field_writable(name, writable) else "note-only"
        rows.append((name, f"missing in {missing} of {total}", flag))
    return rows


def lead_matches_missing(lead, missing):
    for name in missing or []:
        if not lead_field_empty(lead, name):
            return False
    return True


def selected_fields_filled(lead, fields):
    return all(not lead_field_empty(lead, name) for name in fields)


def checkpoint_path(output_dir, batch_id, dry_run):
    name = "checkpoint.dry-run.json" if dry_run else "checkpoint.json"
    return Path(output_dir) / str(batch_id) / name


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def load_checkpoint(path):
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fresh_checkpoint(config, batch_id, venture_id, run_id):
    now = config.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "version": 1,
        "run_id": run_id,
        "batch_id": batch_id,
        "venture_id": venture_id,
        "config_hash": config_hash(config),
        "fields": list(config.fields),
        "filters": config.filters,
        "dry_run": bool(config.dry_run),
        "started_at": now,
        "updated_at": now,
        "searches_used": 0,
        "processed": {},
    }


def save_checkpoint(path, payload, searches_used, config):
    payload["updated_at"] = config.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["searches_used"] = searches_used
    atomic_write(path, json.dumps(payload, indent=2))


def should_skip_processed(entry):
    if not entry:
        return False
    return entry.get("decision") not in {"error", "blocked"}


def public_candidate(scored):
    return {
        "name": scored.get("name"),
        "phone": scored.get("phone"),
        "website": scored.get("website"),
        "place_id": scored.get("place_id"),
        "category": scored.get("category"),
        "score": scored.get("score"),
        "breakdown": scored.get("breakdown"),
        "hard_rejects": list(scored.get("hard_rejects") or []),
    }


def _add_field(fields, lead, key, new, confidence, source, writable_flag, overwrite):
    if new is None or new == "":
        return
    current = lead.get(key)
    empty = address_is_empty(current) if key == "address" else (
        current is None or not str(current).strip()
    )
    if key == "rating":
        empty = current in (None, "")
    if not empty and not overwrite:
        return
    fields[key] = {
        "old": None if current in (None, "") else current,
        "new": new,
        "confidence": int(confidence),
        "source": source,
        "writable": bool(writable_flag),
    }


def propose_fields(lead, winner, requested, overwrite, writable, email_info, contact, source, quality):
    fields = {}
    if not winner:
        return fields
    score = winner["score"]
    if "phone" in requested:
        phone = usable_phone(winner.get("phone"))
        if phone:
            _add_field(fields, lead, "phone", phone, score, source, "phone" in writable, overwrite)
    if "website" in requested:
        website = winner.get("website")
        if website and not website_is_rejected(website):
            _add_field(
                fields, lead, "website", normalize_website_url(website), score, source,
                "website" in writable, overwrite,
            )
    if "address" in requested and winner.get("address"):
        _add_field(
            fields, lead, "address", winner["address"], score, source,
            "address" in writable, overwrite,
        )
    if "email" in requested and email_info:
        _add_field(
            fields, lead, "email", email_info["email"], email_info["confidence"], "website",
            "email" in writable, overwrite,
        )
    if "contact_name" in requested and contact:
        _add_field(
            fields, lead, "contact_first_name", contact["contact_first_name"], score, "website",
            "contact_first_name" in writable, overwrite,
        )
        _add_field(
            fields, lead, "contact_last_name", contact["contact_last_name"], score, "website",
            "contact_last_name" in writable, overwrite,
        )
    if "google_maps_uri" in requested:
        uri = winner.get("profile_url")
        if not uri and winner.get("place_id"):
            uri = f"https://www.google.com/maps/place/?q=place_id:{winner['place_id']}"
        if uri:
            _add_field(
                fields, lead, "google_maps_uri", uri, score, source,
                "google_maps_uri" in writable, overwrite,
            )
    if "rating" in requested and winner.get("rating") is not None:
        _add_field(
            fields, lead, "rating", winner["rating"], score, source,
            "rating" in writable, overwrite,
        )
        if winner.get("user_ratings_total") is not None:
            _add_field(
                fields, lead, "user_ratings_total", winner["user_ratings_total"], score, source,
                "user_ratings_total" in writable, overwrite,
            )
    if "business_status" in requested and winner.get("business_status"):
        _add_field(
            fields, lead, "business_status", winner["business_status"], score, source,
            "business_status" in writable, overwrite,
        )
    if quality and "website" in fields:
        fields["website"]["quality"] = quality
    return fields


def render_note(day, decision, best, fields):
    prefix = f"[enrich {day} crm_enrich]"
    if decision != "write":
        name = (best or {}).get("name") or "none"
        score = (best or {}).get("score") or 0
        return f"{prefix} no confident match; best={name} conf={score}"
    parts = []
    place_id = (best or {}).get("place_id")
    place_used = False
    for key in (
        "phone", "email", "website", "address", "contact_first_name", "contact_last_name",
    ):
        spec = fields.get(key)
        if not spec or not spec.get("writable"):
            continue
        piece = f"{key}={spec['new']} conf={spec['confidence']} src={spec['source']}"
        if spec.get("old") not in (None, "") and spec["old"] != spec["new"]:
            piece += f" was={spec['old']}"
        if key == "website" and spec.get("quality"):
            piece += f" quality={spec['quality']}"
        if not place_used and place_id:
            piece += f" place_id={place_id}"
            place_used = True
        parts.append(piece)
    notes = []
    if fields.get("google_maps_uri") and not fields["google_maps_uri"].get("writable"):
        notes.append(f"maps_uri={fields['google_maps_uri']['new']}")
    elif fields.get("google_maps_uri"):
        spec = fields["google_maps_uri"]
        piece = f"google_maps_uri={spec['new']} conf={spec['confidence']} src={spec['source']}"
        parts.append(piece)
    if fields.get("rating") and not fields["rating"].get("writable"):
        rating = fields["rating"]["new"]
        reviews = (fields.get("user_ratings_total") or {}).get("new")
        notes.append(f"rating={rating} ({reviews})" if reviews is not None else f"rating={rating}")
    if fields.get("business_status") and not fields["business_status"].get("writable"):
        notes.append(f"business_status={fields['business_status']['new']}")
    if notes:
        parts.append(" ".join(notes) + " (note-only)")
    if not parts:
        name = (best or {}).get("name") or "none"
        score = (best or {}).get("score") or 0
        return f"{prefix} no confident match; best={name} conf={score}"
    return prefix + " " + " | ".join(parts)


def tags_for(decision, suspect, config):
    if suspect:
        return [config.tag_suspect]
    if decision == "write":
        return [config.tag_enriched]
    if decision == "low_confidence":
        return [config.tag_low_confidence]
    if decision == "no_match":
        return [config.tag_no_match]
    return []


def merge_notes(existing, line):
    current = (existing or "").strip()
    extra = (line or "").strip()
    if not extra:
        return current
    if extra in current:
        return current
    return f"{current}\n{extra}".strip() if current else extra


def merge_tags(existing, additions, drop_no_email=False):
    tags = list(existing or [])
    for tag in additions or []:
        if tag and tag not in tags:
            tags.append(tag)
    if drop_no_email:
        tags = [tag for tag in tags if tag != "no-email"]
    return tags


def build_update_payload(lead, preview, config, writable):
    """Fields for update_lead. Notes are appended and tags are the merged list."""
    decision = preview.get("decision")
    additions = list(preview.get("tags_add") or [])
    if decision not in {"write", "low_confidence", "no_match"} and not additions:
        return {}
    if decision not in {"write", "low_confidence", "no_match"}:
        return {}
    payload = {}
    notes = merge_notes(lead.get("notes"), preview.get("note_preview"))
    if notes:
        payload["notes"] = notes
    drop = bool(config.drop_no_email_tag and decision == "write" and (preview.get("fields") or {}).get("email"))
    tags = merge_tags(lead.get("tags"), additions, drop_no_email=drop)
    if tags or lead.get("tags"):
        payload["tags"] = tags
    if decision == "write":
        for key, spec in (preview.get("fields") or {}).items():
            if not isinstance(spec, dict) or not spec.get("writable"):
                continue
            if key not in writable or key in NEVER_WRITE_FIELDS:
                continue
            current = lead.get(key)
            if key == "address":
                empty = address_is_empty(current)
            elif key == "rating":
                empty = current in (None, "")
            else:
                empty = current is None or not str(current).strip()
            if not empty and not config.overwrite:
                continue
            payload[key] = spec.get("new")
    return {key: value for key, value in payload.items() if key in writable}


def _base_preview(lead, location, query, source_status, decision, candidates, best, fields, tags, note):
    return {
        "lead_id": lead.get("id"),
        "business_name": lead.get("business_name"),
        "location": location,
        "query": query,
        "candidates": [public_candidate(item) for item in candidates or []],
        "decision": decision,
        "fields": fields or {},
        "tags_add": tags,
        "note_preview": note,
        "source_status": source_status,
    }


def _empty_preview(lead, location, decision, note, source_status, query=None):
    return _base_preview(
        lead, location, query, source_status, decision, [], None, {}, [], note,
    )


def enrich_lead(lead, config, deps):
    """Score one lead and return a preview record. Does not call update_lead."""
    writable = deps.writable
    zip_county = deps.zip_county
    location = parse_lead_location(lead, zip_county)
    source_status = dict(deps.source_status)
    day = config.now().date().isoformat()
    if not location.get("state"):
        note = f"[enrich {day} crm_enrich] skipped; no state"
        return _empty_preview(lead, location, "skipped_no_state", note, source_status)

    if (
        not config.audit_existing
        and not config.overwrite
        and selected_fields_filled(lead, config.fields)
    ):
        note = f"[enrich {day} crm_enrich] skipped; selected fields already filled"
        return _empty_preview(lead, location, "skipped_already_filled", note, source_status)

    queries = build_search_queries(lead, location)
    query = queries[0] if queries else ""
    candidates = []
    origin = "maps_playwright"
    if deps.maps is not None and "maps_playwright" in deps.enabled:
        listings, status = deps.maps.listings_for(lead, queries, location.get("city"), location.get("state"))
        source_status["maps_playwright"] = status
        if status == "cap" and not listings:
            return {"_stop": "cap", "lead": lead}
        if status == "blocked" and not listings and deps.places is None:
            note = f"[enrich {day} crm_enrich] blocked"
            preview = _empty_preview(lead, location, "blocked", note, source_status, query)
            preview["query"] = query
            return preview
        candidates.extend(listings or [])
        if status == "blocked":
            origin = "maps_playwright"
    if deps.places is not None and "places_api" in deps.enabled:
        maps_blocked = source_status.get("maps_playwright") == "blocked"
        if not candidates or maps_blocked:
            listings, status = deps.places.listings_for(
                lead, queries, location.get("city"), location.get("state"),
            )
            source_status["places_api"] = status
            if status == "cap" and not candidates:
                return {"_stop": "cap", "lead": lead}
            candidates.extend(listings or [])
            if listings:
                origin = "places_api"
    if "website" in deps.enabled:
        source_status.setdefault("website", "skipped")

    selection = select_match(
        candidates,
        lead,
        zip_county=zip_county,
        npa_state=deps.npa_state,
        min_confidence=config.min_confidence,
        low_floor=config.low_confidence_floor,
        location=location,
    )
    decision = selection["decision"]
    winner = selection["winner"]
    best = selection["best"]
    email_info = None
    contact = None
    quality = None
    website = None
    if winner and winner.get("website") and not website_is_rejected(winner.get("website")):
        website = winner.get("website")
    elif lead.get("website") and not website_is_rejected(lead.get("website")):
        website = lead.get("website")
    need_site = (
        decision == "write"
        and not config.audit_existing
        and website
        and ("email" in config.fields or "contact_name" in config.fields or "website" in config.fields)
    )
    if need_site and ("email" in config.fields or "contact_name" in config.fields):
        try:
            collected = collect_website(
                website,
                lead,
                session=getattr(deps, "session", None),
                get_fn=deps.robots_get,
                visit_fn=deps.visit_fn,
            )
            source_status["website"] = collected.get("status") or "ok"
            quality = collected.get("quality")
            accepted = collected.get("emails") or []
            if accepted and "email" in config.fields:
                email, level = accepted[0]
                email_info = {
                    "email": email,
                    "confidence": email_confidence_value(level, (winner or best or {}).get("score") or 0),
                }
            if "contact_name" in config.fields:
                contact = collected.get("contact")
        except Exception as exc:
            source_status["website"] = "error"
            logger.error("Website check failed for %s: %s", lead.get("id"), type(exc).__name__)

    suspect = False
    if config.audit_existing:
        has_existing = bool(str(lead.get("phone") or "").strip() or str(lead.get("website") or "").strip())
        # Audit only tags bad existing phone/website values. It does not fill or clear fields.
        if has_existing and decision != "write":
            suspect = True
            decision = "no_match"
        else:
            decision = "skipped_already_filled"
        winner = None

    fields = {}
    if decision == "write" and winner is not None:
        fields = propose_fields(
            lead, winner, config.fields, config.overwrite, writable,
            email_info, contact, origin if origin == "places_api" else "maps_playwright",
            quality,
        )
        if not any(spec.get("writable") for spec in fields.values()) and not any(
            not spec.get("writable") for spec in fields.values()
        ):
            decision = "skipped_already_filled"
    note = render_note(day, decision, best, fields)
    if suspect:
        name = (best or {}).get("name") or "none"
        score = (best or {}).get("score") or 0
        note = f"[enrich {day} crm_enrich] suspect existing phone/website; best={name} conf={score}"
    tags = tags_for(decision, suspect, config)
    if decision in {"skipped_already_filled", "skipped_no_state", "blocked", "error"}:
        tags = []
    preview = _base_preview(
        lead,
        selection.get("location") or location,
        query,
        source_status,
        decision,
        selection.get("candidates") or [],
        best,
        fields,
        tags,
        note,
    )
    preview["score"] = (best or {}).get("score")
    return preview


def write_preview_files(directory, previews):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write(directory / "preview.json", json.dumps(previews, indent=2))
    csv_path = directory / "preview.csv"
    temporary = csv_path.with_suffix(".csv.tmp")
    columns = [
        "lead_id", "business_name", "decision", "field", "old", "new",
        "confidence", "source", "writable", "score", "hard_rejects", "note_preview", "query",
    ]
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for preview in previews:
            best = None
            if preview.get("candidates"):
                best = max(preview["candidates"], key=lambda item: item.get("score") or 0)
            rejects = ",".join((best or {}).get("hard_rejects") or [])
            score = (best or {}).get("score")
            fields = preview.get("fields") or {}
            rows = list(fields.items()) or [( "", None)]
            for key, spec in rows:
                writer.writerow({
                    "lead_id": preview.get("lead_id"),
                    "business_name": preview.get("business_name"),
                    "decision": preview.get("decision"),
                    "field": key,
                    "old": None if not spec else spec.get("old"),
                    "new": None if not spec else spec.get("new"),
                    "confidence": None if not spec else spec.get("confidence"),
                    "source": None if not spec else spec.get("source"),
                    "writable": None if not spec else spec.get("writable"),
                    "score": score if preview.get("score") is None else preview.get("score"),
                    "hard_rejects": rejects,
                    "note_preview": preview.get("note_preview"),
                    "query": preview.get("query"),
                })
    os.replace(temporary, csv_path)


def summarize(previews, searches, started, config, source_status):
    filled = {name: 0 for name in (
        "email", "phone", "website", "address", "google_maps_uri", "rating",
        "business_status", "contact_name",
    )}
    counts = {
        "write": 0,
        "no_match": 0,
        "low_confidence": 0,
        "skipped_already_filled": 0,
        "skipped_no_state": 0,
        "blocked": 0,
        "error": 0,
    }
    for preview in previews:
        decision = preview.get("decision")
        if decision in counts:
            counts[decision] += 1
        if decision != "write":
            continue
        fields = preview.get("fields") or {}
        for name in ("email", "phone", "website", "address", "google_maps_uri", "rating", "business_status"):
            if name in fields:
                filled[name] += 1
        if "contact_first_name" in fields or "contact_last_name" in fields:
            filled["contact_name"] += 1
    duration = max(0.0, (config.now() - started).total_seconds()) if started else 0.0
    robots = [name for name, status in (source_status or {}).items() if status == ACCESS_ROBOTS]
    return {
        "leads_attempted": len(previews),
        "filled": filled,
        "written_leads": counts["write"],
        "no_match": counts["no_match"],
        "low_confidence": counts["low_confidence"],
        "skipped_already_filled": counts["skipped_already_filled"],
        "skipped_no_state": counts["skipped_no_state"],
        "blocked": counts["blocked"],
        "errors": counts["error"],
        "robots_disallowed": robots,
        "searches_used": searches,
        "duration_seconds": round(duration, 3),
        "dry_run": bool(config.dry_run),
    }


def print_summary(summary):
    print("")
    print("=== crm_enrich ===")
    print(f"attempted: {summary['leads_attempted']}")
    filled = summary["filled"]
    print(
        "filled: "
        + ", ".join(f"{key}={filled[key]}" for key in filled)
    )
    print(f"written leads: {summary['written_leads']}")
    print(f"no_match: {summary['no_match']}")
    print(f"low_confidence: {summary['low_confidence']}")
    print(f"skipped_already_filled: {summary['skipped_already_filled']}")
    print(f"skipped_no_state: {summary.get('skipped_no_state', 0)}")
    print(f"blocked: {summary['blocked']}")
    print(f"robots_disallowed: {', '.join(summary['robots_disallowed']) or 'none'}")
    print(f"errors: {summary['errors']}")
    print(f"searches used: {summary['searches_used']}")
    print(f"duration_seconds: {summary['duration_seconds']}")
    print(f"dry_run: {summary['dry_run']}")
    if summary.get("stopped_reason"):
        print(f"stopped: {summary['stopped_reason']}")


def count_write_plan(previews):
    leads = 0
    fields = 0
    for preview in previews:
        decision = preview.get("decision")
        if decision == "write":
            leads += 1
            for spec in (preview.get("fields") or {}).values():
                if isinstance(spec, dict) and spec.get("writable"):
                    fields += 1
        elif decision in {"low_confidence", "no_match"} and preview.get("tags_add"):
            leads += 1
    return fields, leads


def apply_writes(client, previews, config, sleeper):
    written = 0
    errors = 0
    for preview in previews:
        decision = preview.get("decision")
        if decision not in {"write", "low_confidence", "no_match"}:
            continue
        if decision != "write" and not preview.get("tags_add"):
            continue
        lead_id = preview.get("lead_id")
        try:
            current = client.get_lead(lead_id)
            if not isinstance(current, dict):
                raise CrmToolError("get_lead returned no lead")
            payload = build_update_payload(current, preview, config, client.writable_fields)
            if not payload:
                preview["written"] = []
                continue
            client.update_lead(lead_id, payload)
            preview["written"] = sorted(
                key for key in payload if key not in {"notes", "tags"}
            )
            written += 1
            if config.write_delay:
                sleeper(config.write_delay)
        except (CrmToolError, CrmConnectionError) as exc:
            errors += 1
            preview["decision"] = "error"
            logger.error("update_lead failed for %s: %s", lead_id, type(exc).__name__)
    return written, errors


class _Deps:
    def __init__(self):
        self.maps = None
        self.places = None
        self.session = None
        self.enabled = []
        self.source_status = {}
        self.writable = set(UPDATE_LEAD_WRITABLE)
        self.zip_county = None
        self.npa_state = None
        self.visit_fn = None
        self.robots_get = None


def _discovery_remaining(deps):
    remaining = []
    if "maps_playwright" in deps.enabled and deps.maps is not None and not deps.maps.blocked:
        remaining.append("maps_playwright")
    if "places_api" in deps.enabled and deps.places is not None and deps.places.status != "blocked":
        remaining.append("places_api")
    if not deps.enabled:
        return []
    discovery = [name for name in deps.enabled if name in DISCOVERY_SOURCES]
    if not discovery:
        return ["website"] if "website" in deps.enabled else []
    return remaining


def run_batch(config, client, batch_id, venture_id, deps, sleeper, write_now):
    digest = config_hash(config)
    path = checkpoint_path(config.output_dir, batch_id, config.dry_run)
    existing = load_checkpoint(path) if config.resume else None
    if existing and existing.get("config_hash") != digest and not config.force_resume:
        raise CrmConfigError(
            "Checkpoint config_hash differs; pass --force-resume to continue"
        )
    run_id = config.now().strftime("%Y%m%dT%H%M%SZ")
    if existing and existing.get("config_hash") == digest:
        checkpoint = existing
        run_id = existing.get("run_id") or run_id
    else:
        checkpoint = fresh_checkpoint(config, batch_id, venture_id, run_id)
    if config.force_resume and existing:
        checkpoint = existing
        checkpoint["config_hash"] = digest
        run_id = existing.get("run_id") or run_id
    run_dir = Path(config.output_dir) / str(batch_id) / run_id
    previews = []
    started = config.now()
    exit_code = EXIT_OK
    stopped = None
    server_filters = {
        key: value for key, value in (config.filters or {}).items() if key != "missing"
    }
    try:
        for lead in client.iter_leads(batch=batch_id, filters=server_filters, page_size=200):
            lead_id = lead.get("id")
            if should_skip_processed((checkpoint.get("processed") or {}).get(lead_id)):
                continue
            if not lead_matches_missing(lead, (config.filters or {}).get("missing")):
                continue
            if config.limit and len(previews) >= config.limit:
                break
            logger.info("Lead %s %s", lead_id, lead.get("business_name"))
            try:
                preview = enrich_lead(lead, config, deps)
            except CrmToolError as exc:
                logger.error("Lead %s tool error: %s", lead_id, type(exc).__name__)
                preview = _empty_preview(
                    lead, parse_lead_location(lead, deps.zip_county), "error",
                    f"[enrich {config.now().date().isoformat()} crm_enrich] error",
                    dict(deps.source_status),
                )
            except Exception as exc:
                logger.error("Lead %s failed: %s", lead_id, type(exc).__name__)
                preview = _empty_preview(
                    lead, parse_lead_location(lead, deps.zip_county), "error",
                    f"[enrich {config.now().date().isoformat()} crm_enrich] error",
                    dict(deps.source_status),
                )
            if isinstance(preview, dict) and preview.get("_stop") == "cap":
                stopped = "max_searches"
                break
            if write_now and not config.dry_run and preview.get("decision") in {
                "write", "low_confidence", "no_match",
            }:
                try:
                    current = client.get_lead(lead_id)
                    payload = build_update_payload(
                        current if isinstance(current, dict) else lead,
                        preview,
                        config,
                        client.writable_fields,
                    )
                    written_keys = []
                    if payload:
                        client.update_lead(lead_id, payload)
                        written_keys = sorted(key for key in payload if key not in {"notes", "tags"})
                        if config.write_delay:
                            sleeper(config.write_delay)
                    preview["written"] = written_keys
                except (CrmToolError, CrmConnectionError) as exc:
                    preview["decision"] = "error"
                    preview["written"] = []
                    logger.error("update_lead failed for %s: %s", lead_id, type(exc).__name__)
            else:
                preview["written"] = []
            previews.append(preview)
            checkpoint["processed"][lead_id] = {
                "decision": preview.get("decision"),
                "score": preview.get("score"),
                "written": preview.get("written") or [],
                "at": config.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            save_checkpoint(path, checkpoint, deps.counter["searches"], config)
            write_preview_files(run_dir, previews)
            if preview.get("decision") == "blocked" and not _discovery_remaining(deps):
                exit_code = EXIT_BLOCKED
                stopped = "blocked"
                break
            if deps.maps is not None and deps.maps.blocked and not _discovery_remaining(deps):
                exit_code = EXIT_BLOCKED
                stopped = "blocked"
                break
    except KeyboardInterrupt:
        save_checkpoint(path, checkpoint, deps.counter["searches"], config)
        write_preview_files(run_dir, previews)
        raise
    summary = summarize(previews, deps.counter["searches"], started, config, deps.source_status)
    if stopped:
        summary["stopped_reason"] = stopped
    atomic_write(run_dir / "summary.json", json.dumps(summary, indent=2))
    write_preview_files(run_dir, previews)
    save_checkpoint(path, checkpoint, deps.counter["searches"], config)
    return exit_code, previews, summary, run_dir


def _batch_record(client, batch_ref):
    if client.discovery_fallback:
        return {"batch_id": batch_ref, "venture_id": None, "name": batch_ref}
    payload = client.get_batch(batch_ref)
    batch = payload.get("batch") if isinstance(payload, dict) else None
    if not isinstance(batch, dict):
        batch = payload if isinstance(payload, dict) else {}
    return batch


def prepare_deps(config, google_robots, session_factory, places_factory, visit_fn, robots_get):
    enabled, status = apply_robots_gate(google_robots or "", config.sources)
    if google_robots is None:
        enabled = list(config.sources)
        status = {name: "ok" for name in config.sources}
        status["google_web_search"] = ACCESS_ROBOTS
    deps = _Deps()
    deps.enabled = enabled
    deps.source_status = status
    deps.zip_county = load_zip_county()
    deps.npa_state = load_npa_state()
    deps.visit_fn = visit_fn
    deps.robots_get = robots_get
    deps.counter = {"searches": 0}
    if "maps_playwright" in enabled:
        session = session_factory(config.headless)
        deps.session = session
        deps.maps = MapsPlaywrightSource(session, deps.counter, config.max_searches)
    if "places_api" in enabled:
        deps.places = places_factory(deps.counter, config.max_searches)
    return deps


def run_config(config, client, session_factory, places_factory, visit_fn, robots_get, google_robots, sleeper, input_fn, write_now):
    deps = prepare_deps(config, google_robots, session_factory, places_factory, visit_fn, robots_get)
    discovery = [name for name in config.sources if name in DISCOVERY_SOURCES]
    enabled_discovery = [name for name in discovery if name in deps.enabled and deps.source_status.get(name) != ACCESS_ROBOTS]
    if discovery and not enabled_discovery:
        print("Every discovery source is robots_disallowed or disabled.")
        summary = summarize([], 0, config.now(), config, deps.source_status)
        summary["stopped_reason"] = "robots_disallowed"
        print_summary(summary)
        _close_session(deps)
        return EXIT_BLOCKED, [], summary
    if "places_api" in deps.enabled:
        sample = config.limit or 0
        print(format_places_cost(estimate_places_cost(sample or config.max_searches)))
        if not config.non_interactive:
            answer = _prompt(input_fn, "Continue with places_api spend? [y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Cancelled before Places API calls.")
                _close_session(deps)
                return EXIT_OK, [], summarize([], 0, config.now(), config, deps.source_status)
    exit_code = EXIT_OK
    all_previews = []
    last_summary = summarize([], 0, config.now(), config, deps.source_status)
    try:
        for batch_ref in config.batches:
            batch = _batch_record(client, batch_ref)
            batch_id = batch.get("batch_id") or batch_ref
            venture_id = batch.get("venture_id") or config.venture
            code, previews, summary, run_dir = run_batch(
                config, client, batch_id, venture_id, deps, sleeper, write_now,
            )
            all_previews.extend(previews)
            last_summary = summary
            print_summary(summary)
            print(f"preview: {run_dir / 'preview.json'}")
            if code == EXIT_BLOCKED:
                return EXIT_BLOCKED, all_previews, summary
            exit_code = code
    except KeyboardInterrupt:
        print("Interrupted. Checkpoint saved.")
        return EXIT_INTERRUPTED, all_previews, last_summary
    finally:
        _close_session(deps)
    return exit_code, all_previews, last_summary


def _close_session(deps):
    session = getattr(deps, "session", None)
    closer = getattr(session, "close", None)
    if closer:
        closer()


def resolve_mcp_url(mcp_url=None):
    url = mcp_url or os.environ.get("CRM_MCP_URL")
    if not url or not str(url).strip():
        raise CrmConfigError(URL_MESSAGE)
    return str(url).strip()


def resolve_token():
    return os.environ.get("CRM_MCP_TOKEN") or os.environ.get("CRM_MCP_MV_LLC") or None


def _print_batch_detail(client, batch_ref):
    if client.discovery_fallback:
        print("Coverage is computed client-side (discovery tools missing).")
        return
    payload = client.get_batch(batch_ref)
    batch = payload.get("batch") if isinstance(payload, dict) else payload
    if not isinstance(batch, dict):
        return
    print(
        f"  {batch.get('name')}  total={batch.get('total')}  "
        f"with_email={batch.get('with_email')}  with_phone={batch.get('with_phone')}  "
        f"with_website={batch.get('with_website')}"
    )
    for status in batch.get("statuses") or []:
        print(f"    {status.get('name')}: {status.get('count')}")


def interactive_config(client, args, input_fn):
    if client.discovery_fallback:
        print("Warning: list_ventures/list_batches/get_batch are missing; grouping list_leads (cap 5000).")
        catalog = client.catalog_from_leads()
        ventures = catalog["ventures"]
        all_batches = catalog["batches"]
    else:
        payload = client.list_ventures()
        ventures = payload.get("ventures") or []
        all_batches = None
    if not ventures:
        raise CrmConfigError("No ventures returned")
    print("\n=== Ventures ===")
    print_table(
        ["#", "name", "batches", "leads"],
        [
            (index, item.get("name"), item.get("batch_count"), item.get("lead_count"))
            for index, item in enumerate(ventures, 1)
        ],
    )
    picked = parse_index_selection(_prompt(input_fn, "Venture #: ").strip(), len(ventures))
    venture = ventures[picked[0] - 1]
    if all_batches is None:
        listed = client.list_batches(venture.get("id") or venture.get("slug") or venture.get("name"))
        batches = listed.get("batches") or []
    else:
        batches = [item for item in all_batches if item.get("venture_id") == venture.get("id")]
    if not batches:
        raise CrmConfigError("No batches for that venture")
    print("\n=== Batches ===")
    print_table(
        ["#", "name", "imported", "total", "email %", "phone %"],
        [
            (
                index,
                item.get("name"),
                (item.get("imported_at") or "")[:10],
                item.get("total"),
                (item.get("rates") or {}).get("email_coverage_pct"),
                (item.get("rates") or {}).get("phone_coverage_pct"),
            )
            for index, item in enumerate(batches, 1)
        ],
    )
    raw = _prompt(input_fn, "Batch # (e.g. 1 or 1,3-4): ").strip()
    indexes = parse_index_selection(raw, len(batches))
    chosen = [batches[index - 1] for index in indexes]
    for item in chosen:
        _print_batch_detail(client, item.get("batch_id") or item.get("name"))
    print("\nFilters are optional. Press enter to skip a line.")
    status = _prompt(input_fn, "Status name: ").strip()
    tags = _prompt(input_fn, "Tags (comma, ANY match): ").strip()
    has_email = _prompt(input_fn, "has_email [blank/true/false]: ").strip()
    search = _prompt(input_fn, "Search text: ").strip()
    filters = {}
    if status:
        filters["status"] = status
    if tags:
        filters["tags"] = [item.strip() for item in tags.split(",") if item.strip()]
    if has_email.lower() in {"true", "false", "yes", "no"}:
        filters["has_email"] = has_email.lower() in {"true", "yes"}
    if search:
        filters["search"] = search
    sample = []
    for item in chosen:
        for lead in client.iter_leads(batch=item.get("batch_id"), filters=filters, page_size=200):
            sample.append(lead)
            if len(sample) >= 5000:
                break
    print("\n=== Fields ===")
    print_table(["field", "missing", "writable via update_lead?"], missing_counts(sample, client.writable_fields))
    raw_fields = _prompt(
        input_fn,
        "Fields to fill [email,phone,website,address]: ",
    ).strip()
    fields = [item.strip() for item in (raw_fields or ",".join(DEFAULT_FIELDS)).split(",") if item.strip()]
    unknown = [name for name in fields if name not in SUPPORTED_FIELDS]
    if unknown:
        raise CrmConfigError("Unknown field(s): " + ", ".join(unknown))
    dry = _prompt(input_fn, "Dry-run? [Y/n]: ").strip().lower()
    minimum = _prompt(input_fn, "Min confidence [80]: ").strip()
    limit = _prompt(input_fn, "Limit (blank = all, still capped by --max-searches): ").strip()
    sources = _prompt(input_fn, "Sources [maps_playwright,website]: ").strip()
    config = RunConfig(
        venture=venture.get("id") or venture.get("slug") or "",
        batches=[item.get("batch_id") or item.get("name") for item in chosen],
        fields=fields,
        filters=filters,
        limit=int(limit) if limit else 0,
        dry_run=dry not in {"n", "no"},
        min_confidence=int(minimum) if minimum else 80,
        sources=[item.strip() for item in (sources or "maps_playwright,website").split(",") if item.strip()],
        headless=not args.headful,
        max_searches=args.max_searches,
        write_delay=args.write_delay,
        output_dir=Path(args.output_dir),
        audit_existing=args.audit_existing,
        drop_no_email_tag=args.drop_no_email_tag,
        overwrite=args.overwrite,
        non_interactive=False,
        low_confidence_floor=args.low_confidence_floor,
        tag_enriched=args.tag_enriched,
        tag_low_confidence=args.tag_low_confidence,
        tag_no_match=args.tag_no_match,
        tag_suspect=args.tag_suspect,
    )
    config._sample_size = len(sample)
    return config


def cmd_list(client, venture=None):
    if client.discovery_fallback:
        print("Warning: discovery tools missing; coverage is computed from list_leads.")
        catalog = client.catalog_from_leads()
        ventures = catalog["ventures"]
        print_table(
            ["#", "name", "batches", "leads"],
            [(i, v.get("name"), v.get("batch_count"), v.get("lead_count")) for i, v in enumerate(ventures, 1)],
        )
        rows = []
        for item in catalog["batches"]:
            if venture and venture not in {item.get("venture_id"), item.get("name")}:
                continue
            rows.append((item.get("name"), item.get("total"), "", ""))
        print_table(["name", "total", "email %", "phone %"], rows)
        return
    payload = client.list_ventures()
    ventures = payload.get("ventures") or []
    print_table(
        ["#", "name", "batches", "leads"],
        [(i, v.get("name"), v.get("batch_count"), v.get("lead_count")) for i, v in enumerate(ventures, 1)],
    )
    for item in ventures:
        ident = item.get("id") or item.get("slug") or item.get("name")
        if venture and venture not in {item.get("id"), item.get("slug"), item.get("name")}:
            continue
        listed = client.list_batches(ident)
        rows = []
        for batch in listed.get("batches") or []:
            rates = batch.get("rates") or {}
            detail = client.get_batch(batch.get("batch_id"))
            body = detail.get("batch") if isinstance(detail, dict) else {}
            rows.append((
                batch.get("name"),
                batch.get("total"),
                rates.get("email_coverage_pct"),
                rates.get("phone_coverage_pct"),
                (body or {}).get("with_website"),
            ))
        print(f"\n{item.get('name')}")
        print_table(["name", "total", "email %", "phone %", "with_website"], rows)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Enrich CRM batch leads over MCP (Playwright Maps + site validation)",
    )
    parser.add_argument("--mcp-url", default=None, help="CRM MCP URL (else CRM_MCP_URL)")
    parser.add_argument(
        "--mcp-transport",
        choices=("streamable-http", "sse"),
        default="streamable-http",
    )
    parser.add_argument("--venture", default=None, help="Venture id, slug, or name")
    parser.add_argument("--batch", action="append", default=None, help="Batch id, slug, or name")
    parser.add_argument("--fields", default=None, help="Comma list of fields to fill")
    parser.add_argument("--filters", default=None, help='k=v;k=v (status, tags, has_email, min_score, max_score, search, missing)')
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force-resume", action="store_true")
    parser.add_argument("--min-confidence", type=int, default=80)
    parser.add_argument("--low-confidence-floor", type=int, default=60)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--sources", default="maps_playwright,website")
    parser.add_argument("--max-searches", type=int, default=200)
    parser.add_argument("--write-delay", type=float, default=0.5)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--audit-existing", action="store_true")
    parser.add_argument("--drop-no-email-tag", action="store_true")
    parser.add_argument("--tag-enriched", default="enriched")
    parser.add_argument("--tag-low-confidence", default="enrich_low_confidence")
    parser.add_argument("--tag-no-match", default="enrich_no_match")
    parser.add_argument("--tag-suspect", default="enrich_suspect")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--list", action="store_true", help="Print ventures and batches with coverage")
    return parser.parse_args(argv)


def config_from_args(args):
    fields = [item.strip() for item in (args.fields or ",".join(DEFAULT_FIELDS)).split(",") if item.strip()]
    unknown = [name for name in fields if name not in SUPPORTED_FIELDS]
    if unknown:
        raise CrmConfigError("Unknown field(s): " + ", ".join(unknown))
    if not 0 <= args.min_confidence <= 100:
        raise CrmConfigError("--min-confidence must be 0-100")
    if not 0 <= args.low_confidence_floor <= 100:
        raise CrmConfigError("--low-confidence-floor must be 0-100")
    sources = [item.strip() for item in (args.sources or "").split(",") if item.strip()]
    allowed = {"maps_playwright", "website", "places_api"}
    bad = [name for name in sources if name not in allowed]
    if bad:
        raise CrmConfigError("Unknown source(s): " + ", ".join(bad))
    if "places_api" in sources and not os.environ.get("GOOGLE_API_KEY"):
        raise CrmConfigError("places_api requires GOOGLE_API_KEY")
    return RunConfig(
        venture=args.venture or "",
        batches=list(args.batch or []),
        fields=fields,
        filters=parse_filters(args.filters),
        limit=args.limit or 0,
        dry_run=bool(args.dry_run),
        resume=bool(args.resume),
        force_resume=bool(args.force_resume),
        min_confidence=args.min_confidence,
        low_confidence_floor=args.low_confidence_floor,
        overwrite=bool(args.overwrite),
        headless=not args.headful,
        sources=sources,
        max_searches=args.max_searches,
        write_delay=args.write_delay,
        output_dir=Path(args.output_dir),
        audit_existing=bool(args.audit_existing),
        drop_no_email_tag=bool(args.drop_no_email_tag),
        tag_enriched=args.tag_enriched,
        tag_low_confidence=args.tag_low_confidence,
        tag_no_match=args.tag_no_match,
        tag_suspect=args.tag_suspect,
        non_interactive=True,
    )


def _stdin_is_tty(stdin):
    if stdin is None:
        stdin = sys.stdin
    isatty = getattr(stdin, "isatty", None)
    return bool(isatty and isatty())


def default_session_factory(headless):
    from playwright_discovery import BusinessDiscoverySession
    return BusinessDiscoverySession(headless=headless, launch_args=[])


def default_places_factory(counter, max_searches):
    return PlacesApiSource(os.environ.get("GOOGLE_API_KEY"), counter, max_searches)


def default_robots_get(url, timeout=10):
    import requests
    return requests.get(url, timeout=timeout)


def load_google_robots(preset, get_fn):
    if preset is not None:
        return preset
    try:
        response = get_fn("https://www.google.com/robots.txt", timeout=15)
    except TypeError:
        response = get_fn("https://www.google.com/robots.txt")
    except Exception as exc:
        logger.error("Could not read Google robots.txt (%s); Maps left enabled", type(exc).__name__)
        return None
    status = getattr(response, "status_code", 200) or 200
    if int(status) >= 400:
        logger.error("Could not read Google robots.txt (HTTP %s); Maps left enabled", status)
        return None
    return getattr(response, "text", "") or ""


def main(argv=None, client_factory=None, session_factory=None, places_factory=None,
         visit_fn=None, robots_text=None, robots_get=None, stdin=None, input_fn=None, sleeper=None):
    args = parse_args(argv)
    input_fn = input_fn or input
    sleeper = sleeper or time.sleep
    session_factory = session_factory or default_session_factory
    places_factory = places_factory or default_places_factory
    robots_get = robots_get if robots_get is not None else default_robots_get
    noninteractive = bool(
        args.non_interactive
        or args.list
        or (args.venture and args.batch)
        or not _stdin_is_tty(stdin)
    )
    try:
        if noninteractive and not args.list and (not args.venture or not args.batch):
            raise CrmConfigError("Non-interactive runs need --venture and --batch (or use a TTY)")
        if "places_api" in (args.sources or "") and not os.environ.get("GOOGLE_API_KEY") and not args.list:
            if noninteractive or (args.venture and args.batch):
                raise CrmConfigError("places_api requires GOOGLE_API_KEY")
        url = None if client_factory else resolve_mcp_url(args.mcp_url)
        token = None if client_factory else resolve_token()
        if client_factory:
            client = client_factory()
        else:
            client = CrmClient(url=url, token=token, transport=args.mcp_transport)
            client.connect()
    except CrmConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except CrmAuthError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_MCP
    except CrmConnectionError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_MCP
    except Exception as exc:
        logger.error("crm_enrich failed: %s", type(exc).__name__)
        print(f"crm_enrich failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR

    try:
        if args.list:
            cmd_list(client, args.venture)
            return EXIT_OK
        if noninteractive:
            config = config_from_args(args)
            google_robots = load_google_robots(robots_text, robots_get)
            code, _previews, _summary = run_config(
                config, client, session_factory, places_factory, visit_fn, robots_get,
                google_robots, sleeper, input_fn, write_now=not config.dry_run,
            )
            return code
        config = interactive_config(client, args, input_fn)
        google_robots = load_google_robots(robots_text, robots_get)
        code, previews, _summary = run_config(
            config, client, session_factory, places_factory, visit_fn, robots_get,
            google_robots, sleeper, input_fn, write_now=False,
        )
        if code != EXIT_OK:
            return code
        if config.dry_run:
            return EXIT_OK
        field_count, lead_count = count_write_plan(previews)
        answer = _prompt(
            input_fn,
            f"Write {field_count} field updates to {lead_count} leads? [y/N]: ",
        ).strip().lower()
        if answer not in {"y", "yes"}:
            print("Preview saved. No CRM writes.")
            return EXIT_OK
        written, errors = apply_writes(client, previews, config, sleeper)
        print(f"Wrote {written} leads ({errors} errors).")
        return EXIT_OK if errors == 0 else EXIT_ERROR
    except CrmConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except CrmAuthError as exc:
        print(AUTH_MESSAGE, file=sys.stderr)
        return EXIT_MCP
    except CrmConnectionError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_MCP
    except KeyboardInterrupt:
        print("Interrupted. Checkpoint saved.")
        return EXIT_INTERRUPTED
    except Exception as exc:
        logger.error("crm_enrich failed: %s", type(exc).__name__)
        print(f"crm_enrich failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        closer = getattr(client, "close", None)
        if closer:
            closer()


if __name__ == "__main__":
    sys.exit(main())
