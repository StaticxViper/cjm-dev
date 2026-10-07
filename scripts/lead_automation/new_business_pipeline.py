"""New-business discovery run. Standard keyword discovery is not used here."""
from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from email_discovery import EmailDiscoverySession
from leadfilter import identity_keys_from_row, load_existing_identities
from new_business_dedupe import SeenCache, dedupe_new_businesses
from new_business_email import enrich_new_business_lead
from new_business_geo import build_selection, filter_geography
from new_business_scoring import contact_drop_reason, load_score_rules, score_new_business
from new_business_sources import select_adapters
from new_business_website import classify_website
from search_history import SearchHistory

logger = logging.getLogger("leadgen")

OUTPUT_FIELDS = (
    "lead_id",
    "business_name",
    "alternate_names",
    "category",
    "description",
    "registration_date",
    "formation_date",
    "filing_date",
    "opening_date",
    "newness_date",
    "newness_age_days",
    "newness_evidence",
    "date_discovered",
    "business_status",
    "state",
    "county",
    "city",
    "zip",
    "address",
    "geo_unverified",
    "phone",
    "website",
    "website_status",
    "website_issues",
    "website_quality_score",
    "maps_url",
    "place_id",
    "email",
    "email_source",
    "email_source_url",
    "email_confidence",
    "email_evidence",
    "contact_form_url",
    "public_contacts",
    "lead_score",
    "new_business_score",
    "score_reasons",
    "score_breakdown",
    "sources",
    "dedupe_match",
    "merged_from",
    "possible_duplicate_of",
    "first_seen",
    "last_seen",
)
JSON_LIST_FIELDS = {"score_breakdown", "newness_evidence", "sources", "public_contacts"}
JOIN_LIST_FIELDS = {"alternate_names", "website_issues", "score_reasons"}
INACTIVE_STATUSES = frozenset({
    "inactive",
    "dissolved",
    "revoked",
    "withdrawn",
    "delinquent",
    "cancelled",
    "canceled",
    "expired",
    "closed",
    "closed_temporarily",
    "closed_permanently",
})


def _today(value=None):
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.date()
    return value


def _log_stage(number, name, detail=None):
    try:
        from leadgen import log_stage
        log_stage(number, name, detail, total=7)
    except Exception:
        if detail:
            logger.critical("[STAGE %d/7] %s — %s", number, name, detail)
        else:
            logger.critical("[STAGE %d/7] %s", number, name)


def _log_step(stage, step, name, detail=None):
    try:
        from leadgen import log_step
        log_step(stage, step, name, detail)
    except Exception:
        logger.info("[STEP %d.%d] %s", stage, step, name)


def output_paths(config):
    json_path = getattr(config, "json_output", None) or "new_business_leads.json"
    if json_path in ("leads_output.json", ""):
        json_path = "new_business_leads.json"
    csv_path = getattr(config, "nb_csv_output", None) or "new_business_leads.csv"
    return json_path, csv_path


def refuse_dashboard(config):
    mode = getattr(config, "output_mode", "both") or "both"
    if mode == "dashboard":
        logger.warning(
            "Dashboard output is not available in new-business mode; writing JSON and CSV only."
        )
        config.output_mode = "both"
        return True
    if mode == "both":
        return False
    return False


def save_new_business_json(rows, json_path):
    path = Path(json_path)
    existing = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read %s: %s", path, exc)
    combined = list(existing) + list(rows)
    by_id = {}
    order = []
    for row in combined:
        lead_id = row.get("lead_id") or ""
        if not lead_id:
            continue
        if lead_id not in by_id:
            order.append(lead_id)
        by_id[lead_id] = row
    deduped = [by_id[lead_id] for lead_id in order]
    deduped.sort(key=lambda row: -int(row.get("new_business_score") or 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(deduped, indent=2) + "\n", encoding="utf-8")
    return deduped


def _csv_cell(key, value):
    if key in JSON_LIST_FIELDS:
        return json.dumps(value if value is not None else [], separators=(",", ":"), ensure_ascii=False)
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def save_new_business_csv(rows, csv_path):
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(key, row.get(key)) for key in OUTPUT_FIELDS})
    return path


