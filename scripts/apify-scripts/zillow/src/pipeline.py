"""Map Actor input onto the Zillow agent pipeline.

The search, parse, dedupe, and enrichment code stays in
scripts/zillow_automation. This module only reads input, applies the run
caps, and shapes dataset rows and the key-value summary.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

try:
    from .runtime import playwright_proxy, prepare_imports
except ImportError:
    from runtime import playwright_proxy, prepare_imports


_ROOT = prepare_imports()
for _entry in (
    _ROOT / "scripts",
    _ROOT / "scripts" / "lead_automation",
    _ROOT / "scripts" / "zillow_automation",
):
    _text = str(_entry)
    if _text not in sys.path:
        sys.path.insert(0, _text)

import zillow_agents  # noqa: E402
from zillow_parse import normalize_criteria  # noqa: E402


CHECKPOINT_KEY = "CHECKPOINT"
LISTINGS_KEY = "LISTINGS"
SUMMARY_KEY = "SUMMARY"
_SESSION_RE = re.compile(r"[^A-Za-z0-9._~]")


def on_platform():
    """True only inside an Apify run. Local apify run leaves this unset."""
    return os.environ.get("APIFY_IS_AT_HOME") == "1"


def _present(raw, *keys):
    for key in keys:
        if key in raw and raw.get(key) not in (None, ""):
            return raw.get(key)
    return None


def _string_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        raise ValueError("zip_codes must be a list of ZIP codes.")
    cleaned = []
    for item in parts:
        text = str(item or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _optional_int(value, label):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer.") from exc


def _required_cap(raw, names, default, label):
    value = _present(raw, *names)
    number = default if value is None else _optional_int(value, label)
    if number is None or number < 1:
        raise ValueError(f"{label} must be at least 1.")
    return number


def _flag(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def proxy_actor_input(actor_input):
    """Residential Apify Proxy unless the input names another group.

    On the platform every Zillow request uses this configuration. A direct
    connection from the Actor IP is blocked often enough that the first
    request does not skip the proxy.
    """
    raw = actor_input or {}
    config = raw.get("proxyConfiguration")
    if not isinstance(config, dict):
        config = {}
    groups = config.get("apifyProxyGroups")
    if not groups:
        groups = raw.get("proxyGroups") or raw.get("proxy_groups") or ["RESIDENTIAL"]
    if isinstance(groups, str):
        groups = [part.strip() for part in groups.split(",") if part.strip()]
    cleaned = []
    if isinstance(groups, list):
        for item in groups:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
    if not cleaned:
        cleaned = ["RESIDENTIAL"]
    payload = {"useApifyProxy": True, "apifyProxyGroups": cleaned}
    country = config.get("apifyProxyCountry")
    if isinstance(country, str) and country.strip():
        payload["apifyProxyCountry"] = country.strip().upper()
    else:
        # A ZIP search is US inventory. An unpinned residential exit is often
        # outside the US and Zillow answers that with an empty results shell.
        payload["apifyProxyCountry"] = "US"
    return payload


def proxy_session_id(run_id=None):
    raw = run_id or os.environ.get("APIFY_ACTOR_RUN_ID") or "zillow"
    cleaned = _SESSION_RE.sub("", str(raw))[:40] or "zillow"
    if not cleaned.lower().startswith("zillow"):
        cleaned = "zillow" + cleaned
    return cleaned[:50]


async def open_playwright_proxy(actor, actor_input, *, at_home, session_id=None):
    """Playwright proxy dict on Apify. None for a local run."""
    if not at_home:
        return None
    payload = proxy_actor_input(actor_input)
    configuration = await actor.create_proxy_configuration(actor_proxy_input=payload)
    if configuration is None:
        raise RuntimeError("Apify Proxy is required for Zillow requests on the platform.")
    url = await configuration.new_url(session_id=session_id or proxy_session_id())
    proxy = playwright_proxy(url)
    if not proxy:
        raise RuntimeError("Apify Proxy did not return a proxy URL.")
    return proxy


async def open_http_proxy_urls(actor, actor_input, *, at_home, session_id=None):
    """Two residential proxy URLs. The second is a single retry session."""
    if not at_home:
        return []
    payload = proxy_actor_input(actor_input)
    configuration = await actor.create_proxy_configuration(actor_proxy_input=payload)
    if configuration is None:
        raise RuntimeError("Apify Proxy is required for Zillow requests on the platform.")
    primary = session_id or proxy_session_id()
    spare = (primary + "b")[:50]
    urls = []
    for item in (primary, spare):
        url = await configuration.new_url(session_id=item)
        if not url:
            raise RuntimeError("Apify Proxy did not return a proxy URL.")
        urls.append(url)
    return urls


def read_run_input(actor_input):
    """ZIP codes, caps, and the optional filters. Other keys keep their defaults."""
    raw = actor_input or {}
    if not isinstance(raw, dict):
        raise ValueError("Actor input must be a JSON object.")
    zip_codes = _string_list(_present(raw, "zip_codes", "zipCodes"))
    if not zip_codes:
        raise ValueError("zip_codes is required.")
    max_listings = _required_cap(raw, ("max_listings", "maxListings"), 100, "max_listings")
    max_agents = _required_cap(raw, ("max_agents", "maxAgents"), 50, "max_agents")
    criteria = {
        "zipCodes": zip_codes,
        "resultsLimit": 0,
    }
    price_min = _optional_int(_present(raw, "price_min", "priceMin"), "price_min")
    price_max = _optional_int(_present(raw, "price_max", "priceMax"), "price_max")
    if price_min is not None:
        criteria["priceMin"] = price_min
    if price_max is not None:
        criteria["priceMax"] = price_max
    status_fields = (
        (("for_sale_by_agent", "forSaleByAgent"), "forSaleByAgent"),
        (("for_sale_by_owner", "forSaleByOwner"), "forSaleByOwner"),
        (("for_rent", "forRent"), "forRent"),
        (("sold",), "sold"),
    )
    for aliases, field in status_fields:
        if any(alias in raw for alias in aliases):
            criteria[field] = _flag(_present(raw, *aliases), False)
    enrich = _flag(_present(raw, "enrich", "enrichment"), True)
    if "headless" in raw:
        headless = _flag(raw.get("headless"), True)
    else:
        headless = True
    return {
        "criteria": normalize_criteria(criteria),
        "max_listings": max_listings,
        "max_agents": max_agents,
        "enrich": enrich,
        "headless": headless,
    }


def dataset_row(agent):
    """One dataset item. HTML from the page is not copied through."""
    agent = agent or {}
    addresses = agent.get("listing_addresses") or []
    if isinstance(addresses, str):
        addresses = [part.strip() for part in addresses.split(";") if part.strip()]
    confidence = agent.get("confidence")
    if confidence in (None, ""):
        confidence = ""
    return {
        "agent_name": str(agent.get("agent_name") or ""),
        "brokerage": str(agent.get("brokerage") or ""),
        "phone": str(agent.get("phone") or ""),
        "email": str(agent.get("email") or ""),
        "license": str(agent.get("license") or ""),
        "profile_url": str(agent.get("profile_url") or ""),
        "enrichment_source": str(agent.get("enrichment_source") or ""),
        "enrichment_source_url": str(agent.get("enrichment_source_url") or ""),
        "confidence": confidence,
        "listing_addresses": [str(item) for item in addresses if str(item).strip()],
    }


def billable_row(row):
    return bool(str((row or {}).get("agent_name") or "").strip())


def run_summary(result):
    stats = (result or {}).get("stats") or {}
    areas = (result or {}).get("areas") or {}
    blocked = []
    for area, state in areas.items():
        status = state.get("status") if isinstance(state, dict) else state
        if status == "blocked":
            blocked.append(str(area))
    return {
        "listings_found": int(stats.get("listings_found") or 0),
        "agents_found": int(stats.get("agents_found") or 0),
        "agents_enriched": int(stats.get("agents_enriched") or 0),
        "blocked_zips": blocked,
        "duplicates_skipped": int(stats.get("duplicates_skipped") or 0),
        "blocked_pages": int(stats.get("blocked_pages") or 0),
        "areas_completed": int(stats.get("areas_completed") or 0),
        "areas_blocked": int(stats.get("areas_blocked") or 0),
    }


def local_output_dir():
    return Path(_ROOT) / "scripts" / "zillow_automation"


def run_output_dir(at_home, override=None):
    if override:
        path = Path(override)
    elif at_home:
        path = Path("/tmp/zillow-actor")
    else:
        path = local_output_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def checkpoint_file(at_home, output_dir):
    if at_home:
        return Path(output_dir) / "checkpoint.json"
    return local_output_dir() / "zillow_agents_checkpoint.json"


def seed_checkpoint(path, saved):
    """Write a key-value checkpoint back to the file the pipeline resumes."""
    if not isinstance(saved, dict) or not saved.get("criteria_hash"):
        return False
    zillow_agents.save_json_atomic(path, saved)
    return True


def load_written(result):
    import json

    agents_path = Path(result["paths"]["agents_json"])
    listings_path = Path(result["paths"]["listings_json"])
    agents_doc = json.loads(agents_path.read_text(encoding="utf-8"))
    listings_doc = json.loads(listings_path.read_text(encoding="utf-8"))
    return agents_doc, listings_doc


def run_collected(
    actor_input,
    *,
    fetch=None,
    fetch_many=None,
    proxy=None,
    output_dir=None,
    checkpoint_path=None,
    seen_path=None,
    cache_path=None,
    on_checkpoint=None,
    resume=True,
    run_date=None,
    at_home=False,
    proxy_urls=None,
):
    """Run the shared pipeline. A local call with fetch= does not open a browser."""
    settings = read_run_input(actor_input)
    out_dir = run_output_dir(at_home, output_dir)
    checkpoint = Path(checkpoint_path) if checkpoint_path else checkpoint_file(at_home, out_dir)
    seen = Path(seen_path) if seen_path else (out_dir / "zillow_seen.json")
    cache = Path(cache_path) if cache_path else (out_dir / "zillow_agent_enrich_cache.json")
    browser = None
    if fetch is None and proxy_urls:
        try:
            from .http_fetch import make_proxy_fetch
        except ImportError:
            from http_fetch import make_proxy_fetch
        fetch = make_proxy_fetch(proxy_urls)
        if proxy is None and settings["enrich"]:
            proxy = playwright_proxy(proxy_urls[0])
    elif fetch is None:
        browser = zillow_agents.ZillowBrowser(
            concurrency=1,
            headless=settings["headless"],
            proxy=proxy,
        )
        fetch = browser.fetch
        fetch_many = browser.map_fetch
    try:
        result = zillow_agents.run_pipeline(
            settings["criteria"],
            fetch=fetch,
            fetch_many=fetch_many,
            concurrency=1,
            output_dir=out_dir,
            checkpoint_path=checkpoint,
            seen_path=seen,
            cache_path=cache,
            resume=resume,
            enrich=settings["enrich"],
            run_date=run_date,
            max_listings=settings["max_listings"],
            max_agents=settings["max_agents"],
            on_checkpoint=on_checkpoint,
            browser_proxy=proxy,
        )
    finally:
        if browser is not None:
            browser.close()
    agents_doc, listings_doc = load_written(result)
    rows = [dataset_row(agent) for agent in (agents_doc.get("agents") or [])]
    summary = run_summary(result)
    summary["output_dir"] = str(out_dir)
    if hasattr(fetch, "request_count"):
        summary["zillow_http_requests"] = int(fetch.request_count())
        summary["zillow_session_rotations"] = int(fetch.rotation_count())
    return {
        "rows": rows,
        "listings": listings_doc,
        "summary": summary,
        "result": result,
    }
