"""Normalize currency strings and package quantities."""

from __future__ import annotations

import math
import re
from decimal import Decimal, ROUND_HALF_UP

MAX_PRICE = Decimal("10000")
_COUNT_UNITS = {"ct", "count", "each"}

UNIT_ALIASES = {
    "oz": "oz",
    "ounce": "oz",
    "ounces": "oz",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "fl oz": "fl oz",
    "floz": "fl oz",
    "fluid ounce": "fl oz",
    "fluid ounces": "fl oz",
    "ml": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "l": "l",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "gal": "gal",
    "gallon": "gal",
    "gallons": "gal",
    "qt": "qt",
    "quart": "qt",
    "quarts": "qt",
    "pt": "pt",
    "pint": "pt",
    "pints": "pt",
    "ct": "ct",
    "count": "count",
    "each": "each",
    "ea": "each",
}

_UNIT_PATTERN = (
    r"fl\.?\s*oz|fluid\s+ounces?|ounces?|oz|"
    r"pounds?|lbs?|lb|"
    r"kilograms?|kg|"
    r"gallons?|gal|"
    r"quarts?|qt|"
    r"pints?|pt|"
    r"milliliters?|ml|"
    r"liters?|litres?|"
    r"grams?|"
    r"count|ct|each|ea|"
    r"g|l"
)
_MEASURE = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})\b", re.IGNORECASE)
_PACK = re.compile(
    r"pack\s+of\s+(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*[- ]?pack\b|(\d+(?:\.\d+)?)\s*[x×]\s+",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class PriceError(ValueError):
    """A currency value is present but outside the backend price rules."""


def _canon_unit(raw: str) -> str | None:
    key = re.sub(r"\s+", " ", raw.lower().replace(".", "")).strip()
    return UNIT_ALIASES.get(key)


def parse_price(value: object) -> float | None:
    """Return a positive finite price <= 10000. Empty input returns None."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise PriceError("price must be a number")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise PriceError("price must be a finite number")
        number = Decimal(str(value))
    else:
        text = str(value).strip()
        if not text:
            return None
        match = _NUMBER.search(text.replace(",", "").replace("$", ""))
        if not match:
            raise PriceError(f"price not found in {value!r}")
        number = Decimal(match.group(0))
    if not number.is_finite() or number <= 0 or number > MAX_PRICE:
        raise PriceError("price must be a positive finite number <= 10000")
    quantized = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quantized)


def _pack_count(text: str) -> float | None:
    match = _PACK.search(text)
    if not match:
        return None
    raw = next(group for group in match.groups() if group)
    return float(raw)


def _measures(text: str) -> list[tuple[float, str]]:
    found: list[tuple[float, str]] = []
    for match in _MEASURE.finditer(text):
        unit = _canon_unit(match.group(2))
        if unit is None:
            continue
        found.append((float(match.group(1)), unit))
    return found


def parse_size(text: str | None) -> dict[str, float | str] | None:
    """Turn a quantity string into size_value and size_unit.

    Multipacks multiply: "Pack of 2, 32 oz each" becomes 64 oz.
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    pack = _pack_count(raw)
    measures = _measures(raw)
    physical = [item for item in measures if item[1] not in _COUNT_UNITS]
    counts = [item for item in measures if item[1] in _COUNT_UNITS]
    if pack and physical:
        value, unit = physical[-1]
        return {"size_value": pack * value, "size_unit": unit}
    if physical:
        value, unit = physical[-1]
        return {"size_value": value, "size_unit": unit}
    if counts:
        value, unit = counts[-1]
        return {"size_value": value, "size_unit": unit}
    if pack is not None:
        return {"size_value": pack, "size_unit": "ct"}
    return None