def _blank_row():
    row = {key: None for key in OUTPUT_FIELDS}
    for key in ("alternate_names", "newness_evidence", "website_issues", "public_contacts", "score_reasons", "sources"):
        row[key] = []
    row["score_breakdown"] = {}
    row["geo_unverified"] = False
    row["website"] = ""
    row["email"] = ""
    return row


def _finalize_row(row, today):
    output = _blank_row()
    for key in OUTPUT_FIELDS:
        if key in row and row.get(key) is not None:
            output[key] = row.get(key)
    for key in ("alternate_names", "newness_evidence", "website_issues", "public_contacts", "score_reasons", "sources"):
        output[key] = list(row.get(key) or [])
    output["score_breakdown"] = dict(row.get("score_breakdown") or {})
    output["geo_unverified"] = bool(row.get("geo_unverified"))
    output["website"] = row.get("website") or ""
    output["email"] = row.get("email") or ""
    output["phone"] = row.get("phone") or row.get("phone_google") or ""
    if output["newness_date"]:
        try:
            parsed = datetime.strptime(str(output["newness_date"])[:10], "%Y-%m-%d").date()
            output["newness_age_days"] = (today - parsed).days
        except ValueError:
            output["newness_age_days"] = None
    output["date_discovered"] = today.isoformat()
    return output


def _is_inactive(row):
    status = str(row.get("business_status") or "").strip().lower()
    return status in INACTIVE_STATUSES


def _conflicts_existing(row, identities):
    keys = identity_keys_from_row({
        "place_id": row.get("place_id"),
        "profile_url": row.get("profile_url") or row.get("maps_url"),
        "business_name": row.get("business_name"),
        "phone_google": row.get("phone") or row.get("phone_google"),
        "address": row.get("address"),
    })
    return any(key in identities for key in keys)


def _is_contacted(row, contacted):
    email = str(row.get("email") or "").strip().lower()
    return bool(email and email in contacted)


def apply_website(row, *, mode, today, threshold, dry_run=False):
    if dry_run and row.get("website_status"):
        return row
    url = (row.get("website") or "").strip()
    blocked = bool(row.get("website_search_blocked") or row.get("maps_blocked"))
    if dry_run and not url and not row.get("website_search_ran"):
        classified = classify_website(
            url="",
            search_ran=False,
            search_blocked=blocked,
            check_mode=mode,
            today=today,
            poor_website_min_quality_score=threshold,
        )
    elif dry_run and url:
        classified = classify_website(
            url=url,
            search_ran=False,
            check_mode=mode,
            today=today,
            poor_website_min_quality_score=threshold,
        )
    else:
        # A Maps check with no URL is not enough to call the business no_website.
        # Google result pages are robots-disallowed, so an empty Maps listing
        # stays unknown unless a website search actually ran.
        search_ran = bool(url) or bool(row.get("website_search_ran"))
        if blocked and not url:
            search_ran = False
        classified = classify_website(
            url=url,
            search_ran=search_ran,
            search_blocked=blocked and not url,
            check_mode=mode,
            today=today,
            poor_website_min_quality_score=threshold,
        )
    row["website"] = classified.get("website") or ""
    row["website_status"] = classified.get("website_status")
    row["website_issues"] = list(classified.get("website_issues") or [])
    row["website_quality_score"] = classified.get("website_quality_score")
    if classified.get("contact_form_url") and not row.get("contact_form_url"):
        row["contact_form_url"] = classified.get("contact_form_url")
    for key in ("https", "has_viewport", "html_length", "has_cta"):
        if key in classified:
            row[key] = classified[key]
    return row


def _lead_score(row):
    from leadgen import score_lead

    status = row.get("website_status")
    has_website = bool(row.get("website")) and status not in ("no_website", "unknown", None, "")
    return score_lead(
        has_website,
        bool(row.get("https")),
        bool(row.get("has_viewport")),
        row.get("html_length") or 0,
        bool(row.get("email")),
        bool(row.get("has_cta")),
        row.get("rating"),
        row.get("user_ratings_total"),
        row.get("business_status"),
    )


