"""Records shared by the scrapers and the sync runner."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProductRecord:
    name: str | None = None
    price: float | None = None
    regular_price: float | None = None
    size_value: float | None = None
    size_unit: str | None = None
    product_url: str | None = None
    upc: str | None = None
    asin: str | None = None
    error: str | None = None
    note: str | None = None
