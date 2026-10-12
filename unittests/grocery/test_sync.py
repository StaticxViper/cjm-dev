"""Push batching and the grocery-lookup client. HTTP and Playwright are mocked."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from grocery.config import ConfigError, Settings, load_settings  # noqa: E402
from grocery.models import ProductRecord  # noqa: E402
from grocery.sync import (  # noqa: E402
    batch_prices,
    format_summary,
    interpret_push_response,
    main,
    normalize_link,
    provider_for_url,
    sync_records,
    to_push_item,
    GroceryClient,
)


def _settings() -> Settings:
    return Settings(
        supabase_url="https://example.supabase.co",
        service_role_key="service",
        anon_key="anon",
        shoprite_zip="07030",
        timeout_ms=30000,
        min_delay_s=2,
        batch_size=20,
        storage_state_path=Path("unused"),
    )


class TestConfig(unittest.TestCase):
    def test_missing_supabase(self):
        env = {
            "SUPABASE_URL": "",
            "SUPABASE_SERVICE_ROLE_KEY": "",
            "SUPABASE_ANON_KEY": "",
        }
        with mock.patch("grocery.config.load_dotenv"), mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(ConfigError):
                load_settings(require_supabase=True)

    def test_delay_and_batch_floor(self):
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service",
            "SUPABASE_ANON_KEY": "anon",
            "GROCERY_MIN_DELAY_SECONDS": "0",
            "GROCERY_BATCH_SIZE": "0",
        }
        with mock.patch("grocery.config.load_dotenv"), mock.patch.dict(os.environ, env, clear=False):
            settings = load_settings()
        self.assertEqual(settings.min_delay_s, 2.0)
        self.assertEqual(settings.batch_size, 20)


class TestPayload(unittest.TestCase):
    def test_to_push_item(self):
        product = ProductRecord(
            price=4.99,
            regular_price=5.99,
            size_value=16,
            size_unit="oz",
            product_url="https://www.amazon.com/dp/B00EXAMPLE",
        )
        item = to_push_item("abc", product, force=False)
        self.assertEqual(item["source"], "script")
        self.assertFalse(item["force"])
        self.assertAlmostEqual(item["price"], 4.99)
        self.assertEqual(item["size_unit"], "oz")
        self.assertNotIn("name", item)

    def test_batch_prices(self):
        prices = [{"item_store_id": str(index)} for index in range(45)]
        batches = batch_prices(prices, 20)
        self.assertEqual([len(batch) for batch in batches], [20, 20, 5])
        self.assertEqual(batch_prices([], 20), [])

    def test_normalize_link_list_embed(self):
        row = normalize_link(
            {
                "id": "store-1",
                "product_url": "https://www.costco.com/item.html",
                "shopping_stores": [{"name": "Costco", "provider": "Costco"}],
                "shopping_items": [{"name": "Milk", "upc": "111"}],
            }
        )
        self.assertEqual(row["item_store_id"], "store-1")
        self.assertEqual(row["provider"], "costco")
        self.assertEqual(row["item_name"], "Milk")

    def test_provider_for_url(self):
        self.assertEqual(provider_for_url("https://www.amazon.com/dp/B00EXAMPLE"), "amazon")
        self.assertEqual(provider_for_url("https://www.costco.com/item.html"), "costco")
        self.assertEqual(provider_for_url("https://shop.shoprite.com/product/1"), "shoprite")
        with self.assertRaises(ConfigError):
            provider_for_url("https://example.com/item")


class TestInterpret(unittest.TestCase):
    def test_flagged_and_http_error(self):
        sent = [
            {"item_store_id": "a", "price": 4.99, "product_url": "https://www.costco.com/a", "name": "A"},
            {"item_store_id": "b", "price": 1.00, "product_url": "https://www.costco.com/b", "name": "B"},
        ]
        flagged = interpret_push_response(
            {"results": [{"item_store_id": "a", "status": "flagged", "message": "outlier"}]},
            sent,
            http_status=200,
        )
        self.assertEqual(flagged[0]["status"], "flagged")
        self.assertEqual(flagged[1]["status"], "ok")
        failed = interpret_push_response({"message": "nope"}, sent, http_status=500)
        self.assertTrue(all(row["status"] == "error" for row in failed))
        self.assertEqual(failed[0]["message"], "nope")

    def test_prices_key(self):
        sent = [{"item_store_id": "a", "price": 2}]
        rows = interpret_push_response(
            {"prices": [{"item_store_id": "a", "status": "ok"}]},
            sent,
            http_status=200,
        )
        self.assertEqual(rows[0]["status"], "ok")


class TestSyncRecords(unittest.TestCase):
    def test_batches_flags_and_skips(self):
        records = [
            {
                "item_store_id": f"id-{index}",
                "product_url": f"https://www.costco.com/{index}",
                "provider": "costco",
                "item_name": f"Item {index}",
            }
            for index in range(22)
        ]
        records.append({"item_store_id": "no-url", "product_url": "", "item_name": "Missing"})

        def scrape(record):
            if record["item_store_id"] == "id-0":
                return ProductRecord(product_url=record["product_url"], error="blocked")
            return ProductRecord(
                name=record["item_name"],
                price=4.99,
                regular_price=5.99,
                size_value=16,
                size_unit="oz",
                product_url=record["product_url"],
            )

        batches = []

        def push(prices):
            batches.append(prices)
            results = []
            for item in prices:
                self.assertNotIn("name", item)
                self.assertEqual(item["source"], "script")
                self.assertFalse(item["force"])
                status = "flagged" if item["item_store_id"] == "id-1" else "ok"
                results.append(
                    {
                        "item_store_id": item["item_store_id"],
                        "status": status,
                        "message": "outlier" if status == "flagged" else "",
                    }
                )
            return 200, {"results": results}

        outcomes = sync_records(records, scrape, push, force=False, dry_run=False, batch_size=20)
        self.assertEqual([len(batch) for batch in batches], [20, 1])
        by_id = {row["item_store_id"]: row for row in outcomes}
        self.assertEqual(by_id["id-0"]["status"], "failed")
        self.assertEqual(by_id["id-0"]["reason"], "blocked")
        self.assertEqual(by_id["id-1"]["status"], "flagged")
        self.assertEqual(by_id["no-url"]["status"], "skipped")
        summary = format_summary(outcomes)
        self.assertIn("Flagged outliers (1)", summary)
        self.assertIn("Failed URLs (1)", summary)
        self.assertIn("Skipped (no URL): 1", summary)
        self.assertIn("OK (20)", summary)

    def test_dry_run_does_not_push(self):
        def push(_prices):
            raise AssertionError("push called")

        outcomes = sync_records(
            [{"item_store_id": "a", "product_url": "https://www.costco.com/a", "item_name": "Milk"}],
            lambda record: ProductRecord(name="Milk", price=3.5, product_url=record["product_url"]),
            push,
            force=False,
            dry_run=True,
            batch_size=20,
        )
        self.assertEqual(outcomes[0]["status"], "dry_run")
        self.assertIn("Dry run (1)", format_summary(outcomes))


class TestClient(unittest.TestCase):
    def test_pull_and_push(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers["authorization"]
            seen["apikey"] = request.headers["apikey"]
            if request.url.path.endswith("shopping_item_stores"):
                self.assertIn("eq.costco", str(request.url))
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": "store-1",
                            "product_url": "https://www.costco.com/item.html",
                            "shopping_stores": {"name": "Costco", "provider": "costco"},
                            "shopping_items": {"name": "Milk", "upc": "111"},
                        }
                    ],
                )
            body = json.loads(request.content.decode())
            seen["action"] = body["action"]
            seen["keys"] = sorted(body["prices"][0].keys())
            return httpx.Response(
                200,
                json={"results": [{"item_store_id": "store-1", "status": "flagged", "message": "outlier"}]},
            )

        client = GroceryClient(_settings(), http=httpx.Client(transport=httpx.MockTransport(handler)))
        links = client.fetch_links("costco")
        code, body = client.push_prices(
            [{"item_store_id": "store-1", "price": 4.99, "source": "script", "force": False}]
        )
        self.assertEqual(links[0]["item_name"], "Milk")
        self.assertEqual(code, 200)
        self.assertEqual(body["results"][0]["status"], "flagged")
        self.assertEqual(seen["authorization"], "Bearer service")
        self.assertEqual(seen["apikey"], "anon")
        self.assertEqual(seen["action"], "push_prices")
        self.assertNotIn("name", seen["keys"])


class TestCli(unittest.TestCase):
    def test_usage(self):
        self.assertEqual(main([]), 2)
        self.assertEqual(main(["--search", "whole milk"]), 2)


if __name__ == "__main__":
    unittest.main()
