"""
Unit tests for scripts/apify-scripts/shopify-store.

Run from repo root:
    python -m pytest unittests/apify_scripts/test_shopify_store_actor.py -q

Fixtures only. The catalog fetch is scripted and ``apify.Actor`` is a stand-in,
so these tests never call Shopify or Apify.
"""
import asyncio
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

_REPO = Path(__file__).resolve().parents[2]
_ACTOR = _REPO / "scripts" / "apify-scripts" / "shopify-store"
_SRC = _ACTOR / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "shopify_store"
_ACTOR_MODULES = ("runtime", "spend", "sources", "state", "fetch", "mapping", "main")

NOW = "2026-11-03T12:00:00+00:00"


class FakeStore:
    def __init__(self, data):
        self.data = data

    async def get_value(self, key):
        return self.data.get(key)

    async def set_value(self, key, value):
        self.data[key] = json.loads(json.dumps(value))


class FakeActor:
    def __init__(self, actor_input, stores=None, limit_after=None):
        self.input = actor_input
        self.stores = stores if stores is not None else {}
        self.pushed = []
        self.charges = []
        self.values = {}
        self.opened = []
        self.limit_after = limit_after

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_input(self):
        return self.input

    async def push_data(self, row):
        self.pushed.append(row)

    async def charge(self, event_name=None):
        self.charges.append(event_name)
        reached = self.limit_after is not None and len(self.charges) >= self.limit_after
        return types.SimpleNamespace(event_charge_limit_reached=reached)

    async def set_value(self, key, value):
        self.values[key] = value

    async def open_key_value_store(self, name=None):
        self.opened.append(name)
        return FakeStore(self.stores.setdefault(name, {}))


def _load_actor():
    saved = {name: sys.modules.pop(name) for name in _ACTOR_MODULES if name in sys.modules}
    inserted = str(_SRC) not in sys.path[:1]
    if inserted:
        sys.path.insert(0, str(_SRC))
    fake_apify = types.ModuleType("apify")
    fake_apify.Actor = FakeActor({})
    try:
        with mock.patch.dict(sys.modules, {"apify": fake_apify}):
            return {name: importlib.import_module(name) for name in _ACTOR_MODULES}
    finally:
        for name in _ACTOR_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        if inserted and sys.path and sys.path[0] == str(_SRC):
            sys.path.pop(0)


_actor = _load_actor()
mapping = _actor["mapping"]
fetch_mod = _actor["fetch"]
sources = _actor["sources"]
spend = _actor["spend"]
state_mod = _actor["state"]
main_mod = _actor["main"]


def _text(name):
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _json_body(text, status=200):
    return {"status": status, "text": text, "content_type": "application/json"}


def _html_body(text, status=200):
    return {"status": status, "text": text, "content_type": "text/html"}


class Scripted:
    """Answers catalog URLs from fixtures. No network."""

    def __init__(self, overrides=None, robots=None, products=None, collections=None, home=None):
        self.overrides = overrides or {}
        self.robots = robots or {}
        self.products = products or {}
        self.collections = collections or {}
        self.home = home or {}
        self.urls = []

    def direct(self, url):
        self.urls.append(url)
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.path == "/robots.txt":
            if host in self.robots:
                return self.robots[host]
            return {"status": 200, "text": "User-agent: *\nAllow: /\n", "content_type": "text/plain"}
        for needle, response in self.overrides.items():
            if needle in url:
                return dict(response)
        if parsed.path == "/products.json":
            return _json_body(self.products.get(host) or _text("products_page1.json"))
        if parsed.path == "/collections.json":
            return _json_body(self.collections.get(host) or _text("collections.json"))
        if parsed.path in ("/", ""):
            return _html_body(self.home.get(host) or _text("homepage.html"))
        return {"status": 404, "text": "missing", "content_type": "text/plain"}


def _run(scripted=None, prices=None, **actor_input):
    scripted = scripted or Scripted()
    payload = {"domains": ["example.test"], "maxItems": 100, "maxSpendUsd": 5}
    payload.update(actor_input)
    config = mapping.actor_input_to_config(payload)
    fetch = fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _seconds: None)
    rows, summary, new_prices = mapping.scrape(config, fetch, prices=prices, now=NOW)
    return rows, summary, new_prices, scripted


def _products(rows):
    return [row for row in rows if row.get("kind") == "product"]


def _stores(rows):
    return [row for row in rows if row.get("kind") == "store"]


def _by_status(rows, status):
    return [row for row in rows if row.get("sourceStatus") == status]


