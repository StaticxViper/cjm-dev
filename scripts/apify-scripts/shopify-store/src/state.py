"""Variant prices saved between runs.

Stored as one JSON record in a named key-value store:
``{"version": 1, "updatedAt": ISO, "prices": {key: {"price": number, "seenAt": ISO}}}``.
Keys are ``domain|productId|variantId``. The latest pushed price replaces the
older one. A product held back by maxItems or maxSpendUsd is not recorded, so
the next run still compares against the last price that was actually pushed.
"""

from __future__ import annotations

STATE_KEY = "PRICES"
STATE_VERSION = 1
MAX_KEYS = 200_000


def price_key(domain, product_id, variant_id):
    return f"{domain}|{product_id}|{variant_id}"


def load_state(raw):
    if not isinstance(raw, dict):
        return {}
    prices = raw.get("prices")
    if not isinstance(prices, dict):
        return {}
    loaded = {}
    for key, value in prices.items():
        if not key or not isinstance(value, dict):
            continue
        price = value.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            continue
        loaded[str(key)] = {
            "price": round(float(price), 2),
            "seenAt": str(value.get("seenAt") or ""),
        }
    return loaded


def merge_state(seen, new, max_keys=MAX_KEYS):
    merged = dict(seen or {})
    for key, record in (new or {}).items():
        if not key or not isinstance(record, dict):
            continue
        merged[key] = {"price": record.get("price"), "seenAt": str(record.get("seenAt") or "")}
    if len(merged) > max_keys:
        keep = sorted(merged.items(), key=lambda item: item[1].get("seenAt") or "", reverse=True)[:max_keys]
        merged = dict(keep)
    return merged


def dump_state(seen, updated_at):
    return {"version": STATE_VERSION, "updatedAt": updated_at, "prices": dict(seen or {})}
