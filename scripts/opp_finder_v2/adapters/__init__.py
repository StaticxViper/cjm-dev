"""Adapter registry. Optional custom hooks live under adapters/custom."""

from __future__ import annotations

from opp_finder_v2.adapters.api_adapter import ApiAdapter
from opp_finder_v2.adapters.custom import get_hook
from opp_finder_v2.adapters.playwright_adapter import PlaywrightAdapter
from opp_finder_v2.adapters.rss_adapter import RssAdapter
from opp_finder_v2.models import Criteria, FetchResult, RunOptions, SearchQuery, SiteConfig

_ADAPTERS = {
    "api": ApiAdapter,
    "rss": RssAdapter,
    "playwright": PlaywrightAdapter,
}


def fetch_site(
    site: SiteConfig,
    query: SearchQuery,
    criteria: Criteria,
    options: RunOptions,
    browser=None,
) -> FetchResult:
    hook = get_hook(site.custom)
    if hook is not None and hasattr(hook, "fetch"):
        result = hook.fetch(site, query, criteria, options, browser=browser)
    else:
        adapter_cls = _ADAPTERS.get(site.mode)
        if adapter_cls is None:
            return FetchResult(status="skipped_manual", error=f"mode {site.mode} is not fetched")
        result = adapter_cls().fetch(site, query, criteria, options, browser=browser)
    if hook is not None and hasattr(hook, "postprocess"):
        result.listings = [hook.postprocess(item) for item in result.listings]
    return result
