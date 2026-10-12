"""Decide whether a scraped price is saved, flagged, or failed."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from grocery.models import ProductRecord
from grocery.parser import PriceError, parse_price

_TOKEN = re.compile(r"[a-z0-9]+")


def as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def is_outlier(previous: float | None, new_price: float) -> bool:
    """True when the new price is outside 0.33x to 3x the last pack price."""
    if previous is None or previous <= 0:
        return False
    previous_d = Decimal(str(previous))
    new_d = Decimal(str(new_price))
    return new_d > (Decimal("3") * previous_d) or new_d < (Decimal("0.33") * previous_d)


def unit_price(price: float, size_value: float | None) -> float | None:
    if size_value is None or size_value <= 0:
        return None
    return round(price / float(size_value), 4)


def search_query(brand: str | None, name: str | None) -> str:
    brand_text = (brand or "").strip()
    name_text = (name or "").strip()
    if brand_text and name_text:
        return f"{brand_text} {name_text}"
    return name_text or brand_text


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text.lower()) if len(token) > 1}


def first_confident_hit(query: str, hits: list[ProductRecord], *, threshold: float = 0.5) -> ProductRecord | None:
    """First search hit whose name covers at least half of the query tokens."""
    wanted = _tokens(query)
    if not wanted:
        return None
    for hit in hits:
        if hit.error or not hit.product_url or hit.price is None:
            continue
        overlap = wanted & _tokens(hit.name or "")
        if len(overlap) / len(wanted) >= threshold:
            return hit
    return None


def _money(value: float) -> str:
    return f"{value:.2f}"


def decide_price(link: dict, product: ProductRecord) -> dict:
    if product.error or product.price is None:
        outcome = {"status": "failed", "message": product.error or "no_price"}
        if product.product_url:
            outcome["product_url"] = product.product_url
        return outcome
    try:
        price = parse_price(product.price)
    except PriceError as exc:
        outcome = {"status": "failed", "message": str(exc)}
        if product.product_url:
            outcome["product_url"] = product.product_url
        return outcome
    if price is None:
        return {"status": "failed", "message": "no_price", "product_url": product.product_url}
    previous = as_float(link.get("pack_price"))
    if is_outlier(previous, price):
        shown_previous = previous if previous is not None else 0.0
        return {
            "status": "flagged",
            "message": f"Price swing flagged: ${_money(shown_previous)} -> ${_money(price)}",
            "price": price,
            "product_url": product.product_url,
        }
    regular = price
    if product.regular_price is not None:
        try:
            parsed = parse_price(product.regular_price)
        except PriceError:
            parsed = None
        if parsed is not None:
            regular = parsed
    outcome = {
        "status": "ok",
        "price": price,
        "regular_price": regular,
        "unit_price": unit_price(price, product.size_value),
        "product_url": product.product_url,
        "message": "",
    }
    if product.size_value is not None and product.size_unit:
        outcome["size_value"] = float(product.size_value)
        outcome["size_unit"] = product.size_unit
    return outcome


def lookup_link(link: dict, scraper_for) -> dict:
    """Scrape a store link. Search by brand and name when product_url is empty."""
    provider = (link.get("provider") or "").lower()
    try:
        scraper = scraper_for(provider)
    except Exception as exc:  # noqa: BLE001 — record the store and keep the queue moving
        return {"status": "failed", "message": str(exc)}
    url = (link.get("product_url") or "").strip()
    discovered = None
    if not url:
        query = search_query(link.get("brand"), link.get("item_name"))
        if not query:
            return {"status": "failed", "message": "missing item name"}
        try:
            hits = scraper.search(query)
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "message": str(exc)}
        if len(hits) == 1 and hits[0].error and not hits[0].name and not hits[0].product_url:
            return {"status": "failed", "message": hits[0].error}
        hit = first_confident_hit(query, hits)
        if hit is None or not hit.product_url:
            return {"status": "failed", "message": "no matching product"}
        url = hit.product_url
        discovered = url
    try:
        product = scraper.scrape_url(url)
    except Exception as exc:  # noqa: BLE001
        outcome = {"status": "failed", "message": str(exc)}
        if discovered:
            outcome["product_url"] = discovered
        return outcome
    if discovered and not product.product_url:
        product.product_url = discovered
    outcome = decide_price(link, product)
    if discovered and not outcome.get("product_url"):
        outcome["product_url"] = discovered
    return outcome


def price_phrase(outcome: dict) -> str:
    total = outcome.get("price")
    per_unit = outcome.get("unit_price")
    unit = outcome.get("size_unit")
    if per_unit is not None and unit and total is not None:
        return f"${_money(float(per_unit))}/{unit} (${_money(float(total))} total)"
    if total is not None:
        return f"${_money(float(total))}"
    return "a price"


def format_status_line(when: datetime, link: dict, outcome: dict, *, pending_count: int | None = None) -> str:
    stamp = when.strftime("%H:%M:%S")
    name = link.get("item_name") or "item"
    store = link.get("store_name") or link.get("provider") or "store"
    status = outcome.get("status")
    if status == "ok":
        tail = f"Found {price_phrase(outcome)}. Updated successfully."
    elif status == "flagged":
        tail = str(outcome.get("message") or "Price swing flagged.")
    else:
        tail = "Failed: " + str(outcome.get("message") or "scrape failed")
    prefix = ""
    if pending_count == 1:
        prefix = "Found 1 pending lookup: "
    return f"[{stamp}] {prefix}'{name}' @ {store} -> {tail}"


def format_pending_header(when: datetime, count: int) -> str:
    noun = "lookup" if count == 1 else "lookups"
    return f"[{when.strftime('%H:%M:%S')}] Found {count} pending {noun}."