def _run_main(actor_input, scripted=None, stores=None, limit_after=None):
    scripted = scripted or Scripted()
    actor = FakeActor(actor_input, stores=stores, limit_after=limit_after)
    fake_apify = types.ModuleType("apify")
    fake_apify.Actor = actor

    def live(config):
        return fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _seconds: None)

    with mock.patch.dict(sys.modules, {"apify": fake_apify}), \
            mock.patch.object(main_mod, "Actor", actor), \
            mock.patch.object(main_mod, "make_live_fetch", live):
        asyncio.run(main_mod.main())
    return actor, scripted


class TestInput(unittest.TestCase):
    def test_defaults_bounds_and_domains(self):
        config = mapping.actor_input_to_config({
            "domains": ["https://www.Example.test/products/shoe", "example.test", "not a host"],
            "maxProductsPerStore": 99999,
            "maxItems": 0,
            "delaySeconds": 0,
            "maxSpendUsd": 1000,
            "stateStoreName": "../secrets",
        })
        self.assertEqual(config["domains"], ["example.test"])
        self.assertEqual(config["invalid"], ["not a host"])
        self.assertEqual(config["duplicate_domains"], 1)
        self.assertEqual(config["max_products_per_store"], 1000)
        self.assertEqual(config["max_items"], 1)
        self.assertEqual(config["delay_seconds"], 1.0)
        self.assertEqual(config["max_spend_usd"], 100.0)
        self.assertEqual(config["state_store"], sources.STATE_STORE)
        self.assertFalse(config["track_price_changes"])
        self.assertFalse(config["error"])

    def test_empty_input_is_an_error(self):
        rows, summary, _prices, _scripted = _run(domains=[])
        self.assertEqual(rows[0]["sourceStatus"], "error")
        self.assertEqual(summary["status"], "error")
        self.assertEqual(_scripted.urls, [])


