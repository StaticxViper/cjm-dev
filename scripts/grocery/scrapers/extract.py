"""JSON-LD and HTML helpers shared by the store parsers."""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from grocery.parser import PriceError, parse_price, parse_size


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def load_jsonld(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes.extend(_flatten_jsonld(payload))
    return nodes


def _flatten_jsonld(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        found: list[dict[str, Any]] = []
        for item in payload:
            found.extend(_flatten_jsonld(item))
        return found
    if isinstance(payload, dict):
        if isinstance(payload.get("@graph"), list):
            return _flatten_jsonld(payload["@graph"])
        return [payload]
    return []


def _type_names(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if raw:
        return {str(raw)}
    return set()


def find_product(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for node in nodes:
        if "Product" in _type_names(node):
            return node
    return None


def product_code(product: dict[str, Any] | None) -> str | None:
    if not product:
        return None
    for key in ("gtin12", "gtin13", "gtin14", "gtin8", "gtin"):
        value = product.get(key)
        if value:
            return str(value).strip()
    sku = str(product.get("sku") or "").strip()
    if re.fullmatch(r"\d{8,14}", sku):
        return sku
    return None


def offer_raw_prices(product: dict[str, Any] | None) -> tuple[object | None, object | None]:
    """Return the offer's current price and a list/regular price when present."""
    if not product:
        return None, None
    offers = product.get("offers")
    if isinstance(offers, list):
        offer = offers[0] if offers else {}
    elif isinstance(offers, dict):
        offer = offers
    else:
        offer = {}
    current = offer.get("price")
    if current is None:
        current = offer.get("lowPrice")
    regular = None
    spec = offer.get("priceSpecification")
    specs = spec if isinstance(spec, list) else ([spec] if isinstance(spec, dict) else [])
    for item in specs:
        if not isinstance(item, dict):
            continue
        label = str(item.get("priceType") or item.get("name") or "").lower()
        if any(token in label for token in ("list", "regular", "strikethrough", "was")):
            regular = item.get("price")
        elif current is None:
            current = item.get("price")
    return current, regular


def product_size_texts(product: dict[str, Any] | None) -> list[str]:
    if not product:
        return []
    texts: list[str] = []
    for key in ("size", "weight", "name"):
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    return texts


def text_of(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def first_valid_price(*raws: object) -> tuple[float | None, str | None]:
    """Return (price, error). error is set only when a candidate was invalid."""
    saw_invalid = False
    for raw in raws:
        if raw is None:
            continue
        if isinstance(raw, str) and not raw.strip():
            continue
        try:
            price = parse_price(raw)
        except PriceError:
            saw_invalid = True
            continue
        if price is not None:
            return price, None
    if saw_invalid:
        return None, "invalid_price"
    return None, None


def size_from_texts(*texts: str | None) -> tuple[float, str] | None:
    for text in texts:
        if not text:
            continue
        parsed = parse_size(text)
        if parsed:
            return float(parsed["size_value"]), str(parsed["size_unit"])
    return None


def element_text(node) -> str:
    if node is None:
        return ""
    return node.get_text(" ", strip=True)
