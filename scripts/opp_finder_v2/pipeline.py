"""Run enabled sites one at a time, score, dedupe, and write after each site."""

from __future__ import annotations

import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from opp_finder_v2.adapters import fetch_site
from opp_finder_v2.artifacts import format_z, run_id_from
from opp_finder_v2.browser.session import BrowserSession
from opp_finder_v2.config import PACKAGE_DIR, SiteCatalog, load_criteria, load_sites, select_sites
from opp_finder_v2.dedupe import dedupe_opportunities
from opp_finder_v2.listings import build_opportunity
from opp_finder_v2.models import Criteria, FetchResult, Opportunity, RunOptions, SearchQuery, SiteConfig, SiteResult
from opp_finder_v2.output import build_document, csv_path_for, write_csv, write_json

logger = logging.getLogger("opp-finder-v2")


def gate_status(site: SiteConfig, options: RunOptions) -> str | None:
    """Return a skip status, or None when the site should be fetched."""
    if site.mode == "none":
        return "skipped_manual"
    login = site.access == "login_required" or (site.auth or {}).get("type") == "storage_state"
    if login:
        env_name = (site.auth or {}).get("storage_state_env") or ""
        path = os.environ.get(env_name, "") if env_name else ""
        env_ok = bool(env_name and path and Path(path).is_file())
        if not (site.enabled and options.allow_login and env_ok):
            return "skipped_auth_disabled"
    if site.companies is not None and len(site.companies) == 0 and "{company}" in (site.search_url or ""):
        return "skipped_no_companies"
    if site.mode not in {"api", "rss", "playwright"}:
        return "skipped_manual"
    return None


def _apply_overrides(criteria: Criteria, options: RunOptions) -> None:
    if options.keywords is not None:
        criteria.keywords_any = list(options.keywords)
    if options.since_days is not None:
        criteria.posted_within_days = options.since_days


def _assign_kept(results: list[SiteResult], opportunities: list[Opportunity]) -> None:
    counts: Counter[str] = Counter(opp.source_site for opp in opportunities)
    for result in results:
        result.kept = counts.get(result.id, 0)


def _print_summary(document: dict) -> None:
    print(
        f"{'site':<20} {'status':<24} {'fetched':>7} {'matched':>7} "
        f"{'kept':>6} {'pages':>5} {'seconds':>8}  artifacts"
    )
    for site in document["run"]["sites"]:
        print(
            f"{site['id']:<20} {site['status']:<24} {site['fetched']:>7} "
            f"{site['matched']:>7} {site['kept']:>6} {site['pages']:>5} "
            f"{site['duration_s']:>8}  {site.get('artifacts') or ''}"
        )
    totals = document["run"]["totals"]
    print(
        f"totals fetched={totals['fetched']} after_filters={totals['after_filters']} "
        f"after_dedupe={totals['after_dedupe']} merged={totals['merged']} "
        f"dropped={totals['dropped']}"
    )


def run(options: RunOptions, catalog: SiteCatalog | None = None, criteria: Criteria | None = None) -> int:
    catalog = catalog or load_sites(options.config_path)
    criteria = criteria or load_criteria(options.criteria_path)
    _apply_overrides(criteria, options)
    selected = select_sites(catalog, options.sites)
    started = datetime.now(timezone.utc).replace(microsecond=0)
    options.run_id = options.run_id or run_id_from(started)
    if options.artifacts_root is None:
        options.artifacts_root = PACKAGE_DIR / "artifacts"
    out_path = options.out or (PACKAGE_DIR / "output" / f"opps_{options.run_id}.json")
    query = SearchQuery(keywords=list(criteria.keywords_any))
    started_at = format_z(started)

    collected: list[Opportunity] = []
    site_results: list[SiteResult] = []
    dropped: Counter[str] = Counter()
    browser: BrowserSession | None = None

    def persist() -> dict:
        deduped, merges = dedupe_opportunities(collected, criteria, started)
        _assign_kept(site_results, deduped)
        document = build_document(
            run_id=options.run_id,
            started_at=started_at,
            finished_at=format_z(),
            dry_run=options.dry_run,
            criteria=criteria,
            sites=site_results,
            opportunities=deduped,
            dropped={key: dropped[key] for key in sorted(dropped)},
            merged=merges,
            fetched=sum(item.fetched for item in site_results),
        )
        if options.format in {"json", "both"}:
            write_json(out_path, document)
        if options.format in {"csv", "both"}:
            write_csv(csv_path_for(out_path), deduped)
        return document

    try:
        for site in selected:
            clock = time.monotonic()
            status = gate_status(site, options)
            if status:
                site_results.append(
                    SiteResult(
                        id=site.id,
                        status=status,
                        duration_s=time.monotonic() - clock,
                    )
                )
                logger.info("[%s] %s", site.id, status)
                persist()
                continue
            if site.mode == "playwright" and browser is None:
                browser = BrowserSession(headless=not options.headful)
                browser.start()
            try:
                fetched = fetch_site(site, query, criteria, options, browser=browser)
            except Exception as exc:  # noqa: BLE001 — one site must not abort the run
                logger.exception("[%s] failed", site.id)
                fetched = FetchResult(status="error", error=str(exc))
            matched: list[Opportunity] = []
            for raw in fetched.listings:
                opp, reason = build_opportunity(raw, site, criteria, started)
                if opp is None or reason:
                    dropped[reason or "empty_title"] += 1
                    continue
                matched.append(opp)
            collected.extend(matched)
            site_results.append(
                SiteResult(
                    id=site.id,
                    status=fetched.status,
                    fetched=len(fetched.listings),
                    matched=len(matched),
                    pages=fetched.pages,
                    duration_s=time.monotonic() - clock,
                    error=fetched.error,
                    artifacts=fetched.artifacts,
                )
            )
            logger.info(
                "[%s] %s fetched=%s matched=%s",
                site.id,
                fetched.status,
                len(fetched.listings),
                len(matched),
            )
            persist()
    finally:
        if browser is not None:
            browser.close()

    document = persist()
    _print_summary(document)
    if not site_results:
        return 3
    if all(item.status != "ok" for item in site_results):
        return 3
    return 0
