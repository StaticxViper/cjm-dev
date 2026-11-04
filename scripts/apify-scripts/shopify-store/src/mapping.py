"""Map Actor input onto Shopify store and product rows.

Products are deduped on store plus product id. maxItems caps product rows
and stops later stores from being requested. A block on /products.json or
/collections.json pushes one blocked row and stops the run. The homepage is
best-effort theme and app hints and does not stop the run.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    from .runtime import is_block, iso_now, looks_json
    from .sources import (
        MAX_COLLECTION_PAGES,
        MAX_COLLECTIONS,
        MAX_DOMAINS,
        MAX_PRODUCT_PAGES,
        PAGE_LIMIT,
        STATE_STORE,
        collections_url,
        homepage_url,
        normalize_domain,
        origin,
        product_url,
        products_url,
        state_store_name,
    )
    from .spend import PRICES_USD
    from .state import price_key
except ImportError:
    from runtime import is_block, iso_now, looks_json
    from sources import (
        MAX_COLLECTION_PAGES,
        MAX_COLLECTIONS,
        MAX_DOMAINS,
        MAX_PRODUCT_PAGES,
        PAGE_LIMIT,
        STATE_STORE,
        collections_url,
        homepage_url,
        normalize_domain,
        origin,
        product_url,
        products_url,
        state_store_name,
    )
    from spend import PRICES_USD
    from state import price_key


log = logging.getLogger("apify")

_TAG = re.compile(r"<[^>]+>")
_THEME = re.compile(r"Shopify\.theme\s*=\s*(\{.*?\})\s*;", re.S)
_SHOP = re.compile(r"""Shopify\.shop\s*=\s*["']([^"']+)["']""")
_CURRENCY = re.compile(r"Shopify\.currency\s*=\s*(\{.*?\})\s*;", re.S)
_OG_NAME = re.compile(
    r"""<meta[^>]+(?:property|name)=["']og:site_name["'][^>]*content=["']([^"']+)["']"""
    r"""|<meta[^>]+content=["']([^"']+)["'][^>]*(?:property|name)=["']og:site_name["']""",
    re.I,
)
_SCRIPT = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.I)
_THEME_NAME = re.compile(r"""["']name["']\s*:\s*["']([^"']+)["']""")
_PASSWORD = re.compile(r"password", re.I)
_APP_HINT_CAP = 15

TEXT_FIELDS = (
    "kind",
    "store",
    "storeUrl",
    "title",
    "productId",
    "handle",
    "vendor",
    "productType",
    "url",
    "publishedAt",
    "updatedAt",
    "currency",
    "themeName",
    "themeStatus",
    "collectionsStatus",
    "myshopifyDomain",
    "sourceStatus",
    "decision",
    "error",
    "scrapedAt",
)


def _bounded_int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _bounded_float(value, default, low, high):
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    return [text] if text else []


def _domains(raw):
    domains = []
    invalid = []
    seen = set()
    duplicates = 0
    for item in _as_list(raw.get("domains") if isinstance(raw, dict) else raw):
        host = normalize_domain(item)
        if not host:
            invalid.append(item)
            continue
        if host in seen:
            duplicates += 1
            continue
        seen.add(host)
        domains.append(host)
    return domains, invalid, duplicates


