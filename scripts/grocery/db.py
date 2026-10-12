"""Direct PostgREST reads and writes for grocery prices."""

from __future__ import annotations

from datetime import datetime, timezone

SELECT = (
    "id, item_id, store_id, product_url, pack_price, "
    "shopping_items(name, brand, upc), shopping_stores(name, provider)"
)


def _data(response: object) -> list:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if not data:
        return []
    if isinstance(data, list):
        return data
    return [data]


def normalize_store_link(row: dict) -> dict:
    store = row.get("shopping_stores") or {}
    item = row.get("shopping_items") or {}
    if isinstance(store, list):
        store = store[0] if store else {}
    if isinstance(item, list):
        item = item[0] if item else {}
    return {
        "item_store_id": row.get("id"),
        "item_id": row.get("item_id"),
        "store_id": row.get("store_id"),
        "product_url": row.get("product_url"),
        "pack_price": row.get("pack_price"),
        "provider": str(store.get("provider") or "").lower(),
        "store_name": store.get("name"),
        "item_name": item.get("name"),
        "brand": item.get("brand"),
        "upc": item.get("upc"),
    }


class GroceryDB:
    def __init__(self, client):
        self.client = client

    def _select(self):
        return self.client.table("shopping_item_stores").select(SELECT)

    def fetch_pending(self) -> list[dict]:
        response = self._select().eq("check_status", "pending").execute()
        return [normalize_store_link(row) for row in _data(response)]

    def fetch_item(self, item_id: str) -> list[dict]:
        response = self._select().eq("item_id", item_id).execute()
        return [normalize_store_link(row) for row in _data(response)]

    def fetch_all(self) -> list[dict]:
        response = self._select().execute()
        return [normalize_store_link(row) for row in _data(response)]

    def update_store(self, row_id: str, payload: dict) -> None:
        self.client.table("shopping_item_stores").update(payload).eq("id", row_id).execute()

    def insert_history(self, payload: dict) -> None:
        self.client.table("shopping_price_history").insert(payload).execute()

    def apply_outcome(self, link: dict, outcome: dict, *, now: datetime) -> None:
        stamp = now.astimezone(timezone.utc).isoformat()
        row_id = link["item_store_id"]
        status = outcome.get("status")
        discovered = outcome.get("product_url") if not (link.get("product_url") or "").strip() else None
        if status == "failed":
            payload = {
                "check_status": "failed",
                "check_error": outcome.get("message") or "scrape failed",
                "last_checked_at": stamp,
            }
            if discovered:
                payload["product_url"] = discovered
            self.update_store(row_id, payload)
            return
        if status == "flagged":
            payload = {
                "check_status": "flagged",
                "check_error": outcome.get("message") or "Price swing flagged",
                "last_checked_at": stamp,
            }
            if discovered:
                payload["product_url"] = discovered
            self.update_store(row_id, payload)
            return
        payload = {
            "pack_price": outcome["price"],
            "regular_price": outcome.get("regular_price", outcome["price"]),
            "check_status": "ok",
            "check_error": None,
            "price_source": "script",
            "last_checked_at": stamp,
        }
        if outcome.get("size_value") is not None and outcome.get("size_unit"):
            payload["size_value"] = outcome["size_value"]
            payload["size_unit"] = outcome["size_unit"]
        if outcome.get("product_url"):
            payload["product_url"] = outcome["product_url"]
        self.update_store(row_id, payload)
        history = {
            "item_id": link.get("item_id"),
            "store_id": link.get("store_id"),
            "item_store_id": row_id,
            "price": outcome["price"],
            "regular_price": outcome.get("regular_price", outcome["price"]),
            "source": "script",
            "recorded_at": stamp,
        }
        if outcome.get("unit_price") is not None:
            history["unit_price"] = outcome["unit_price"]
        self.insert_history(history)
