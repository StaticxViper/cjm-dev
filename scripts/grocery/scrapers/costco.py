"""Costco.com public product pages and search. Member-locked items are skipped."""

from __future__ import annotations

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
    stock_error,
    text_of,
    visible_text,
)

_MEMBER_PHRASES = (
    "sign in to see price",
    "member only",
    "members only",
    "available to members",
)


def _member_only(html: str) -> bool:
    text = visible_text(html).lower()
    return any(phrase in text for phrase in _MEMBER_PHRASES)


def _delivery_note(html: str) -> str | None:
    text = visible_text(html).lower()
    if "delivery surcharge" in text or "includes delivery" in text:
        return "delivery surcharge mentioned"
    return None


class CostcoScraper(BaseScraper):
    provider = "costco"

    def search_url_for(self, query: str) -> str:
        return f"https://www.costco.com/CatalogSearch?keyword={encoded_query(query)}"

    def parse_html(self, html: str, url: str) -> ProductRecord:
        if classify_block(html, url):
            return ProductRecord(product_url=url, error="blocked")
        soup = BeautifulSoup(html or "", "html.parser")
        product = find_product(load_jsonld(html))
        current, regular = offer_raw_prices(product)
        record = ProductRecord(product_url=url, upc=product_code(product))
        if product and isinstance(product.get("name"), str):
            record.name = product["name"].strip()
        if not record.name:
            record.name = text_of(soup, "h1")
        price, price_error = first_valid_price(
            current,
            text_of(soup, ".your-price"),
            text_of(soup, "#pull-right-price"),
            text_of(soup, ".price"),
        )
        record.price = price
        regular_price, _ignored = first_valid_price(
            regular,
            text_of(soup, ".was-price"),
            text_of(soup, ".online-price"),
        )
        record.regular_price = regular_price
        sized = size_from_texts(*product_size_texts(product), record.name, text_of(soup, ".product-info-specs"))
        if sized:
            record.size_value, record.size_unit = sized
        record.note = _delivery_note(html)
        if record.price is None and _member_only(html):
            record.error = "member_only"
            return record
        if record.price is None:
            record.error = stock_error(html) or price_error or "no_price"
        return record

    def parse_search(self, html: str, url: str) -> list[ProductRecord]:
        if classify_block(html, url):
            return [ProductRecord(product_url=url, error="blocked")]
        soup = BeautifulSoup(html or "", "html.parser")
        hits: list[ProductRecord] = []
        seen: set[str] = set()
        for card in soup.select(".product")[:20]:
            link = card.select_one("a[href]")
            if link is None:
                continue
            product_url = urljoin(url, link.get("href"))
            if product_url in seen:
                continue
            seen.add(product_url)
            name = element_text(link)
            price = None
            price_node = card.select_one(".price, .your-price")
            if price_node is not None:
                try:
                    price = parse_price(element_text(price_node))
                except PriceError:
                    price = None
            record = ProductRecord(name=name or None, price=price, product_url=product_url)
            sized = size_from_texts(name)
            if sized:
                record.size_value, record.size_unit = sized
            hits.append(record)
        return hits