def actor_input_to_config(actor_input):
    raw = actor_input or {}
    domains, invalid, duplicates = _domains(raw)
    error = ""
    if not domains and not invalid:
        error = "Add at least one Shopify domain."
    elif len(domains) > MAX_DOMAINS:
        error = f"At most {MAX_DOMAINS} domains per run. This input has {len(domains)}."
    return {
        "domains": domains,
        "invalid": invalid,
        "duplicate_domains": duplicates,
        "max_products_per_store": _bounded_int(raw.get("maxProductsPerStore"), 50, 1, 1000),
        "track_price_changes": bool(raw.get("trackPriceChanges")),
        "state_store": state_store_name(raw.get("stateStoreName") or STATE_STORE),
        "max_items": _bounded_int(raw.get("maxItems"), 100, 1, 5000),
        "delay_seconds": _bounded_float(raw.get("delaySeconds"), 1.0, 1.0, 10.0),
        "max_spend_usd": _bounded_float(raw.get("maxSpendUsd"), 5.0, 0.01, 100.0),
        "error": error,
    }


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _clip(value, limit):
    text = _clean(_TAG.sub(" ", "" if value is None else str(value)))
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def iso_date(value):
    if value is None or value == "" or isinstance(value, bool):
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def money(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("$", "").strip()
        if not value:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return round(number, 2)


def _tags(value):
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        parts = [_clean(part) for part in value]
    else:
        parts = []
    tags = []
    for part in parts:
        text = _clip(part, 80)
        if text and text not in tags:
            tags.append(text)
        if len(tags) >= 30:
            break
    return tags


def _host(url):
    return urlparse(url or "").netloc


def outcome(result, *, expect_json=True):
    """ok, not_found, blocked, robots, unavailable, or error."""
    if not result:
        return "error"
    if result.get("error") == "robots_disallowed":
        return "robots"
    if result.get("error") == "robots_unavailable":
        return "error"
    if is_block(result):
        return "blocked"
    status = int(result.get("status") or 0)
    if status == 404:
        return "not_found"
    if result.get("error") or status >= 400 or status == 0:
        return "error"
    if expect_json and not looks_json(result):
        text = (result.get("text") or "")[:800].lower()
        if _PASSWORD.search(text):
            return "unavailable"
        if "html" in (result.get("content_type") or "").lower() or text.lstrip().startswith("<"):
            return "unavailable"
        return "error"
    return "ok"


def _failure_message(result, kind):
    if kind == "robots":
        return "robots.txt disallows this URL."
    if kind == "unavailable":
        return "The store did not return catalog JSON. It may be password protected or not a Shopify storefront."
    if kind == "not_found":
        return "HTTP 404."
    if result.get("error") == "robots_unavailable":
        return f"robots.txt could not be read: {result.get('detail') or 'fetch failed'}"
    if result.get("error"):
        return str(result["error"])
    status = int(result.get("status") or 0)
    if 200 <= status < 300:
        return "The response was not the expected JSON."
    return f"HTTP {status}" if status else "fetch_failed"


def _blocked_message(result):
    status = int((result or {}).get("status") or 0)
    what = f"HTTP {status}" if status and status != 200 else "a challenge page instead of JSON"
    return (
        f"Blocked by {_host((result or {}).get('url'))} ({what}). This Actor does not use a proxy "
        "or a CAPTCHA solver. The run stopped, so later stores were not requested. This row is not charged."
    )


def _empty_row(scraped_at):
    row = {key: "" for key in TEXT_FIELDS}
    row.update({
        "tags": [],
        "available": None,
        "priceMin": None,
        "priceMax": None,
        "variantCount": 0,
        "variants": [],
        "priceChange": None,
        "priceChanged": None,
        "theme": None,
        "appHints": [],
        "collections": [],
        "collectionCount": 0,
        "partial": False,
        "ok": False,
        "scrapedAt": scraped_at,
        "sourceStatus": "error",
        "decision": "skipped",
        "kind": "status",
    })
    return row


def _blank_row(status, error, scraped_at, store="", url="", decision="skipped"):
    row = _empty_row(scraped_at)
    row.update({
        "kind": "status",
        "store": store,
        "storeUrl": origin(store) if store else "",
        "url": url,
        "sourceStatus": status,
        "decision": decision,
        "ok": False,
        "error": _clip(error, 500),
    })
    return row


def parse_variant(raw):
    if not isinstance(raw, dict):
        return None
    vid = raw.get("id")
    if isinstance(vid, bool) or vid is None or str(vid).strip() == "":
        return None
    return {
        "variantId": str(vid).strip(),
        "title": _clip(raw.get("title"), 200),
        "sku": _clip(raw.get("sku"), 80),
        "price": money(raw.get("price")),
        "compareAtPrice": money(raw.get("compare_at_price")),
        "available": bool(raw.get("available")),
        "option1": _clip(raw.get("option1"), 120),
        "option2": _clip(raw.get("option2"), 120),
        "option3": _clip(raw.get("option3"), 120),
        "previousPrice": None,
        "priceDelta": None,
        "priceChanged": None,
    }


def parse_product(raw):
    if not isinstance(raw, dict):
        return None
    pid = raw.get("id")
    if isinstance(pid, bool) or pid is None or str(pid).strip() == "":
        return None
    variants = []
    for item in raw.get("variants") or []:
        parsed = parse_variant(item)
        if parsed:
            variants.append(parsed)
    prices = [item["price"] for item in variants if item["price"] is not None]
    return {
        "productId": str(pid).strip(),
        "title": _clip(raw.get("title"), 300),
        "handle": _clip(raw.get("handle"), 200),
        "vendor": _clip(raw.get("vendor"), 200),
        "productType": _clip(raw.get("product_type"), 200),
        "tags": _tags(raw.get("tags")),
        "publishedAt": iso_date(raw.get("published_at")),
        "updatedAt": iso_date(raw.get("updated_at")),
        "variants": variants,
        "available": any(item["available"] for item in variants) if variants else False,
        "priceMin": min(prices) if prices else None,
        "priceMax": max(prices) if prices else None,
        "variantCount": len(variants),
    }


def parse_collection(raw):
    if not isinstance(raw, dict):
        return None
    cid = raw.get("id")
    if isinstance(cid, bool) or cid is None or str(cid).strip() == "":
        return None
    count = raw.get("products_count")
    try:
        count = int(count) if count is not None and count != "" else None
    except (TypeError, ValueError):
        count = None
    return {
        "id": str(cid).strip(),
        "title": _clip(raw.get("title"), 200),
        "handle": _clip(raw.get("handle"), 200),
        "productsCount": count,
    }


def _json_object(text):
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _hint_name(url):
    parts = [part for part in urlparse(url).path.split("/") if part]
    for marker in ("extensions", "apps"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return _clip(parts[index + 1], 80)
    return ""


def parse_homepage(html):
    """Theme and app hints from public storefront HTML. Hints are not a verified install list."""
    text = str(html or "")[:500_000]
    hints = {
        "title": "",
        "shop": "",
        "currency": "",
        "theme": None,
        "themeName": "",
        "themeStatus": "not_found",
        "appHints": [],
    }
    names = _OG_NAME.search(text)
    if names:
        hints["title"] = _clip(names.group(1) or names.group(2) or "", 200)
    shop = _SHOP.search(text)
    if shop:
        hints["shop"] = _clip(shop.group(1), 200)
    currency = _CURRENCY.search(text)
    if currency:
        payload = _json_object(currency.group(1))
        if payload:
            hints["currency"] = _clip(payload.get("active") or "", 12).upper()
    theme_match = _THEME.search(text)
    theme = _json_object(theme_match.group(1)) if theme_match else None
    if theme is None and theme_match:
        name = _THEME_NAME.search(theme_match.group(1))
        theme = {"name": name.group(1)} if name else None
    if theme:
        hints["theme"] = {
            "name": _clip(theme.get("name"), 120),
            "id": _clip(theme.get("id"), 40),
            "themeStoreId": _clip(theme.get("theme_store_id"), 40),
            "schemaName": _clip(theme.get("schema_name"), 120),
            "schemaVersion": _clip(theme.get("schema_version"), 40),
            "role": _clip(theme.get("role"), 40),
        }
        hints["themeName"] = hints["theme"]["name"]
        hints["themeStatus"] = "found"
    seen = set()
    for match in _SCRIPT.finditer(text):
        url = match.group(1)
        lowered = url.lower()
        if "/apps/" not in lowered and "/extensions/" not in lowered:
            continue
        name = _hint_name(url)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        hints["appHints"].append({"name": name, "source": "script", "url": _clip(url, 300)})
        if len(hints["appHints"]) >= _APP_HINT_CAP:
            break
    return hints


def _apply_prices(product, domain, priors, track, scraped_at):
    """Return (product copy, price updates, priceChange object)."""
    changed = 0
    had_prior = False
    previous_prices = []
    previous_seen = ""
    variants = []
    updates = {}
    for source in product["variants"]:
        variant = dict(source)
        key = price_key(domain, product["productId"], variant["variantId"])
        prior = priors.get(key) if isinstance(priors, dict) else None
        if variant["price"] is not None:
            updates[key] = {"price": variant["price"], "seenAt": scraped_at}
        if track:
            if isinstance(prior, dict) and prior.get("price") is not None and variant["price"] is not None:
                had_prior = True
                old = round(float(prior["price"]), 2)
                new = variant["price"]
                delta = round(new - old, 2)
                variant["previousPrice"] = old
                variant["priceDelta"] = delta
                variant["priceChanged"] = abs(delta) >= 0.01
                previous_prices.append(old)
                if prior.get("seenAt") and prior["seenAt"] > previous_seen:
                    previous_seen = str(prior["seenAt"])
                if variant["priceChanged"]:
                    changed += 1
            else:
                variant["previousPrice"] = None
                variant["priceDelta"] = None
                variant["priceChanged"] = False
        variants.append(variant)
    if not track:
        change = None
    elif not product["variants"]:
        change = {
            "tracked": True,
            "changed": False,
            "variantsChanged": 0,
            "previousMin": None,
            "previousMax": None,
            "previousSeenAt": "",
            "reason": "no_variants",
        }
    elif not had_prior:
        change = {
            "tracked": True,
            "changed": False,
            "variantsChanged": 0,
            "previousMin": None,
            "previousMax": None,
            "previousSeenAt": "",
            "reason": "no_prior",
        }
    else:
        change = {
            "tracked": True,
            "changed": changed > 0,
            "variantsChanged": changed,
            "previousMin": min(previous_prices) if previous_prices else None,
            "previousMax": max(previous_prices) if previous_prices else None,
            "previousSeenAt": previous_seen,
            "reason": "",
        }
    copy = dict(product)
    copy["variants"] = variants
    return copy, updates, change


def _product_decision(track, change):
    if not track or not change:
        return "listed"
    if change.get("reason") == "no_prior":
        return "new"
    if change.get("changed"):
        return "changed"
    return "unchanged"


def _product_row(domain, product, priors, track, home, scraped_at):
    priced, updates, change = _apply_prices(product, domain, priors, track, scraped_at)
    row = _empty_row(scraped_at)
    row.update({
        "kind": "product",
        "store": domain,
        "storeUrl": origin(domain),
        "title": priced["title"],
        "productId": priced["productId"],
        "handle": priced["handle"],
        "vendor": priced["vendor"],
        "productType": priced["productType"],
        "tags": priced["tags"],
        "url": product_url(domain, priced["handle"]),
        "publishedAt": priced["publishedAt"],
        "updatedAt": priced["updatedAt"],
        "available": priced["available"],
        "priceMin": priced["priceMin"],
        "priceMax": priced["priceMax"],
        "currency": (home or {}).get("currency") or "",
        "variantCount": priced["variantCount"],
        "variants": priced["variants"],
        "priceChange": change,
        "priceChanged": None if change is None else bool(change.get("changed")),
        "themeName": (home or {}).get("themeName") or "",
        "themeStatus": (home or {}).get("themeStatus") or "",
        "myshopifyDomain": (home or {}).get("shop") or "",
        "sourceStatus": "found",
        "decision": _product_decision(track, change),
        "ok": True,
        "error": "",
    })
    return row, updates


def _store_row(domain, products, collections, collections_status, home, partial, scraped_at):
    row = _empty_row(scraped_at)
    title = (home or {}).get("title") or domain
    row.update({
        "kind": "store",
        "store": domain,
        "storeUrl": origin(domain),
        "title": title,
        "url": origin(domain),
        "currency": (home or {}).get("currency") or "",
        "variantCount": sum(item["variantCount"] for item in products),
        "theme": (home or {}).get("theme"),
        "themeName": (home or {}).get("themeName") or "",
        "themeStatus": (home or {}).get("themeStatus") or "not_fetched",
        "appHints": list((home or {}).get("appHints") or []),
        "collections": collections,
        "collectionCount": len(collections),
        "collectionsStatus": collections_status,
        "myshopifyDomain": (home or {}).get("shop") or "",
        "partial": bool(partial),
        "sourceStatus": "found",
        "decision": "partial" if partial else "store",
        "ok": True,
        "error": "",
    })
    return row


def _read_json_pages(domain, fetch, url_for, key, parse_item, limit, max_pages):
    """Return (items, status, result, partial). status ok includes an empty list."""
    collected = []
    seen = set()
    duplicates = 0
    page = 1
    while len(collected) < limit and page <= max_pages:
        requested = min(PAGE_LIMIT, limit - len(collected))
        url = url_for(domain, page, requested)
        result = fetch(url)
        kind = outcome(result, expect_json=True)
        if kind == "blocked":
            return collected, "blocked", result, True, duplicates
        if kind != "ok":
            if page == 1:
                return [], kind, result, False, duplicates
            return collected, "ok", result, True, duplicates
        try:
            payload = json.loads(result.get("text") or "null")
        except json.JSONDecodeError:
            if page == 1:
                return [], "error", {"error": "invalid_json", "url": url, "status": 200}, False, duplicates
            return collected, "ok", result, True, duplicates
        raw_items = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            if page == 1:
                return [], "error", {"error": "unexpected_payload", "url": url, "status": 200}, False, duplicates
            return collected, "ok", result, True, duplicates
        if not raw_items:
            break
        added = 0
        for raw in raw_items:
            if len(collected) >= limit:
                break
            parsed = parse_item(raw)
            if parsed is None:
                continue
            item_id = parsed.get("productId") or parsed.get("id")
            if item_id in seen:
                duplicates += 1
                continue
            seen.add(item_id)
            collected.append(parsed)
            added += 1
        if added == 0 or len(raw_items) < requested or len(collected) >= limit:
            break
        page += 1
    partial = page > max_pages and len(collected) >= limit
    return collected, "ok", None, partial, duplicates


def _read_homepage(domain, fetch):
    result = fetch(homepage_url(domain))
    kind = outcome(result, expect_json=False)
    empty = {
        "title": "",
        "shop": "",
        "currency": "",
        "theme": None,
        "themeName": "",
        "themeStatus": "unavailable",
        "appHints": [],
    }
    if kind == "blocked":
        empty["themeStatus"] = "blocked"
        return empty
    if kind == "robots":
        empty["themeStatus"] = "robots"
        return empty
    if kind == "not_found":
        empty["themeStatus"] = "not_found"
        return empty
    if kind != "ok":
        empty["themeStatus"] = "error"
        return empty
    return parse_homepage(result.get("text") or "")


def _not_fetched_home():
    return {
        "title": "",
        "shop": "",
        "currency": "",
        "theme": None,
        "themeName": "",
        "themeStatus": "not_fetched",
        "appHints": [],
    }


def _rows_for_products(domain, products, collections, collections_status, home, priors, track, partial, scraped_at):
    store = _store_row(domain, products, collections, collections_status, home, partial, scraped_at)
    rows = [store]
    updates = {}
    for product in products:
        row, update = _product_row(domain, product, priors, track, home, scraped_at)
        rows.append(row)
        updates.update(update)
    return rows, updates


def _read_store(domain, config, fetch, priors, scraped_at, room, dupes):
    report = {"store": domain, "status": "ok", "products": 0, "collections": 0}
    limit = min(config["max_products_per_store"], room)
    products, status, result, partial, product_dupes = _read_json_pages(
        domain, fetch, products_url, "products", parse_product, limit, MAX_PRODUCT_PAGES,
    )
    dupes["duplicates"] += product_dupes
    if status == "blocked" and not products:
        report["status"] = "blocked"
        url = (result or {}).get("url") or products_url(domain, 1, 1)
        return [_blank_row("blocked", _blocked_message(result), scraped_at, domain, url, "stopped")], {}, report, "blocked"
    if status == "blocked":
        report["status"] = "blocked"
        report["products"] = len(products)
        rows, updates = _rows_for_products(
            domain, products, [], "not_fetched", _not_fetched_home(), priors,
            config["track_price_changes"], True, scraped_at,
        )
        url = (result or {}).get("url") or products_url(domain, 1, 1)
        rows.append(_blank_row("blocked", _blocked_message(result), scraped_at, domain, url, "stopped"))
        return rows, updates, report, "blocked"
    if status != "ok":
        report["status"] = "robots_disallowed" if status == "robots" else status
        url = (result or {}).get("url") or products_url(domain, 1, 1)
        return [_blank_row(report["status"], _failure_message(result or {}, status), scraped_at, domain, url)], {}, report, ""

    collections, col_status, col_result, col_partial, collection_dupes = _read_json_pages(
        domain, fetch, collections_url, "collections", parse_collection, MAX_COLLECTIONS, MAX_COLLECTION_PAGES,
    )
    dupes["duplicates"] += collection_dupes
    if col_status == "blocked":
        report["status"] = "blocked"
        report["products"] = len(products)
        report["collections"] = len(collections)
        rows, updates = _rows_for_products(
            domain, products, collections, "blocked", _not_fetched_home(), priors,
            config["track_price_changes"], True, scraped_at,
        )
        url = (col_result or {}).get("url") or collections_url(domain, 1, 1)
        rows.append(_blank_row("blocked", _blocked_message(col_result), scraped_at, domain, url, "stopped"))
        return rows, updates, report, "blocked"
    if col_status == "ok":
        collections_status = "empty" if not collections else "found"
    elif col_status == "not_found":
        collections_status = "not_found"
        collections = []
    elif col_status == "robots":
        collections_status = "robots"
        collections = []
    else:
        collections_status = "error"
        collections = []

    home = _read_homepage(domain, fetch)
    report["products"] = len(products)
    report["collections"] = len(collections)
    report["status"] = "empty" if not products else "ok"
    rows, updates = _rows_for_products(
        domain, products, collections, collections_status, home, priors,
        config["track_price_changes"], bool(partial or col_partial), scraped_at,
    )
    return rows, updates, report, ""


def scrape(config, fetch, prices=None, now=None):
    """Return (rows, summary, new_prices). new_prices is only for parsed products."""
    scraped_at = now or iso_now()
    priors = prices if isinstance(prices, dict) else {}
    status_rows = []
    for item in config.get("invalid") or []:
        status_rows.append(_blank_row("error", f"Not a public store domain: {item!r}", scraped_at))
    if config.get("error"):
        row = _blank_row("error", config["error"], scraped_at)
        return [row], _summarize([row], config, {}, [], "", False, scraped_at), {}

    rows = []
    new_prices = {}
    counts = {"duplicates": 0, "duplicateDomains": config.get("duplicate_domains") or 0}
    reports = []
    truncated = False
    stopped = ""
    kept = 0
    seen_products = set()

    for domain in config["domains"]:
        if kept >= config["max_items"]:
            truncated = True
            break
        room = config["max_items"] - kept
        store_rows, updates, report, fatal = _read_store(
            domain, config, fetch, priors, scraped_at, room, counts,
        )
        product_rows = [row for row in store_rows if row.get("kind") == "product"]
        unique_rows = []
        for row in store_rows:
            if row.get("kind") != "product":
                unique_rows.append(row)
                continue
            key = (row.get("store"), row.get("productId"))
            if key in seen_products:
                counts["duplicates"] += 1
                continue
            seen_products.add(key)
            unique_rows.append(row)
        dropped = len(product_rows) - sum(1 for row in unique_rows if row.get("kind") == "product")
        if dropped:
            for row in unique_rows:
                if row.get("kind") == "store":
                    row["variantCount"] = sum(
                        item.get("variantCount") or 0 for item in unique_rows if item.get("kind") == "product"
                    )
        rows.extend(unique_rows)
        for key, record in updates.items():
            domain_key, product_id, _variant = key.split("|", 2)
            if (domain_key, product_id) in seen_products:
                new_prices[key] = record
        kept += sum(1 for row in unique_rows if row.get("kind") == "product")
        report["products"] = sum(1 for row in unique_rows if row.get("kind") == "product")
        reports.append(report)
        _log_store(report)
        if fatal == "blocked":
            stopped = "blocked"
            break
        if kept >= config["max_items"]:
            truncated = True

    rows.extend(status_rows)
    summary = _summarize(rows, config, counts, reports, stopped, truncated, scraped_at)
    log.critical(
        "Shopify store SUMMARY: status=%s products=%s stores=%s",
        summary["status"],
        summary["products"],
        summary["stores"],
    )
    return rows, summary, new_prices


def _log_store(report):
    log.critical(
        "Shopify store %s: status=%s products=%s collections=%s",
        report.get("store"),
        report.get("status"),
        report.get("products"),
        report.get("collections"),
    )


def billable_event(row):
    row = row or {}
    if row.get("sourceStatus") != "found" or row.get("ok") is not True:
        return ""
    if row.get("kind") == "store" and row.get("store"):
        return "store"
    if row.get("kind") == "product" and row.get("productId"):
        return "product"
    return ""


def _summarize(rows, config, counts, reports, stopped, truncated, scraped_at):
    tally = {}
    for row in rows or []:
        key = row.get("sourceStatus") or "error"
        tally[key] = tally.get(key, 0) + 1
    products = sum(1 for row in rows or [] if row.get("kind") == "product" and row.get("sourceStatus") == "found")
    stores = sum(1 for row in rows or [] if row.get("kind") == "store" and row.get("sourceStatus") == "found")
    found = products + stores
    if found and tally.get("blocked"):
        status = "partial"
    elif found:
        status = "ok"
    elif tally.get("blocked"):
        status = "blocked"
    elif tally.get("error"):
        status = "error"
    elif tally.get("robots_disallowed"):
        status = "robots_disallowed"
    elif tally.get("unavailable"):
        status = "unavailable"
    else:
        status = "not_found"
    return {
        "status": status,
        "pushed": len(rows or []),
        "found": found,
        "products": products,
        "stores": stores,
        "priceChanges": sum(1 for row in rows or [] if row.get("priceChanged") is True),
        "blocked": tally.get("blocked", 0),
        "errors": tally.get("error", 0),
        "robots": tally.get("robots_disallowed", 0),
        "unavailable": tally.get("unavailable", 0),
        "notFound": tally.get("not_found", 0),
        "mergedDuplicates": counts.get("duplicates", 0),
        "duplicateDomains": counts.get("duplicateDomains", 0),
        "truncated": bool(truncated),
        "maxItems": config.get("max_items"),
        "maxProductsPerStore": config.get("max_products_per_store"),
        "trackPriceChanges": bool(config.get("track_price_changes")),
        "stateStore": config.get("state_store") or STATE_STORE,
        "maxSpendUsd": config.get("max_spend_usd"),
        "pricesUsd": dict(PRICES_USD),
        "storesReport": reports,
        "stopped": stopped,
        "scrapedAt": scraped_at,
    }