class TestCatalog(unittest.TestCase):
    def test_products_variants_collections_and_theme(self):
        rows, summary, prices, scripted = _run(trackPriceChanges=True)
        store = _stores(rows)[0]
        products = _products(rows)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["stopped"], "")
        self.assertEqual(store["store"], "example.test")
        self.assertEqual(store["title"], "Example Store")
        self.assertEqual(store["currency"], "USD")
        self.assertEqual(store["myshopifyDomain"], "example.myshopify.com")
        self.assertEqual(store["theme"]["name"], "Dawn")
        self.assertEqual(store["theme"]["themeStoreId"], "887")
        self.assertEqual(store["themeStatus"], "found")
        self.assertEqual(sorted(hint["name"] for hint in store["appHints"]), ["judge-me", "klaviyo-email"])
        self.assertEqual(store["collectionCount"], 2)
        self.assertEqual(store["collections"][0]["handle"], "men")
        self.assertEqual(store["collectionsStatus"], "found")
        self.assertEqual([row["productId"] for row in products], ["1001", "1002"])
        wool = products[0]
        self.assertEqual(wool["title"], "Wool Runner")
        self.assertEqual(wool["url"], "https://example.test/products/wool-runner")
        self.assertTrue(wool["available"])
        self.assertEqual(wool["priceMin"], 98.0)
        self.assertEqual(wool["variantCount"], 2)
        self.assertEqual(wool["variants"][0]["sku"], "WR-8")
        self.assertEqual(wool["variants"][0]["compareAtPrice"], 110.0)
        self.assertFalse(wool["variants"][1]["available"])
        self.assertEqual(wool["priceChange"]["reason"], "no_prior")
        self.assertFalse(wool["priceChanged"])
        self.assertEqual(wool["decision"], "new")
        self.assertEqual(wool["themeName"], "Dawn")
        self.assertIn("example.test|1001|5001", prices)
        self.assertEqual(prices["example.test|1001|5001"]["price"], 98.0)
        self.assertTrue(any(url.endswith("/products.json?limit=50&page=1") for url in scripted.urls))
        self.assertTrue(any("/collections.json" in url for url in scripted.urls))
        self.assertFalse(any("meta.json" in url for url in scripted.urls))

    def test_price_change_against_saved_state(self):
        priors = {
            "example.test|1001|5001": {"price": 90.0, "seenAt": "2026-10-01T00:00:00+00:00"},
            "example.test|1001|5002": {"price": 98.0, "seenAt": "2026-09-01T00:00:00+00:00"},
        }
        rows, _summary, _prices, _scripted = _run(trackPriceChanges=True, prices=priors)
        wool = _products(rows)[0]
        first, second = wool["variants"]
        self.assertEqual(first["previousPrice"], 90.0)
        self.assertEqual(first["priceDelta"], 8.0)
        self.assertTrue(first["priceChanged"])
        self.assertEqual(second["previousPrice"], 98.0)
        self.assertEqual(second["priceDelta"], 0.0)
        self.assertFalse(second["priceChanged"])
        self.assertTrue(wool["priceChanged"])
        self.assertEqual(wool["priceChange"]["variantsChanged"], 1)
        self.assertEqual(wool["priceChange"]["previousMin"], 90.0)
        self.assertEqual(wool["priceChange"]["previousSeenAt"], "2026-10-01T00:00:00+00:00")
        self.assertEqual(wool["decision"], "changed")
        self.assertEqual(wool["publishedAt"], "2024-01-15T08:00:00+00:00")

    def test_tracking_off_leaves_price_change_empty_but_saves_prices(self):
        priors = {"example.test|1001|5001": {"price": 90.0, "seenAt": "2026-10-01T00:00:00+00:00"}}
        rows, _summary, prices, _scripted = _run(trackPriceChanges=False, prices=priors)
        wool = _products(rows)[0]
        self.assertIsNone(wool["priceChange"])
        self.assertIsNone(wool["priceChanged"])
        self.assertIsNone(wool["variants"][0]["previousPrice"])
        self.assertEqual(wool["decision"], "listed")
        self.assertEqual(prices["example.test|1001|5001"]["price"], 98.0)

    def test_dedupe_and_max_items_skip_later_stores(self):
        payload = json.loads(_text("products_page1.json"))
        payload["products"].insert(1, dict(payload["products"][0]))
        scripted = Scripted(products={"example.test": json.dumps(payload)})
        rows, summary, _prices, scripted = _run(
            scripted=scripted,
            domains=["example.test", "other.test"],
            maxItems=2,
            maxProductsPerStore=10,
        )
        self.assertEqual([row["productId"] for row in _products(rows)], ["1001", "1002"])
        self.assertEqual(summary["mergedDuplicates"], 1)
        self.assertTrue(summary["truncated"])
        self.assertFalse(any("other.test" in url for url in scripted.urls))

    def test_pagination_requests_the_next_full_page(self):
        def direct(url):
            direct.urls.append(url)
            parsed = urlparse(url)
            if parsed.path == "/robots.txt":
                return {"status": 200, "text": "User-agent: *\nAllow: /\n", "content_type": "text/plain"}
            page = int(parse_qs(parsed.query).get("page", ["1"])[0])
            limit = int(parse_qs(parsed.query).get("limit", ["1"])[0])
            if page == 1:
                items = [{"id": index, "title": f"P{index}", "handle": f"p-{index}", "variants": [
                    {"id": index, "title": "Default", "price": "5.00", "available": True},
                ]} for index in range(1, limit + 1)]
            elif page == 2:
                items = [{"id": 9000, "title": "Last", "handle": "last", "variants": [
                    {"id": 9000, "title": "Default", "price": "6.00", "available": True},
                ]}]
            else:
                items = []
            return _json_body(json.dumps({"products": items}))

        direct.urls = []
        config = mapping.actor_input_to_config({"domains": ["example.test"], "delaySeconds": 1})
        fetch = fetch_mod.build_fetch(config, direct, sleep=lambda _seconds: None)
        products, status, _result, _partial, dupes = mapping._read_json_pages(
            "example.test", fetch, sources.products_url, "products", mapping.parse_product, 500, 20,
        )
        self.assertEqual(status, "ok")
        self.assertEqual(dupes, 0)
        self.assertEqual(len(products), 251)
        self.assertEqual(products[-1]["productId"], "9000")
        pages = [parse_qs(urlparse(url).query).get("page", ["1"])[0] for url in direct.urls if "products.json" in url]
        self.assertEqual(pages, ["1", "2"])

    def test_block_on_a_later_page_keeps_products_already_parsed(self):
        def direct(url):
            direct.urls.append(url)
            parsed = urlparse(url)
            if parsed.path == "/robots.txt":
                return {"status": 200, "text": "User-agent: *\nAllow: /\n", "content_type": "text/plain"}
            if parsed.path != "/products.json":
                direct.extra.append(url)
                return {"status": 404, "text": "should not be requested", "content_type": "text/plain"}
            page = int(parse_qs(parsed.query).get("page", ["1"])[0])
            limit = int(parse_qs(parsed.query).get("limit", ["1"])[0])
            if page == 1:
                items = [{"id": index, "title": f"P{index}", "handle": f"p-{index}", "variants": [
                    {"id": index, "title": "Default", "price": "5.00", "available": True, "sku": "S"},
                ]} for index in range(1, limit + 1)]
                return _json_body(json.dumps({"products": items}))
            return {"status": 403, "text": "no", "content_type": "text/plain"}

        direct.urls = []
        direct.extra = []
        scripted = Scripted()
        scripted.direct = direct
        rows, summary, _prices, _scripted = _run(
            scripted=scripted,
            domains=["example.test", "later.test"],
            maxProductsPerStore=1000,
            maxItems=1000,
        )
        self.assertEqual(len(_products(rows)), 250)
        self.assertTrue(_stores(rows)[0]["partial"])
        self.assertEqual(_stores(rows)[0]["collectionsStatus"], "not_fetched")
        self.assertEqual(summary["stopped"], "blocked")
        self.assertEqual(direct.extra, [])
        self.assertFalse(any("later.test" in url for url in direct.urls))

    def test_block_on_products_stops_the_run(self):
        scripted = Scripted(overrides={
            "blocked.test/products.json": {"status": 429, "text": "slow down", "content_type": "text/plain"},
        })
        rows, summary, _prices, scripted = _run(
            scripted=scripted,
            domains=["example.test", "blocked.test", "later.test"],
        )
        blocked = _by_status(rows, "blocked")
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["store"], "blocked.test")
        self.assertIn("does not use a proxy", blocked[0]["error"])
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["stopped"], "blocked")
        self.assertEqual(len(_products(rows)), 2)
        product_calls = [url for url in scripted.urls if "blocked.test/products.json" in url]
        self.assertEqual(len(product_calls), 1)
        self.assertFalse(any("later.test" in url for url in scripted.urls))

    def test_challenge_page_is_a_block(self):
        scripted = Scripted(overrides={
            "example.test/products.json": _html_body(_text("challenge.html")),
        })
        rows, summary, _prices, scripted = _run(scripted=scripted, domains=["example.test", "other.test"])
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(_products(rows), [])
        self.assertEqual(_stores(rows), [])
        self.assertFalse(any("other.test" in url for url in scripted.urls))

    def test_password_page_is_not_a_block(self):
        scripted = Scripted(overrides={
            "example.test/products.json": _html_body(_text("password.html")),
        })
        rows, summary, _prices, scripted = _run(scripted=scripted, domains=["example.test", "other.test"])
        self.assertEqual(_by_status(rows, "unavailable")[0]["store"], "example.test")
        self.assertEqual(summary["stopped"], "")
        self.assertEqual(_stores(rows)[0]["store"], "other.test")
        self.assertTrue(any("other.test/products.json" in url for url in scripted.urls))

    def test_homepage_challenge_does_not_stop_the_run(self):
        scripted = Scripted(home={"example.test": _text("challenge.html")})
        rows, summary, _prices, scripted = _run(scripted=scripted, domains=["example.test", "other.test"])
        self.assertEqual(summary["stopped"], "")
        self.assertEqual(_stores(rows)[0]["themeStatus"], "blocked")
        self.assertEqual(_stores(rows)[0]["appHints"], [])
        self.assertEqual(len(_products(rows)), 4)
        self.assertTrue(any("other.test" in url for url in scripted.urls))

    def test_collections_block_keeps_products_and_stops(self):
        scripted = Scripted(overrides={
            "example.test/collections.json": {"status": 403, "text": "no", "content_type": "text/plain"},
        })
        rows, summary, _prices, scripted = _run(scripted=scripted, domains=["example.test", "other.test"])
        self.assertEqual(len(_products(rows)), 2)
        self.assertEqual(_stores(rows)[0]["collectionsStatus"], "blocked")
        self.assertEqual(_stores(rows)[0]["themeStatus"], "not_fetched")
        self.assertTrue(_stores(rows)[0]["partial"])
        self.assertEqual(summary["stopped"], "blocked")
        self.assertFalse(any("other.test" in url for url in scripted.urls))
        self.assertFalse(any(urlparse(url).path == "/" and "example.test" in url for url in scripted.urls))

    def test_missing_collections_still_reads_the_homepage(self):
        scripted = Scripted(overrides={
            "example.test/collections.json": {"status": 404, "text": "no", "content_type": "text/plain"},
        })
        rows, _summary, _prices, scripted = _run(scripted=scripted)
        self.assertEqual(_stores(rows)[0]["collectionsStatus"], "not_found")
        self.assertEqual(_stores(rows)[0]["themeStatus"], "found")
        self.assertTrue(any(urlparse(url).path == "/" for url in scripted.urls))

    def test_robots_disallow_skips_the_catalog_and_continues(self):
        scripted = Scripted(robots={
            "example.test": {
                "status": 200,
                "text": "User-agent: *\nDisallow: /products.json\n",
                "content_type": "text/plain",
            },
        })
        rows, summary, _prices, scripted = _run(scripted=scripted, domains=["example.test", "other.test"])
        self.assertEqual(_by_status(rows, "robots_disallowed")[0]["store"], "example.test")
        self.assertEqual(summary["stopped"], "")
        self.assertFalse(any("example.test/products.json" in url for url in scripted.urls))
        self.assertTrue(any("other.test/products.json" in url for url in scripted.urls))


