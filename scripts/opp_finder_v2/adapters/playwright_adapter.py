"""JSON-driven Playwright search. Dry-run loads fixture HTML with set_content."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from opp_finder_v2.adapters.base import (
    html_fixtures,
    offset_number,
    page_number,
    render_template,
    template_values,
)
from opp_finder_v2.artifacts import format_z, save_artifact
from opp_finder_v2.browser.detection import classify_page
from opp_finder_v2.browser.locators import all_matches, first_match, read_text
from opp_finder_v2.dedupe import canonical_url
from opp_finder_v2.listings import mapped_to_raw
from opp_finder_v2.models import Criteria, FetchResult, RawListing, RunOptions, SearchQuery, SiteConfig
from opp_finder_v2.politeness import Pacer

logger = logging.getLogger("opp-finder-v2")


def _read_fields(scope, fields: dict, base_url: str) -> dict:
    mapped = {}
    for dest, spec in (fields or {}).items():
        locator, strategy = first_match(scope, spec)
        if locator is None:
            continue
        # Field-level attr/regex/absolute_url live on the matching strategy.
        text = read_text(locator.first, strategy, base_url)
        if text:
            mapped[dest] = text
    return mapped


def extract_listings(page, site: SiteConfig, scraped_at: str, base_url: str) -> list[RawListing]:
    list_spec = (site.results or {}).get("list")
    fields = (site.results or {}).get("fields") or {}
    cards, _strategy = all_matches(page, list_spec)
    listings: list[RawListing] = []
    if not cards:
        return listings
    for card in cards:
        mapped = _read_fields(card, fields, base_url)
        raw = mapped_to_raw(mapped, site, scraped_at)
        if raw.title:
            listings.append(raw)
    return listings


def _screenshot(page) -> bytes | None:
    try:
        return page.screenshot(full_page=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Screenshot failed: %s", exc)
        return None


def _run_flow(page, site: SiteConfig, values: dict[str, str]) -> None:
    for step in site.search_flow or []:
        op = step.get("op")
        optional = bool(step.get("optional"))
        try:
            if op == "goto":
                page.goto(render_template(step.get("url") or "", values), wait_until="domcontentloaded")
            elif op == "wait_ms":
                page.wait_for_timeout(int(step.get("ms") or step.get("timeout_ms") or 0))
            elif op == "wait_for":
                locator, _strategy = first_match(page, step.get("locator"))
                if locator is not None:
                    locator.first.wait_for(timeout=int(step.get("timeout_ms") or 15000))
            elif op == "fill":
                locator, _strategy = first_match(page, step.get("locator"))
                if locator is not None:
                    locator.first.fill(render_template(step.get("value") or "", values))
            elif op == "click" or op == "dismiss":
                locator, _strategy = first_match(page, step.get("locator"))
                if locator is not None:
                    locator.first.click(timeout=3000)
            elif op == "press":
                locator, _strategy = first_match(page, step.get("locator"))
                if locator is not None:
                    locator.first.press(step.get("key") or "Enter")
            elif op == "select":
                locator, _strategy = first_match(page, step.get("locator"))
                if locator is not None:
                    locator.first.select_option(render_template(step.get("value") or "", values))
        except Exception as exc:  # noqa: BLE001
            if not optional:
                raise
            logger.debug("Optional step %s failed: %s", op, exc)


class PlaywrightAdapter:
    def fetch(
        self,
        site: SiteConfig,
        query: SearchQuery,
        criteria: Criteria,
        options: RunOptions,
        browser=None,
    ) -> FetchResult:
        if browser is None:
            return FetchResult(status="error", error="playwright session was not started")
        storage = None
        if (site.auth or {}).get("type") == "storage_state":
            env_name = site.auth.get("storage_state_env") or ""
            storage = os.environ.get(env_name) if env_name else None
        page = browser.new_page(storage_state=storage)
        if options.dry_run:
            return self._fetch_fixtures(page, site, options)
        return self._fetch_live(page, site, query, criteria, options)

    def _fetch_fixtures(self, page, site: SiteConfig, options: RunOptions) -> FetchResult:
        files = html_fixtures(site.id)
        if not files:
            return FetchResult(status="error", error=f"no HTML fixture for {site.id}")
        return self._consume_pages(
            page,
            site,
            options,
            pages=files,
            loader=lambda path: page.set_content(Path(path).read_text(encoding="utf-8")),
            url_for=lambda _path: site.base_url,
        )

    def _fetch_live(self, page, site, query, criteria, options: RunOptions) -> FetchResult:
        pagination = site.pagination or {}
        kind = pagination.get("type") or "none"
        max_pages = 1 if kind == "none" else int(pagination.get("max_pages") or 1)
        pacer = Pacer(site, dry_run=False, max_per_site=options.max_per_site)

        def loader(index: int) -> None:
            values = template_values(
                query,
                criteria,
                site,
                page=page_number(pagination, index),
                offset=offset_number(pagination, index),
            )
            if index == 0 and site.search_flow:
                _run_flow(page, site, values)
                return
            if kind in {"next_button", "infinite_scroll"} and index > 0:
                if kind == "next_button":
                    locator, _strategy = first_match(page, pagination.get("next"))
                    if locator is None:
                        raise StopIteration
                    locator.first.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded")
                else:
                    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                return
            url = render_template(site.search_url, values)
            page.goto(url, wait_until="domcontentloaded")

        indexes = list(range(max_pages))
        return self._consume_pages(
            page,
            site,
            options,
            pages=indexes,
            loader=loader,
            url_for=lambda _index: page.url or site.search_url,
            pacer=pacer,
        )

    def _consume_pages(self, page, site, options, pages, loader, url_for, pacer=None) -> FetchResult:
        pacer = pacer or Pacer(site, dry_run=True, max_per_site=options.max_per_site)
        pagination = site.pagination or {}
        stop_after = int(pagination.get("stop_when_no_new") or 2)
        scraped_at = format_z()
        listings: list[RawListing] = []
        seen: set[str] = set()
        stagnant = 0
        completed = 0
        artifacts = None
        for item in pages:
            if not pacer.acquire():
                break
            if len(listings) >= pacer.max_results:
                break
            try:
                loader(item)
            except StopIteration:
                break
            except Exception as exc:  # noqa: BLE001
                logger.info("Navigation failed for %s: %s", site.id, exc)
                if not listings:
                    return FetchResult(status="error", error=str(exc), pages=completed)
                break
            completed += 1
            html = ""
            try:
                html = page.content() or ""
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not read page content: %s", exc)
            current_url = url_for(item)
            try:
                current_url = page.url or current_url
            except Exception:
                pass
            kind = classify_page(current_url, html, extra=site.detection)
            if kind:
                if not options.no_artifacts:
                    artifacts = save_artifact(
                        options.artifacts_root or _artifacts_root(),
                        options.run_id or "run",
                        site.id,
                        kind,
                        url=current_url,
                        status=f"skipped_{kind}",
                        reason=kind,
                        html=html,
                        png_bytes=_screenshot(page),
                    )
                return FetchResult(
                    listings=listings[: pacer.max_results],
                    pages=completed,
                    status=f"skipped_{kind}",
                    error=kind,
                    artifacts=artifacts,
                )
            added = 0
            for raw in extract_listings(page, site, scraped_at, site.base_url):
                key = canonical_url(raw.url) or raw.title
                if key in seen:
                    continue
                seen.add(key)
                listings.append(raw)
                added += 1
                if len(listings) >= pacer.max_results:
                    break
            if added == 0:
                stagnant += 1
                if stagnant >= stop_after:
                    break
            else:
                stagnant = 0
        return FetchResult(
            listings=listings[: pacer.max_results],
            pages=completed,
            status="ok",
        )


def _artifacts_root() -> Path:
    return Path(__file__).resolve().parents[1] / "artifacts"