def _history_fresh(history, adapter_id, state, city, radius, max_age_days):
    from search_history import make_search_key

    key = make_search_key(
        "new_business",
        f"new_business:{adapter_id}",
        city or "",
        state or "",
        search_radius=radius,
    )
    prior = history.get(key)
    if not prior:
        return False, key
    completed = prior.get("completed_at") or ""
    try:
        stamp = datetime.fromisoformat(completed.replace("Z", "+00:00"))
    except ValueError:
        return False, key
    age = (datetime.now(timezone.utc) - stamp).days
    return age <= int(max_age_days or 365), key


def _write_artifact(config, run_ts, source_id, url, reason, html=""):
    if not getattr(config, "nb_artifacts", True):
        return None
    folder = Path("new_business_artifacts") / run_ts / source_id
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "url": url,
        "status": reason,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    if html:
        (folder / "response.html").write_text(html, encoding="utf-8")
    return str(folder)


def run_new_business(config, today=None):
    """Discover, filter, score, and write new-business leads. Returns the summary."""
    today = _today(today)
    dry_run = bool(getattr(config, "nb_dry_run", False))
    refuse_dashboard(config)
    mode = getattr(config, "output_mode", "both") or "both"
    if mode not in ("json", "csv", "both"):
        mode = "both"
        config.output_mode = mode
    json_path, csv_path = output_paths(config)
    rules = load_score_rules(getattr(config, "nb_score_rules_path", None))
    very_new = int(getattr(config, "nb_very_new_days", rules.get("very_new_days", 90)))
    max_age = int(getattr(config, "nb_max_age_days", rules.get("max_age_days", 365)))
    min_score = int(getattr(config, "nb_min_score", rules.get("min_new_business_score", 50)))
    rules = dict(rules)
    rules["very_new_days"] = very_new
    rules["max_age_days"] = max_age
    since = today - timedelta(days=max_age)
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    _log_stage(1, "Source discovery", "new-business")
    selected = getattr(config, "nb_sources", None)
    if isinstance(selected, str):
        selected = [part.strip() for part in selected.split(",") if part.strip()]
    try:
        adapters = select_adapters(selected or None)
    except ValueError as exc:
        logger.error("%s", exc)
        raise SystemExit(str(exc)) from exc

    region_names = []
    if getattr(config, "nb_region", None):
        region_names.append(config.nb_region)
    selection = build_selection(
        locations=getattr(config, "locations", None),
        counties=getattr(config, "nb_counties", None),
        zips=getattr(config, "nb_zips", None),
        radius_m=getattr(config, "search_radius", 50000),
        region_names=region_names,
        regions_file=getattr(config, "nb_regions_file", None),
    )
    _log_stage(2, "Geography filter", f"since {since.isoformat()}")

    seen = SeenCache(getattr(config, "nb_seen_path", None) or "new_business_seen.json")
    standard_path = "leads_output.json"
    identities = load_existing_identities(standard_path)
    identities.update(load_existing_identities(json_path))
    try:
        from leadgen import _load_contacted_emails
        contacted = _load_contacted_emails()
    except Exception:
        contacted = set()
    history = SearchHistory(getattr(config, "search_history_path", None))

    maps_adapter = next((adapter for adapter in adapters if adapter.id == "google_maps" and adapter.runnable()), None)
    collected = []
    source_reports = []
    drop_counts = {
        "franchise": 0,
        "inactive_or_closed": 0,
        "no_contact_info": 0,
        "below_min_score": 0,
        "out_of_geography": 0,
        "already_seen": 0,
        "established_business": 0,
    }
    email_session = None
    if getattr(config, "lead_enrichment", True):
        email_session = EmailDiscoverySession(
            cache_path=getattr(config, "nb_enrichment_cache_path", None) or "new_business_enrichment_cache.json",
            ttl_days=int(getattr(config, "nb_enrichment_ttl_days", 30) or 30),
            refresh=bool(getattr(config, "nb_refresh_enrichment", False)),
        )

    kept_rows = []
    dedupe_stats = {"merged_duplicates": 0, "possible_duplicates": 0}
    try:
        for adapter in adapters:
            started = datetime.now(timezone.utc)
            report = {
                "id": adapter.id,
                "status": "ok",
                "records_fetched": 0,
                "in_geography": 0,
                "new_within_max_age": 0,
                "kept": 0,
                "duration_s": 0,
                "artifacts": None,
            }
            if not adapter.runnable():
                report["status"] = "disabled" if adapter.status != "blocked" else "blocked"
                source_reports.append(report)
                _log_step(1, 1, "Skip source", f"{adapter.id} {report['status']}")
                continue
            state = ""
            city = ""
            locations = getattr(config, "locations", None) or []
            if locations:
                state, city = locations[0][0], locations[0][1]
            fresh, history_key = _history_fresh(
                history, adapter.id, state, city, getattr(config, "search_radius", 50000), max_age,
            )
            if fresh and getattr(config, "skip_searched", True) and not dry_run:
                report["status"] = "skipped_history"
                source_reports.append(report)
                continue
            try:
                if not dry_run and adapter.id != "google_maps":
                    access = adapter.check_access()
                    if access != "ok":
                        report["status"] = access
                        report["artifacts"] = _write_artifact(config, run_ts, adapter.id, adapter.url, access)
                        source_reports.append(report)
                        continue
                limit = int(getattr(config, "nb_max_records_per_source", 200) or 200)
                _log_step(1, 2, "Fetch source", adapter.id)
                records = adapter.fetch(None, since, limit, dry_run=dry_run)
                report["records_fetched"] = len(records)
                geo_rows, geo_dropped = filter_geography(records, selection)
                drop_counts["out_of_geography"] += geo_dropped
                report["in_geography"] = len(geo_rows)
                report["new_within_max_age"] = len(geo_rows)
                if adapter.id == "google_maps":
                    report["status"] = "ok"
                    report["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 3)
                    source_reports.append(report)
                    continue
                if maps_adapter is not None and adapter.id != "google_maps":
                    _log_stage(3, "Maps/website verification", adapter.id)
                    maps_adapter.verify(
                        geo_rows,
                        limit=min(20, limit),
                        dry_run=dry_run,
                        headless=not bool(getattr(config, "nb_headful", False)),
                    )
                threshold = int(rules.get("poor_website_min_quality_score") or 41)
                for row in geo_rows:
                    apply_website(
                        row,
                        mode=getattr(config, "nb_website_check", "deep"),
                        today=today,
                        threshold=threshold,
                        dry_run=dry_run,
                    )
                collected.extend(geo_rows)
                if not dry_run:
                    history.record_search(
                        leadgen_type="new_business",
                        keyword=f"new_business:{adapter.id}",
                        city=city,
                        state=state,
                        search_radius=getattr(config, "search_radius", 50000),
                        businesses_found=len(geo_rows),
                        status="completed",
                    )
            except PermissionError as exc:
                report["status"] = str(exc) or "blocked"
                report["artifacts"] = _write_artifact(config, run_ts, adapter.id, adapter.url, report["status"])
            except Exception as exc:
                logger.error("Source %s failed: %s", adapter.id, exc)
                report["status"] = "error"
                report["artifacts"] = _write_artifact(
                    config, run_ts, adapter.id, adapter.url, f"error: {exc}",
                )
            report["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 3)
            source_reports.append(report)

        _log_stage(4, "Dedupe", f"{len(collected)} records")
        merged, dedupe_stats = dedupe_new_businesses(collected, seen_cache=seen)
        if email_session is not None:
            _log_stage(5, "Email enrichment", f"{len(merged)} businesses")
            for row in merged:
                website_before = (row.get("website") or "").strip()
                enrich_new_business_lead(
                    row,
                    city=row.get("city"),
                    state=row.get("state"),
                    session=email_session,
                    allow_google=not dry_run,
                )
                website_after = (row.get("website") or "").strip()
                if website_after and website_after != website_before:
                    apply_website(
                        row,
                        mode=getattr(config, "nb_website_check", "deep"),
                        today=today,
                        threshold=int(rules.get("poor_website_min_quality_score") or 41),
                        dry_run=dry_run,
                    )
        else:
            _log_stage(5, "Email enrichment", "skipped by configuration")

        _log_stage(6, "Scoring", f"min {min_score}")
        from leadgen import is_franchise

        include_seen = bool(getattr(config, "nb_include_seen", False))
        for row in merged:
            if getattr(config, "filter_franchises", True) and is_franchise(row.get("business_name"), row.get("website")):
                drop_counts["franchise"] += 1
                continue
            if _is_inactive(row):
                drop_counts["inactive_or_closed"] += 1
                continue
            if contact_drop_reason(row, rules):
                drop_counts["no_contact_info"] += 1
                continue
            score, reasons, breakdown = score_new_business(
                row,
                rules,
                today=today,
                very_new_days=very_new,
                max_age_days=max_age,
            )
            row["new_business_score"] = score
            row["score_reasons"] = reasons
            row["score_breakdown"] = breakdown
            row["lead_score"] = _lead_score(row)
            if "established_business" in breakdown and score < min_score:
                drop_counts["established_business"] += 1
                continue
            if score < min_score:
                drop_counts["below_min_score"] += 1
                continue
            lead_id = row.get("lead_id")
            if lead_id and seen.already_output(lead_id) and not include_seen:
                drop_counts["already_seen"] += 1
                continue
            if _conflicts_existing(row, identities) or _is_contacted(row, contacted):
                drop_counts["already_seen"] += 1
                continue
            finalized = _finalize_row(row, today)
            if lead_id:
                seen.mark_output(lead_id, finalized.get("newness_date"))
                first_seen, last_seen = seen.seen_dates(lead_id)
                finalized["first_seen"] = first_seen
                finalized["last_seen"] = last_seen
            kept_rows.append(finalized)
        for report in source_reports:
            if report["status"] == "ok":
                report["kept"] = len(kept_rows)
    finally:
        if email_session is not None:
            email_session.close()
        seen.save()

    _log_stage(7, "Output", mode)
    written = kept_rows
    if mode in ("json", "both"):
        written = save_new_business_json(kept_rows, json_path)
    if mode in ("csv", "both"):
        save_new_business_csv(written, csv_path)

    website_counts = {}
    emails_found = 0
    for row in written:
        status = row.get("website_status") or "unknown"
        website_counts[status] = website_counts.get(status, 0) + 1
        if row.get("email"):
            emails_found += 1
    summary = {
        "started_at": run_ts,
        "mode": "new-business",
        "dry_run": dry_run,
        "sources": source_reports,
        "totals": {
            "discovered": len(collected),
            "merged_duplicates": dedupe_stats["merged_duplicates"] if collected else 0,
            "possible_duplicates": sum(1 for row in written if row.get("possible_duplicate_of")),
            "emails_found": emails_found,
            "website_status": website_counts,
            "kept": len(written),
        },
        "drops": drop_counts,
        "json_path": json_path if mode in ("json", "both") else None,
        "csv_path": csv_path if mode in ("csv", "both") else None,
    }
    sidecar = Path(f"new_business_run_{run_ts}.json")
    sidecar.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    history.record_run({
        "started_at": run_ts,
        "leadgen_type": "new_business",
        "stats": summary["totals"],
        "drops": drop_counts,
        "sources": [item.get("id") for item in source_reports],
    })
    history.save()
    _print_summary(summary)
    return summary


def _print_summary(summary):
    print()
    print("New-business discovery complete")
    totals = summary.get("totals") or {}
    print(f"Discovered: {totals.get('discovered', 0)}")
    print(f"Merged duplicates: {totals.get('merged_duplicates', 0)}")
    print(f"Possible duplicates: {totals.get('possible_duplicates', 0)}")
    print(f"Emails found: {totals.get('emails_found', 0)}")
    print(f"Kept: {totals.get('kept', 0)}")
    print("Website status: " + json.dumps(totals.get("website_status") or {}))
    print("Drops: " + json.dumps(summary.get("drops") or {}))
    for source in summary.get("sources") or []:
        print(
            f"  {source.get('id')}: {source.get('status')} "
            f"fetched={source.get('records_fetched')} "
            f"in_geography={source.get('in_geography')} "
            f"kept={source.get('kept')}"
        )
    if summary.get("json_path"):
        print(f"JSON: {summary['json_path']}")
    if summary.get("csv_path"):
        print(f"CSV: {summary['csv_path']}")
    print()
