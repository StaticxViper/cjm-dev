"""
Unit tests for the Zillow agents Actor.

Fixtures only. No live Zillow, Google, or Apify calls.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_zillow_actor
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "scripts" / "apify-scripts" / "zillow" / "src"
_FIXTURES = _REPO / "unittests" / "zillow_automation" / "fixtures"
_ACTOR_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    spec = importlib.util.spec_from_file_location(f"zillow_actor_{name}", _SRC / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pipeline = _load("pipeline")
remote = _load("remote")
zillow_agents = pipeline.zillow_agents


def _read(name):
    return (_FIXTURES / name).read_text(encoding="utf-8")


class _Page:
    def set_default_timeout(self, _ms):
        return None

    def route(self, *_args, **_kwargs):
        return None

    def unroute(self, *_args, **_kwargs):
        return None


class _Browser:
    def new_page(self, **_kwargs):
        return _Page()

    def close(self):
        return None


class _Chromium:
    def __init__(self):
        self.kwargs = None

    def launch(self, **kwargs):
        self.kwargs = kwargs
        return _Browser()


class _Playwright:
    def __init__(self):
        self.chromium = _Chromium()

    def start(self):
        return self


class _ProxyConfig:
    def __init__(self, url):
        self.url = url
        self.session_id = None

    async def new_url(self, session_id=None):
        self.session_id = session_id
        return self.url


class _Actor:
    def __init__(self, configuration):
        self.configuration = configuration
        self.calls = []

    async def create_proxy_configuration(self, actor_proxy_input=None):
        self.calls.append(actor_proxy_input)
        return self.configuration


class _Items:
    def __init__(self, items):
        self.items = items


class _Dataset:
    def __init__(self, items):
        self._items = items

    def list_items(self):
        return _Items(self._items)


class _Store:
    def __init__(self, records):
        self._records = records

    def get_record(self, key):
        if key not in self._records:
            return None
        return {"value": self._records[key]}


class _Client:
    def __init__(self, run, items, records):
        self.run = run
        self.items = items
        self.records = records
        self.actor_id = None
        self.run_input = None

    def actor(self, actor_id):
        self.actor_id = actor_id
        return self

    def call(self, run_input=None):
        self.run_input = run_input
        return self.run

    def dataset(self, _dataset_id):
        return _Dataset(self.items)

    def key_value_store(self, _store_id):
        return _Store(self.records)


class TestInput(unittest.TestCase):
    def test_minimal_input_uses_defaults(self):
        settings = pipeline.read_run_input({"zip_codes": ["08002"]})
        self.assertEqual(settings["criteria"]["zipCodes"], ["08002"])
        self.assertEqual(settings["criteria"]["resultsLimit"], 0)
        self.assertEqual(settings["max_listings"], 100)
        self.assertEqual(settings["max_agents"], 50)
        self.assertTrue(settings["enrich"])
        self.assertTrue(settings["headless"])
        self.assertTrue(settings["criteria"]["forSaleByAgent"])
        self.assertFalse(settings["criteria"]["forRent"])

    def test_dataset_row_keeps_enrichment(self):
        row = pipeline.dataset_row({
            "agent_name": "Jane Smith",
            "brokerage": "Compass",
            "phone": "(856) 555-0101",
            "email": "jane.smith@compass.com",
            "license": "NJ-12345",
            "profile_url": "https://www.zillow.com/profile/jane-smith",
            "enrichment_source": "website",
            "enrichment_source_url": "https://example.com/jane",
            "confidence": 80,
            "listing_addresses": ["1 Main St, Cherry Hill, NJ 08002"],
        })
        self.assertEqual(row["enrichment_source"], "website")
        self.assertEqual(row["enrichment_source_url"], "https://example.com/jane")
        self.assertEqual(row["confidence"], 80)
        self.assertEqual(row["listing_addresses"], ["1 Main St, Cherry Hill, NJ 08002"])
        summary = pipeline.run_summary({
            "stats": {"listings_found": 2, "agents_found": 1, "agents_enriched": 1},
            "areas": {"08002": {"status": "blocked"}, "08057": {"status": "done"}},
        })
        self.assertEqual(summary["listings_found"], 2)
        self.assertEqual(summary["agents_found"], 1)
        self.assertEqual(summary["agents_enriched"], 1)
        self.assertEqual(summary["blocked_zips"], ["08002"])

    def test_zip_codes_are_required(self):
        with self.assertRaises(ValueError):
            pipeline.read_run_input({"max_listings": 10})

    def test_price_and_status_overrides(self):
        settings = pipeline.read_run_input({
            "zip_codes": "08002, 08057",
            "max_listings": 25,
            "max_agents": 5,
            "priceMin": 150000,
            "price_max": 400000,
            "forRent": True,
            "sold": False,
            "enrich": False,
        })
        self.assertEqual(settings["criteria"]["zipCodes"], ["08002", "08057"])
        self.assertEqual(settings["criteria"]["priceMin"], 150000)
        self.assertEqual(settings["criteria"]["priceMax"], 400000)
        self.assertTrue(settings["criteria"]["forRent"])
        self.assertFalse(settings["criteria"]["sold"])
        self.assertFalse(settings["enrich"])
        self.assertEqual(settings["max_listings"], 25)
        self.assertEqual(settings["max_agents"], 5)

    def test_proxy_defaults_to_residential_and_skips_local(self):
        payload = pipeline.proxy_actor_input({})
        self.assertEqual(payload["useApifyProxy"], True)
        self.assertEqual(payload["apifyProxyGroups"], ["RESIDENTIAL"])
        chosen = pipeline.proxy_actor_input({
            "proxyConfiguration": {"useApifyProxy": False, "apifyProxyGroups": ["SHADER"]},
        })
        self.assertEqual(chosen["apifyProxyGroups"], ["SHADER"])
        self.assertTrue(chosen["useApifyProxy"])
        self.assertNotIn("APIFY_IS_AT_HOME", os.environ)
        self.assertFalse(pipeline.on_platform())

    def test_platform_proxy_uses_create_proxy_configuration(self):
        url = "http://groups-RESIDENTIAL:secret@proxy.apify.com:8000"
        config = _ProxyConfig(url)
        actor = _Actor(config)

        async def _open():
            return await pipeline.open_playwright_proxy(
                actor,
                {"zip_codes": ["08002"]},
                at_home=True,
                session_id="zillowtest",
            )

        import asyncio

        proxy = asyncio.run(_open())
        self.assertEqual(actor.calls[0]["apifyProxyGroups"], ["RESIDENTIAL"])
        self.assertEqual(config.session_id, "zillowtest")
        self.assertEqual(proxy["server"], "http://proxy.apify.com:8000")
        self.assertEqual(proxy["username"], "groups-RESIDENTIAL")
        self.assertEqual(proxy["password"], "secret")
        self.assertIsNone(asyncio.run(pipeline.open_playwright_proxy(actor, {}, at_home=False)))

        async def _missing():
            return await pipeline.open_playwright_proxy(_Actor(None), {}, at_home=True)

        with self.assertRaises(RuntimeError):
            asyncio.run(_missing())


class TestPipelineCaps(unittest.TestCase):
    def _run(self, fetch, root, actor_input, **kwargs):
        checkpoints = []
        with patch.object(pipeline.zillow_agents, "ZillowBrowser", side_effect=AssertionError("no browser")):
            collected = pipeline.run_collected(
                actor_input,
                fetch=fetch,
                output_dir=root,
                checkpoint_path=Path(root) / "checkpoint.json",
                seen_path=Path(root) / "seen.json",
                on_checkpoint=checkpoints.append,
                run_date="2026-10-24",
                at_home=False,
                **kwargs,
            )
        return collected, checkpoints

    def test_caps_dedupe_and_local_files(self):
        search = _read("search_results.html")
        detail = _read("listing_detail.html")
        second = (_ACTOR_FIXTURES / "listing_second_agent.html").read_text(encoding="utf-8")
        requested = []

        def fetch(url):
            requested.append(url)
            if "currentPage" in url:
                raise AssertionError(url)
            if "222_zpid" in url:
                return zillow_agents.FetchResult(url=url, html=second, status=200)
            if "homedetails" in url:
                return zillow_agents.FetchResult(url=url, html=detail, status=200)
            return zillow_agents.FetchResult(url=url, html=search, status=200)

        with tempfile.TemporaryDirectory() as tmp:
            collected, checkpoints = self._run(
                fetch,
                tmp,
                {"zip_codes": ["08002", "08057"], "max_listings": 1, "max_agents": 50, "enrich": False},
            )
            self.assertEqual(collected["summary"]["listings_found"], 1)
            self.assertEqual(collected["summary"]["agents_found"], 1)
            self.assertEqual(collected["summary"]["blocked_zips"], [])
            self.assertFalse(any("08057" in url for url in requested))
            self.assertEqual(sum("homedetails" in url for url in requested), 1)
            row = collected["rows"][0]
            self.assertEqual(row["agent_name"], "Jane Smith")
            self.assertEqual(row["brokerage"], "Compass")
            self.assertEqual(row["phone"], "(856) 555-0101")
            self.assertEqual(row["email"], "jane.smith@compass.com")
            self.assertTrue(row["listing_addresses"])
            agents_csv = collected["result"]["paths"]["agents_csv"]
            self.assertTrue(str(agents_csv).endswith("zillow_agents_2026-10-24_08002_08057.csv"))
            self.assertTrue(agents_csv.is_file())
            self.assertTrue(collected["result"]["paths"]["listings_json"].is_file())
            self.assertTrue(checkpoints)
            self.assertIn("08002", checkpoints[-1]["areas"])

        requested.clear()
        with tempfile.TemporaryDirectory() as tmp:
            both, _ = self._run(
                fetch,
                tmp,
                {"zip_codes": ["08002"], "max_listings": 10, "max_agents": 1, "enrich": False},
            )
            self.assertFalse(any("currentPage" in url for url in requested))
            self.assertEqual(both["summary"]["agents_found"], 1)
            self.assertEqual(len(both["rows"]), 1)
            self.assertGreaterEqual(both["summary"]["listings_found"], 1)
            names = {row["agent_name"] for row in both["rows"]}
            self.assertEqual(names, {"Jane Smith"})

    def test_block_records_the_zip_and_moves_on(self):
        block = _read("block_page.html")
        search = _read("search_done.html")
        detail = _read("listing_detail.html")
        requested = []

        def fetch(url):
            requested.append(url)
            if "08002" in url and "homedetails" not in url:
                return zillow_agents.FetchResult(url=url, html=block, status=200)
            if "homedetails" in url:
                return zillow_agents.FetchResult(url=url, html=detail, status=200)
            return zillow_agents.FetchResult(url=url, html=search, status=200)

        with tempfile.TemporaryDirectory() as tmp:
            collected, _checkpoints = self._run(
                fetch,
                tmp,
                {"zip_codes": ["08002", "08057"], "max_listings": 5, "max_agents": 5, "enrich": False},
            )
            self.assertEqual(collected["summary"]["blocked_zips"], ["08002"])
            self.assertEqual(collected["summary"]["agents_found"], 1)
            self.assertTrue(any("08057" in url for url in requested))
            self.assertEqual(zillow_agents.BLOCKED_RESOURCE_TYPES, {"image", "media", "font"})

    def test_browser_launch_receives_proxy_only_when_set(self):
        proxy = {"server": "http://proxy.example:8000", "username": "u", "password": "p"}
        browser = zillow_agents.ZillowBrowser(proxy=proxy, headless=True)
        bare = zillow_agents.ZillowBrowser(headless=True)
        started = _Playwright()
        with patch("playwright.sync_api.sync_playwright", return_value=started):
            browser._slot()
            self.assertEqual(started.chromium.kwargs["proxy"], proxy)
            self.assertTrue(started.chromium.kwargs["headless"])
            second = _Playwright()
            with patch("playwright.sync_api.sync_playwright", return_value=second):
                bare._slot()
            self.assertNotIn("proxy", second.chromium.kwargs)
        browser.close()
        bare.close()


class TestRemoteDownload(unittest.TestCase):
    def test_start_writes_dated_files_from_the_dataset(self):
        client = _Client(
            run={
                "status": "SUCCEEDED",
                "defaultDatasetId": "ds1",
                "defaultKeyValueStoreId": "kv1",
            },
            items=[{
                "agent_name": "Jane Smith",
                "brokerage": "Compass",
                "phone": "(856) 555-0101",
                "email": "jane.smith@compass.com",
                "license": "NJ-12345",
                "profile_url": "https://www.zillow.com/profile/jane-smith",
                "enrichment_source": "",
                "enrichment_source_url": "",
                "confidence": "",
                "listing_addresses": ["1 Main St, Cherry Hill, NJ 08002"],
            }],
            records={
                "LISTINGS": {
                    "run": {"listings_found": 1},
                    "listings": [{
                        "listing_id": "111",
                        "address": "1 Main St, Cherry Hill, NJ 08002",
                        "price": 325000,
                        "status": "FOR_SALE",
                        "beds": 3,
                        "baths": 2,
                        "sqft": 1500,
                        "url": "https://www.zillow.com/homedetails/1-Main-St/111_zpid/",
                        "area": "08002",
                    }],
                },
                "SUMMARY": {
                    "listings_found": 1,
                    "agents_found": 1,
                    "agents_enriched": 0,
                    "blocked_zips": [],
                },
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            report = remote.start_and_download(
                client,
                "user~zillow-agents",
                remote.build_actor_input(["08002"], 100, 50),
                tmp,
                run_date="2026-10-24",
            )
            self.assertEqual(client.run_input["zip_codes"], ["08002"])
            self.assertEqual(client.run_input["max_listings"], 100)
            self.assertEqual(report["agents"], 1)
            self.assertEqual(report["summary"]["blocked_zips"], [])
            csv_path = Path(report["paths"]["agents_csv"])
            self.assertTrue(str(csv_path).endswith("zillow_agents_2026-10-24_08002.csv"))
            self.assertIn("Jane Smith", csv_path.read_text(encoding="utf-8"))
            listings = json.loads(Path(report["paths"]["listings_json"]).read_text(encoding="utf-8"))
            self.assertEqual(listings["listings"][0]["listing_id"], "111")

    def test_actor_id_uses_token_env_not_the_store_catalog(self):
        self.assertEqual(
            remote.actor_id_from_env({"ZILLOW_ACTOR_ID": "someone~zillow-agents"}),
            "someone~zillow-agents",
        )
        self.assertEqual(
            remote.actor_id_from_env({"APIFY_USER_ID": "abc123"}),
            "abc123~zillow-agents",
        )
        with self.assertRaises(RuntimeError):
            remote.actor_id_from_env({})


if __name__ == "__main__":
    unittest.main()
