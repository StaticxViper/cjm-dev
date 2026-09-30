"""End-to-end search pipeline: discover → filter → score → enrich → CSV."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from analysis.outreach import generate_outreach
from analysis.scoring import rescore_with_contactability, score_automation, serialize_analysis_fields
from analysis.workflow import extract_workflow
from enrichment.contacts import enrich_company_and_contacts
from scrapers import SearchContext, enabled_scrapers
from utils.browser import BrowserSession
from utils.config import flatten_keywords, resolve_path
from utils.constants import ALL_JOBS_COLUMNS, QUALIFIED_COLUMNS, SEARCH_HISTORY_COLUMNS
from utils.csv_utils import append_csv_row, load_job_index, read_csv_rows, upsert_csv_row
from utils.geo import detect_remote_status, matches_target_geography
from utils.jobs import RawJob, utc_now_iso, utc_today
from utils.normalization import join_list, normalize_url

logger = logging.getLogger("opp-finder")


def _merge_jobs(existing: RawJob | dict, incoming: RawJob) -> dict[str, Any]:
    base = existing.to_dict() if isinstance(existing, RawJob) else dict(existing)
    new = incoming.to_dict()
    # Prefer longer descriptions / non-empty fields
    for key in (
        "job_title",
        "company_name",
        "location",
        "salary",
        "employment_type",
        "posting_date",
        "company_website",
        "application_url",
        "source_url",
        "job_description",
        "responsibilities",
        "requirements",
    ):
        old_val = str(base.get(key) or "")
        new_val = str(new.get(key) or "")
        if len(new_val) > len(old_val):
            base[key] = new_val
    sources = set()
    for part in str(base.get("sources_found") or "").split("|"):
        if part.strip():
            sources.add(part.strip())
    for part in str(new.get("sources_found") or "").split("|"):
        if part.strip():
            sources.add(part.strip())
    if incoming.source:
        sources.add(incoming.source)
    base["sources_found"] = " | ".join(sorted(sources))
    base["last_seen"] = utc_today()
    if not base.get("first_seen"):
        base["first_seen"] = utc_today()
    if not base.get("date_found"):
        base["date_found"] = utc_today()
    base["job_id"] = new.get("job_id") or base.get("job_id")
    return base


def dedupe_jobs(jobs: list[RawJob]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    url_index: dict[str, str] = {}
    for job in jobs:
        job.ensure_defaults()
        fp = job.fingerprint()
        norm_url = normalize_url(job.source_url or job.application_url)
        if norm_url and norm_url in url_index:
            fp = url_index[norm_url]
        elif norm_url:
            url_index[norm_url] = fp
        if fp in merged:
            merged[fp] = _merge_jobs(merged[fp], job)
        else:
            row = job.to_dict()
            row["first_seen"] = utc_today()
            row["last_seen"] = utc_today()
            row["date_found"] = utc_today()
            merged[fp] = row
    return list(merged.values())


def stage1_analyze(job: dict[str, Any]) -> dict[str, Any]:
    workflow = extract_workflow(job)
    job = dict(job)
    job["workflow_tasks"] = join_list(workflow["workflow_tasks"])
    job["workflow_evidence"] = join_list(workflow["workflow_evidence"])
    if not job.get("remote_status"):
        job["remote_status"] = detect_remote_status(job.get("location"), job.get("job_description"))
    analysis = serialize_analysis_fields(score_automation(job))
    job.update(analysis)
    job["outreach_status"] = "research"
    return job


def passes_qualification(job: dict[str, Any], config: dict[str, Any]) -> bool:
    qual = config.get("qualification") or {}
    min_auto = int(qual.get("minimum_automation_score", 55))
    min_opp = int(qual.get("minimum_opportunity_score", 60))
    auto = int(job.get("automation_score") or 0)
    opp = int(job.get("opportunity_score") or 0)
    tasks = str(job.get("workflow_tasks") or "").strip()
    if auto < min_auto or opp < min_opp:
        return False
    # Strategic gate: must answer what they pay someone to do
    return bool(tasks)


def stage2_enrich(job: dict[str, Any], config: dict[str, Any], browser: BrowserSession | None) -> dict[str, Any]:
    enriched = dict(job)
    contact = enrich_company_and_contacts(enriched, browser=browser)
    enriched.update(contact)
    # Rebuild analysis with updated contactability
    analysis = score_automation(enriched)
    analysis = rescore_with_contactability(analysis, int(contact.get("contactability_score") or 0))
    enriched.update(serialize_analysis_fields(analysis))
    outreach = generate_outreach(enriched, config)
    enriched.update(outreach)
    # Final strategic gate for ready_to_contact
    has_contact = bool(enriched.get("contact_email") or enriched.get("contact_phone") or enriched.get("company_website"))
    if passes_qualification(enriched, config) and has_contact and enriched.get("demo_concept"):
        enriched["outreach_status"] = "ready_to_contact"
    elif passes_qualification(enriched, config):
        enriched["outreach_status"] = "qualified"
    else:
        enriched["outreach_status"] = "research"
    enriched["date_contacted"] = enriched.get("date_contacted") or ""
    enriched["follow_up_date"] = enriched.get("follow_up_date") or ""
    enriched["notes"] = enriched.get("notes") or ""
    enriched["contact_verified"] = (
        "true" if str(enriched.get("contact_verified")).lower() in {"1", "true", "yes"} else "false"
    )
    return enriched


def _print_job_progress(job: dict[str, Any]) -> None:
    logger.info("[JOB] %s", job.get("job_title") or "")
    logger.info("[COMPANY] %s", job.get("company_name") or "")
    logger.info("[LOCATION] %s", job.get("location") or job.get("remote_status") or "")
    logger.info("[ANALYSIS]")
    logger.info("Automation Score: %s/100", job.get("automation_score"))
    logger.info("Opportunity Score: %s/100", job.get("opportunity_score"))
    tasks = [t.strip() for t in str(job.get("workflow_tasks") or "").split("|") if t.strip()]
    if tasks:
        logger.info("Workflow:")
        for task in tasks[:6]:
            logger.info("- %s", task)
    if job.get("automation_opportunity"):
        logger.info("Potential Automation:")
        logger.info("%s", job.get("automation_opportunity"))


def run_search(config: dict[str, Any], options: dict[str, Any]) -> dict[str, int]:
    """Execute a full search run. options from CLI."""
    search_cfg = config.get("search") or {}
    max_total = int(options.get("limit") or search_cfg.get("max_total_jobs") or 250)
    max_per_kw = int(search_cfg.get("max_results_per_keyword") or 25)
    max_company = int(search_cfg.get("max_company_research") or 100)
    max_contacts = int(search_cfg.get("max_qualified_contacts") or 50)

    keywords = options.get("keywords") or flatten_keywords(config)
    if options.get("keyword"):
        keywords = [options["keyword"]]

    location_phrases = list(search_cfg.get("location_phrases") or ["South Jersey"])
    include_remote = bool(config.get("include_remote", True))
    if options.get("remote_only"):
        include_remote = True
    if options.get("south_nj_only") and options.get("remote_only") is not True:
        # south-nj mode still allows remote unless user asked otherwise
        pass
    if options.get("no_remote"):
        include_remote = False

    browser_cfg = dict(config.get("browser") or {})
    if options.get("headless") is not None:
        browser_cfg["headless"] = bool(options["headless"])

    all_path = resolve_path(config, "all_jobs")
    qual_path = resolve_path(config, "qualified")
    hist_path = resolve_path(config, "search_history")
    all_path.parent.mkdir(parents=True, exist_ok=True)

    existing_index = load_job_index(all_path, "job_id")
    refresh = bool(options.get("refresh"))
    run_id = uuid.uuid4().hex[:12]

    stats = {
        "discovered": 0,
        "after_dedupe": 0,
        "geo_kept": 0,
        "saved_all": 0,
        "qualified": 0,
        "skipped_existing": 0,
    }

    with BrowserSession(browser_cfg) as browser:
        ctx = SearchContext(
            config=config,
            keywords=keywords,
            location_phrases=location_phrases,
            include_remote=include_remote,
            south_nj_only=bool(options.get("south_nj_only")),
            remote_only=bool(options.get("remote_only")),
            max_results_per_keyword=max_per_kw,
            max_total_jobs=max_total,
            browser=browser,
            verbose=bool(options.get("verbose")),
        )

        raw_jobs: list[RawJob] = []
        scrapers = enabled_scrapers(config)
        # Small verification runs: prefer Google discovery to avoid long multi-source hangs.
        if max_total <= 10:
            scrapers = [s for s in scrapers if getattr(s, "name", "") == "google"] or scrapers[:1]
        for scraper in scrapers:
            if len(raw_jobs) >= max_total:
                break
            try:
                found = scraper.search(ctx) or []
            except Exception as exc:  # noqa: BLE001 — continue other sources
                logger.error("[ERROR] Source %s failed: %s", getattr(scraper, "name", "?"), exc)
                append_csv_row(
                    hist_path,
                    {
                        "run_id": run_id,
                        "timestamp": utc_now_iso(),
                        "source": getattr(scraper, "name", ""),
                        "query": "",
                        "results_count": 0,
                        "status": "error",
                        "notes": str(exc)[:300],
                    },
                    SEARCH_HISTORY_COLUMNS,
                )
                continue
            logger.info("[SEARCH] %s returned %d jobs", scraper.name, len(found))
            append_csv_row(
                hist_path,
                {
                    "run_id": run_id,
                    "timestamp": utc_now_iso(),
                    "source": scraper.name,
                    "query": f"{len(keywords)} keywords",
                    "results_count": len(found),
                    "status": "blocked" if browser.is_blocked(scraper.name) else "ok",
                    "notes": "",
                },
                SEARCH_HISTORY_COLUMNS,
            )
            raw_jobs.extend(found)
            ctx.collected = list(raw_jobs)

        stats["discovered"] = len(raw_jobs)
        deduped = dedupe_jobs(raw_jobs)
        stats["after_dedupe"] = len(deduped)

        company_research_count = 0
        qualified_contact_count = 0

        for job in deduped:
            # Geographic / remote filter
            allow_remote = include_remote
            if options.get("remote_only"):
                rs = detect_remote_status(job.get("location"), job.get("job_description"))
                if rs != "remote":
                    continue
            elif options.get("south_nj_only") and not options.get("remote_only"):
                # Keep south NJ locals + remotes (if include_remote)
                if not matches_target_geography(
                    job.get("location"),
                    job.get("job_description"),
                    {**config, "include_remote": include_remote},
                    allow_remote=include_remote,
                ):
                    continue
            else:
                if not matches_target_geography(
                    job.get("location"),
                    job.get("job_description"),
                    {**config, "include_remote": include_remote},
                    allow_remote=include_remote,
                ):
                    continue

            stats["geo_kept"] += 1
            job_id = str(job.get("job_id") or "")
            if job_id and job_id in existing_index and not refresh:
                stats["skipped_existing"] += 1
                prev = existing_index[job_id]
                merged = dict(prev)
                merged["last_seen"] = utc_today()
                old_sources = {
                    s.strip()
                    for s in str(prev.get("sources_found") or "").split("|")
                    if s.strip()
                }
                new_sources = {
                    s.strip()
                    for s in str(job.get("sources_found") or "").split("|")
                    if s.strip()
                }
                merged["sources_found"] = " | ".join(sorted(old_sources | new_sources))
                upsert_csv_row(all_path, merged, ALL_JOBS_COLUMNS, ["job_id"])
                continue

            analyzed = stage1_analyze(job)
            _print_job_progress(analyzed)
            upsert_csv_row(all_path, analyzed, ALL_JOBS_COLUMNS, ["job_id"])
            stats["saved_all"] += 1
            existing_index[job_id] = analyzed

            if not passes_qualification(analyzed, config):
                continue
            if company_research_count >= max_company:
                continue

            company_research_count += 1
            deep = stage2_enrich(analyzed, config, browser)
            _print_job_progress(deep)
            if deep.get("recommended_contact_role") or deep.get("contact_email"):
                logger.info("[CONTACT]")
                logger.info("%s", deep.get("recommended_contact_role") or "")
                if deep.get("contact_email"):
                    logger.info("%s", deep.get("contact_email"))
                elif deep.get("company_website"):
                    logger.info("%s", deep.get("company_website"))
            if deep.get("outreach_message"):
                logger.info("[OUTREACH]")
                logger.info("Draft generated.")

            # Persist updated all_jobs row with richer fields where columns overlap
            upsert_csv_row(all_path, deep, ALL_JOBS_COLUMNS, ["job_id"])

            if passes_qualification(deep, config):
                if qualified_contact_count >= max_contacts:
                    continue
                upsert_csv_row(qual_path, deep, QUALIFIED_COLUMNS, ["source_url", "job_title", "company_name"])
                qualified_contact_count += 1
                stats["qualified"] += 1
                logger.info("[SAVED] %s", qual_path.name)

    logger.info(
        "Run complete. discovered=%d deduped=%d geo_kept=%d saved=%d qualified=%d skipped_existing=%d",
        stats["discovered"],
        stats["after_dedupe"],
        stats["geo_kept"],
        stats["saved_all"],
        stats["qualified"],
        stats["skipped_existing"],
    )
    return stats