class TestHttp(unittest.TestCase):
    def test_429_is_not_retried_and_5xx_is_retried_once(self):
        class Response:
            def __init__(self, status, body=b"{}"):
                self.status_code = status
                self.content = body
                self.headers = {"Content-Type": "application/json"}

        class Client:
            def __init__(self, statuses):
                self.statuses = list(statuses)
                self.calls = 0

            def get(self, url, headers=None):
                self.calls += 1
                return Response(self.statuses.pop(0))

        blocked = Client([429, 200])
        sleeps = []
        result = fetch_mod.http_get("https://example.test/products.json", client=blocked, sleep=lambda *args: sleeps.append(args))
        self.assertEqual(blocked.calls, 1)
        self.assertEqual(result["status"], 429)
        self.assertEqual(sleeps, [])

        flaky = Client([500, 200])
        result = fetch_mod.http_get("https://example.test/products.json", client=flaky, sleep=lambda *args: None)
        self.assertEqual(flaky.calls, 2)
        self.assertEqual(result["status"], 200)

        denied = Client([403, 200])
        result = fetch_mod.http_get("https://example.test/products.json", client=denied, sleep=lambda *args: None)
        self.assertEqual(denied.calls, 1)
        self.assertEqual(result["status"], 403)


class TestSpendAndState(unittest.TestCase):
    def test_prices_match_the_event_file_and_omit_proxy(self):
        events = json.loads((_ACTOR / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        charges = events["actorChargeEvents"]
        self.assertEqual(set(charges), {"product", "store"})
        self.assertEqual(charges["product"]["eventPriceUsd"], spend.PRICES_USD["product"])
        self.assertEqual(charges["store"]["eventPriceUsd"], spend.PRICES_USD["store"])
        self.assertTrue(charges["product"]["isPrimaryEvent"])
        schema = json.loads((_ACTOR / ".actor" / "input_schema.json").read_text(encoding="utf-8"))
        self.assertNotIn("proxyConfiguration", schema["properties"])
        self.assertNotIn("allowCaptcha", schema["properties"])

    def test_spend_cap_pushes_the_store_and_holds_products(self):
        actor, _scripted = _run_main({
            "domains": ["example.test"],
            "maxSpendUsd": 0.012,
            "maxItems": 10,
        })
        kinds = [row["kind"] for row in actor.pushed]
        self.assertEqual(kinds[0], "store")
        self.assertEqual(kinds[1], "product")
        self.assertEqual(actor.pushed[1]["productId"], "1001")
        self.assertIn("status", kinds)
        self.assertEqual(actor.pushed[-1]["sourceStatus"], "spend_capped")
        self.assertEqual(actor.charges, ["store", "product"])
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["billedProducts"], 1)
        self.assertEqual(summary["billedStores"], 1)
        self.assertEqual(summary["heldBackProducts"], 1)
        self.assertTrue(summary["chargeCapped"])
        saved = actor.stores["shopify-store-state"]["PRICES"]["prices"]
        self.assertIn("example.test|1001|5001", saved)
        self.assertNotIn("example.test|1002|5003", saved)

    def test_state_round_trip_keeps_the_latest_price(self):
        seen = state_mod.load_state({
            "version": 1,
            "prices": {"example.test|1001|5001": {"price": "nope", "seenAt": "x"}, "ok": {"price": 1}},
        })
        self.assertNotIn("example.test|1001|5001", seen)
        merged = state_mod.merge_state(
            {"example.test|1001|5001": {"price": 90.0, "seenAt": "2026-10-01T00:00:00+00:00"}},
            {"example.test|1001|5001": {"price": 98.0, "seenAt": NOW}},
        )
        self.assertEqual(merged["example.test|1001|5001"]["price"], 98.0)
        dumped = state_mod.dump_state(merged, NOW)
        self.assertEqual(state_mod.load_state(dumped)["example.test|1001|5001"]["price"], 98.0)


if __name__ == "__main__":
    unittest.main()
