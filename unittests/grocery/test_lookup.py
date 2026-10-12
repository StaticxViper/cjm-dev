"""Direct database lookup queue. Supabase and Playwright are mocked."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from grocery.db import GroceryDB  # noqa: E402
from grocery.lookup import (  # noqa: E402
    decide_price,
    first_confident_hit,
    format_status_line,
    is_outlier,
    lookup_link,
    search_query,
    unit_price,
)
from grocery.models import ProductRecord  # noqa: E402
from grocery.scrapers.amazon import AmazonScraper  # noqa: E402
from grocery.scraper import listen_loop, main, process_rows  # noqa: E402

WHEN = datetime(2026, 10, 12, 11, 5, 22, tzinfo=timezone.utc)


class FakeQuery:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self.filters = []
        self.payload = None
        self.op = None

    def select(self, _cols):
        self.op = "select"
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = dict(payload)
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = dict(payload)
        return self

    def execute(self):
        if self.op == "update":
            self.store.updates.append({"table": self.name, "payload": self.payload, "filters": list(self.filters)})
            return SimpleNamespace(data=[])
        if self.op == "insert":
            self.store.inserts.append({"table": self.name, "payload": self.payload})
            return SimpleNamespace(data=[self.payload])
        rows = list(self.store.tables.get(self.name, []))
        for key, value in self.filters:
            rows = [row for row in rows if row.get(key) == value]
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.updates = []
        self.inserts = []

    def table(self, name):
        return FakeQuery(self, name)


def _row(**overrides):
    base = {
        "id": "link-1",
        "item_id": "item-1",
        "store_id": "store-1",
        "product_url": "https://shop.shoprite.com/product/chicken",
        "pack_price": 4.99,
        "check_status": "pending",
        "shopping_items": {"name": "Chicken Breast", "brand": "Perdue", "upc": None},
        "shopping_stores": {"name": "ShopRite", "provider": "shoprite"},
    }
    base.update(overrides)
    return base


class TestOutlier(unittest.TestCase):
    def test_bounds(self):
        self.assertFalse(is_outlier(None, 10))
        self.assertFalse(is_outlier(0, 10))
        self.assertFalse(is_outlier(10, 30))
        self.assertFalse(is_outlier(10, 3.3))
        self.assertTrue(is_outlier(10, 30.01))
        self.assertTrue(is_outlier(10, 3.29))

    def test_unit_price(self):
        self.assertAlmostEqual(unit_price(12.48, 2.5), 4.992)
        self.assertIsNone(unit_price(12.48, None))

    def test_search_query(self):
        self.assertEqual(search_query("Perdue", "Chicken Breast"), "Perdue Chicken Breast")
        self.assertEqual(search_query("", "Milk"), "Milk")


class TestMatch(unittest.TestCase):
    def test_first_confident_hit(self):
        hits = [
            ProductRecord(name="Apple Juice", price=3, product_url="https://example.com/apple"),
            ProductRecord(name="Perdue Chicken Breast", price=12.48, product_url="https://example.com/chicken"),
        ]
        chosen = first_confident_hit("Perdue Chicken Breast", hits)
        self.assertEqual(chosen.product_url, "https://example.com/chicken")
        self.assertIsNone(first_confident_hit("Perdue Chicken Breast", hits[:1]))


class TestDecide(unittest.TestCase):
    def test_flagged_does_not_use_new_price_as_saved_status(self):
        product = ProductRecord(price=20, product_url="https://example.com/chicken", size_value=1, size_unit="lb")
        outcome = decide_price({"pack_price": "4.99"}, product)
        self.assertEqual(outcome["status"], "flagged")
        self.assertEqual(outcome["message"], "Price swing flagged: $4.99 -> $20.00")

    def test_status_line(self):
        link = {"item_name": "Chicken Breast", "store_name": "ShopRite"}
        outcome = {
            "status": "ok",
            "price": 12.48,
            "unit_price": 4.99,
            "size_unit": "lb",
        }
        line = format_status_line(WHEN, link, outcome, pending_count=1)
        self.assertEqual(
            line,
            "[11:05:22] Found 1 pending lookup: 'Chicken Breast' @ ShopRite -> "
            "Found $4.99/lb ($12.48 total). Updated successfully.",
        )


class TestLookup(unittest.TestCase):
    def test_search_when_url_missing(self):
        class FakeScraper:
            def __init__(self):
                self.searched = []
                self.scraped = []

            def search(self, query):
                self.searched.append(query)
                return [
                    ProductRecord(
                        name="Perdue Chicken Breast",
                        price=12.48,
                        product_url="https://shop.shoprite.com/product/chicken",
                    )
                ]

            def scrape_url(self, url):
                self.scraped.append(url)
                return ProductRecord(
                    name="Perdue Chicken Breast",
                    price=12.48,
                    regular_price=13.99,
                    size_value=2.5,
                    size_unit="lb",
                    product_url=url,
                )

        scraper = FakeScraper()
        link = {
            "provider": "shoprite",
            "product_url": None,
            "brand": "Perdue",
            "item_name": "Chicken Breast",
            "pack_price": None,
        }
        outcome = lookup_link(link, lambda _provider: scraper)
        self.assertEqual(scraper.searched, ["Perdue Chicken Breast"])
        self.assertEqual(scraper.scraped, ["https://shop.shoprite.com/product/chicken"])
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["product_url"], "https://shop.shoprite.com/product/chicken")
        self.assertAlmostEqual(outcome["unit_price"], 4.992)

    def test_out_of_stock(self):
        html = "<html><head><title>Milk</title></head><body><h1>Milk</h1><p>Currently unavailable</p></body></html>"
        record = AmazonScraper().parse_html(html, "https://www.amazon.com/dp/B00EXAMPLE")
        self.assertEqual(record.error, "out_of_stock")


class TestDatabase(unittest.TestCase):
    def _db(self):
        client = FakeSupabase(
            {
                "shopping_item_stores": [
                    _row(),
                    _row(id="link-2", item_id="item-2", check_status="ok", product_url="https://www.costco.com/a"),
                ]
            }
        )
        return GroceryDB(client), client

    def test_pending_query(self):
        db, _client = self._db()
        rows = db.fetch_pending()
        self.assertEqual([row["item_store_id"] for row in rows], ["link-1"])
        self.assertEqual(rows[0]["brand"], "Perdue")
        self.assertEqual(rows[0]["provider"], "shoprite")

    def test_item_query(self):
        db, _client = self._db()
        rows = db.fetch_item("item-2")
        self.assertEqual([row["item_store_id"] for row in rows], ["link-2"])

    def test_ok_writes_price_and_history(self):
        db, client = self._db()
        link = db.fetch_pending()[0]
        link["product_url"] = None
        outcome = {
            "status": "ok",
            "price": 12.48,
            "regular_price": 13.99,
            "unit_price": 4.992,
            "size_value": 2.5,
            "size_unit": "lb",
            "product_url": "https://shop.shoprite.com/product/chicken",
        }
        db.apply_outcome(link, outcome, now=WHEN)
        update = client.updates[0]["payload"]
        self.assertEqual(update["pack_price"], 12.48)
        self.assertEqual(update["check_status"], "ok")
        self.assertIsNone(update["check_error"])
        self.assertEqual(update["price_source"], "script")
        self.assertEqual(update["product_url"], "https://shop.shoprite.com/product/chicken")
        history = client.inserts[0]["payload"]
        self.assertEqual(history["item_store_id"], "link-1")
        self.assertEqual(history["source"], "script")
        self.assertEqual(history["unit_price"], 4.992)
        self.assertEqual(history["item_id"], "item-1")

    def test_flagged_keeps_price(self):
        db, client = self._db()
        link = db.fetch_pending()[0]
        outcome = {"status": "flagged", "message": "Price swing flagged: $4.99 -> $20.00", "price": 20}
        db.apply_outcome(link, outcome, now=WHEN)
        update = client.updates[0]["payload"]
        self.assertEqual(update["check_status"], "flagged")
        self.assertNotIn("pack_price", update)
        self.assertEqual(client.inserts, [])

    def test_failed_keeps_price(self):
        db, client = self._db()
        link = db.fetch_pending()[0]
        db.apply_outcome(link, {"status": "failed", "message": "blocked"}, now=WHEN)
        update = client.updates[0]["payload"]
        self.assertEqual(update["check_status"], "failed")
        self.assertEqual(update["check_error"], "blocked")
        self.assertNotIn("pack_price", update)
        self.assertEqual(client.inserts, [])


class TestProcess(unittest.TestCase):
    def test_process_rows_and_listen_interval(self):
        client = FakeSupabase({"shopping_item_stores": [_row(pack_price=4.99)]})
        db = GroceryDB(client)
        rows = db.fetch_pending()

        def lookup(_link):
            return {
                "status": "ok",
                "price": 5.49,
                "regular_price": 5.49,
                "unit_price": 5.49,
                "size_unit": "lb",
                "size_value": 1,
                "product_url": "https://shop.shoprite.com/product/chicken",
            }

        lines, failed = process_rows(rows, lookup, db, now=WHEN, mention_pending=True)
        self.assertEqual(failed, 0)
        self.assertIn("Found 1 pending lookup", lines[0])
        self.assertEqual(client.updates[0]["payload"]["pack_price"], 5.49)

        sleeps = []
        listen_loop(lambda: [], lambda _rows: None, poll_seconds=10, sleep=sleeps.append, max_cycles=2)
        self.assertEqual(sleeps, [10])

    def test_usage(self):
        self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
