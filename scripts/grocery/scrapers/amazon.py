"""Amazon product and search pages. One-time purchase price only."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from grocery.models import ProductRecord
from grocery.parser import PriceError, parse_price
from grocery.scrapers.base import BaseScraper, classify_block, encoded_query
from grocery.scrapers.extract import (
    element_text,
    find_product,
    first_valid_price,
    load_jsonld,
    offer_raw_prices,
    product_code,
    product_size_texts,
    size_from_texts,
    text_of,
    visible_text,
)

_ASIN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})", re.IGNORECASE)
_ONE_TIME = re.compile(r"one[\s-]*time purchase", re.IGNORECASE)
_UNIT_PRICE = re.compile(
    r"\$\s*\d+(?:\.\d+)?\s*/\s*(?:fl\.?\s*oz|oz|lb|lbs|gal|ct|count|each|ml|l)\b",
    re.IGNORECASE,
)


def amazon_asin(url: str, soup: BeautifulSoup) -> str | None:
    match = _ASIN.search(url or "")
    if match:
        return match.group(1).upper()
    node = soup.select_one("#ASIN")
    if node is not None and node.get("value"):
        return str(node["value"]).strip().upper()
    return None


def _in_subscribe(node) -> bool:
    parent = getattr(node, "parent", None)
    for _ in range(5):
        if parent is None:
            return False
        if getattr(parent, "name", None) in {"body", "html"}:
            return False
        if parent.get("data-component-type") == "s-search-result":
            return False
        classes = " ".join(parent.get("class") or []).lower()
        ident = (parent.get("id") or "").lower()
        if "subscribe" in f"{classes} {ident}":
            return True
        text = parent.get_text(" ", strip=True).lower()
        if "subscribe" in text and "save" in text and len(text) < 120:
            return True
        parent = parent.parent
    return False


def _inside(node, selector: str) -> bool:
    parent = node
    for _ in range(6):
        if parent is None:
            return False
        if hasattr(parent, "select_one") and parent.select_one(selector) is parent:
            return True
        classes = " ".join(parent.get("class") or [])
        if selector == ".a-text-price" and "a-text-price" in classes.split():
            return True
        parent = parent.parent
    return False


def _one_time_price(soup: BeautifulSoup) -> str | None:
    for text_node in soup.find_all(string=_ONE_TIME):
        parent = text_node.parent
        for _ in range(6):
            if parent is None:
                break
            price_node = parent.select_one(".a-offscreen, #priceblock_ourprice, .priceToPay")
            snippet = parent.get_text(" ", strip=True)
            if price_node is not None and len(snippet) < 300:
                return element_text(price_node)
            parent = parent.parent
    return None


def _loose_prices(soup: BeautifulSoup) -> list[str]:
    found: list[str] = []
    for node in soup.select(".a-price .a-offscreen, #priceblock_ourprice, .priceToPay .a-offscreen"):
        if _in_subscribe(node) or _inside(node, ".a-text-price"):
            continue
        text = element_text(node)
        if text:
            found.append(text)
    return found


def _card_price(card) -> float | None:
    for node in card.select(".a-offscreen"):
        if _in_subscribe(node) or _inside(node, ".a-text-price"):
            continue
        try:
            price = parse_price(element_text(node))
        except PriceError:
            continue
        if price is not None:
            return price
    return None


class AmazonScraper(BaseScraper):
    provider = "amazon"

    def search_url_for(self, query: str) -> str:
        return f"https://www.amazon.com/s?k={encoded_query(query)}"

    def parse_html(self, html: str, url: str) -> ProductRecord:
        if classify_block(html, url):
            return ProductRecord(product_url=url, error="blocked")
        soup = BeautifulSoup(html or "", "html.parser")
        product = find_product(load_jsonld(html))
        current, regular = offer_raw_prices(product)
        record = ProductRecord(product_url=url, asin=amazon_asin(url, soup))
        if product and isinstance(product.get("name"), str):
            record.name = product["name"].strip()
        record.upc = product_code(product)
        if not record.name:
            record.name = text_of(soup, "#productTitle") or text_of(soup, "h1")
        price, price_error = first_valid_price(
            _one_time_price(soup),
            text_of(soup, "#priceblock_ourprice"),
            text_of(soup, "#priceblock_dealprice"),
            text_of(soup, ".priceToPay .a-offscreen"),
            text_of(soup, ".priceToPay"),
            current,
            *_loose_prices(soup),
        )
        record.price = price
        regular_price, _regular_error = first_valid_price(
            regular,
            text_of(soup, ".a-text-price .a-offscreen"),
            text_of(soup, "#listPrice"),
        )
        record.regular_price = regular_price
        sized = size_from_texts(*product_size_texts(product), record.name)
        if sized:
            record.size_value, record.size_unit = sized
        unit = _UNIT_PRICE.search(visible_text(html))
        if unit:
            record.note = "unit_price: " + re.sub(r"\s+", " ", unit.group(0)).strip()
        if record.price is None:
            record.error = price_error or "no_price"
        return record

    def parse_search(self, html: str, url: str) -> list[ProductRecord]:
        if classify_block(html, url):
            return [ProductRecord(product_url=url, error="blocked")]
        soup = BeautifulSoup(html or "", "html.parser")
        hits: list[ProductRecord] = []
        seen: set[str] = set()
        cards = soup.select("[data-component-type='s-search-result']")
        for card in cards[:20]:
            link = card.select_one("h2 a[href]")
            if link is None:
                continue
            product_url = urljoin(url, link.get("href"))
            if product_url in seen:
                continue
            seen.add(product_url)
            name = element_text(link)
            sized = size_from_texts(name)
            record = ProductRecord(
                name=name or None,
                price=_card_price(card),
                product_url=product_url,
                asin=amazon_asin(product_url, card),
            )
            if sized:
                record.size_value, record.size_unit = sized
            hits.append(record)
        return hits
