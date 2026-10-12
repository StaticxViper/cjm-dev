"""HTML fixtures and block detection. Playwright is not launched."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from grocery.scrapers.amazon import AmazonScraper  # noqa: E402
from grocery.scrapers.base import (  # noqa: E402
    PageFetch,
    backoff_seconds,
    classify_block,
    is_retryable_status,
    store_context_error,
)
from grocery.scrapers.costco import CostcoScraper  # noqa: E402
from grocery.scrapers.shoprite import ShopRiteScraper  # noqa: E402

FIXTURES = ROOT / "scripts" / "grocery" / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestBackoff(unittest.TestCase):
    def test_backoff_and_retryable_status(self):
        self.assertEqual(backoff_seconds(0, 2), 2)
        self.assertEqual(backoff_seconds(1, 2), 4)
        self.assertEqual(backoff_seconds(2, 2), 8)
        self.assertTrue(is_retryable_status(429))
        self.assertTrue(is_retryable_status(503))
        self.assertFalse(is_retryable_status(200))
        self.assertFalse(is_retryable_status(404))


class TestBlockDetection(unittest.TestCase):
    def test_robot_check(self):
        html = (
            "<html><head><title>Robot Check</title></head>"
            "<body>Sorry, we just need to make sure you're not a robot</body></html>"
        )
        self.assertEqual(classify_block(html), "blocked")

    def test_product_fixture_is_not_a_block(self):
        self.assertIsNone(classify_block(_read("amazon_product.html"), "https://www.amazon.com/dp/B00EXAMPLE"))


class TestAmazonFixture(unittest.TestCase):
    def test_product_page(self):
        record = AmazonScraper().parse_html(
            _read("amazon_product.html"),
            "https://www.amazon.com/dp/B00EXAMPLE",
        )
        self.assertEqual(record.error, None)
        self.assertAlmostEqual(record.price, 4.99)
        self.assertAlmostEqual(record.regular_price, 5.99)
        self.assertEqual(record.size_value, 128.0)
        self.assertEqual(record.size_unit, "fl oz")
        self.assertEqual(record.upc, "0123456789012")
        self.assertEqual(record.asin, "B00EXAMPLE")
        self.assertEqual(record.name, "Organic Whole Milk")
        self.assertIn("0.04", record.note or "")
        self.assertNotAlmostEqual(record.price, 3.99)

    def test_one_time_price_beats_json_ld(self):
        html = """
        <script type="application/ld+json">
        {"@type":"Product","name":"Milk","offers":{"@type":"Offer","price":"3.99"}}
        </script>
        <div id="oneTime">One-time purchase <span class="a-offscreen">$4.99</span></div>
        """
        record = AmazonScraper().parse_html(html, "https://www.amazon.com/dp/B00EXAMPLE")
        self.assertAlmostEqual(record.price, 4.99)

    def test_search_skips_subscribe_price(self):
        hits = AmazonScraper().parse_search(
            _read("amazon_search.html"),
            "https://www.amazon.com/s?k=milk",
        )
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0].price, 4.99)
        self.assertEqual(hits[0].asin, "B00EXAMPLE")
        self.assertEqual(hits[0].size_unit, "fl oz")
        self.assertTrue(hits[0].product_url.endswith("/dp/B00EXAMPLE"))


class TestCostcoFixture(unittest.TestCase):
    def test_product_page(self):
        record = CostcoScraper().parse_html(
            _read("costco_product.html"),
            "https://www.costco.com/olive-oil.product.123.html",
        )
        self.assertIsNone(record.error)
        self.assertAlmostEqual(record.price, 14.99)
        self.assertAlmostEqual(record.regular_price, 16.99)
        self.assertEqual(record.size_value, 64.0)
        self.assertEqual(record.size_unit, "oz")
        self.assertEqual(record.upc, "001234567890")
        self.assertEqual(record.note, "delivery surcharge mentioned")

    def test_member_only(self):
        record = CostcoScraper().parse_html(
            _read("costco_member.html"),
            "https://www.costco.com/paper.product.1.html",
        )
        self.assertEqual(record.error, "member_only")
        self.assertIsNone(record.price)

    def test_search(self):
        hits = CostcoScraper().parse_search(
            _read("costco_search.html"),
            "https://www.costco.com/CatalogSearch?keyword=olive",
        )
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0].price, 14.99)
        self.assertEqual(hits[0].size_value, 64.0)


class TestShopRiteFixture(unittest.TestCase):
    def test_product_page(self):
        record = ShopRiteScraper().parse_html(
            _read("shoprite_product.html"),
            "https://shop.shoprite.com/store/shoprite/product/whole-milk",
        )
        self.assertIsNone(record.error)
        self.assertAlmostEqual(record.price, 3.49)
        self.assertAlmostEqual(record.regular_price, 4.29)
        self.assertEqual(record.size_value, 1.0)
        self.assertEqual(record.size_unit, "gal")
        self.assertEqual(record.upc, "012345678905")
        self.assertEqual(record.name, "Whole Milk")

    def test_search(self):
        hits = ShopRiteScraper().parse_search(
            _read("shoprite_search.html"),
            "https://shop.shoprite.com/store/shoprite/search?q=milk",
        )
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0].price, 3.49)
        self.assertEqual(hits[0].size_unit, "gal")

    def test_store_context(self):
        self.assertEqual(store_context_error(False, "", False), "store_context_missing")
        self.assertEqual(store_context_error(False, "07030", False), "store_context_unconfirmed")
        self.assertIsNone(store_context_error(True, "", False))
        self.assertIsNone(store_context_error(False, "07030", True))

        class ExplodingSession:
            def fetch(self, url):
                raise AssertionError(url)

            def try_shoprite_zip(self, zip_code):
                raise AssertionError(zip_code)

        missing = ShopRiteScraper(session=ExplodingSession(), zip_code="", storage_state=None)
        result = missing.scrape_url("https://shop.shoprite.com/product/1")
        self.assertEqual(result.error, "store_context_missing")

        class NoField:
            def try_shoprite_zip(self, zip_code):
                return False

        unconfirmed = ShopRiteScraper(
            session=NoField(),
            zip_code="07030",
            storage_state=Path("missing-shoprite-storage"),
        )
        self.assertEqual(
            unconfirmed.scrape_url("https://shop.shoprite.com/product/1").error,
            "store_context_unconfirmed",
        )

    def test_saved_session_fetches(self):
        class FakeSession:
            def __init__(self):
                self.urls = []

            def fetch(self, url):
                self.urls.append(url)
                return PageFetch(html=_read("shoprite_product.html"), url=url, status=200)

        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        path = Path(handle.name)
        try:
            session = FakeSession()
            scraper = ShopRiteScraper(session=session, zip_code="", storage_state=path)
            record = scraper.scrape_url("https://shop.shoprite.com/store/shoprite/product/whole-milk")
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(session.urls, ["https://shop.shoprite.com/store/shoprite/product/whole-milk"])
        self.assertAlmostEqual(record.price, 3.49)


if __name__ == "__main__":
    unittest.main()
