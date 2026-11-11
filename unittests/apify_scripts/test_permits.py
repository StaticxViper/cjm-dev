"""
Unit tests for scripts/apify-scripts/permits.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_permits

Fixtures only. These tests do not call a live permit portal.
"""
import asyncio
import importlib
import json
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlparse

_REPO = Path(__file__).resolve().parents[2]
_ACTOR = _REPO / "scripts" / "apify-scripts" / "permits"
_SRC = _ACTOR / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "permits"
_ACTOR_MODULES = ("spend", "runtime", "sources", "state", "fetch", "mapping", "main")

VERIFIED_IDS = (
    "chicago_building_permits",
    "seattle_building_permits",
    "austin_issued_permits",
    "los_angeles_building_permits",
)
NEW_IDS = (
    "nyc_dob_now_permits",
    "new_orleans_permits",
    "cincinnati_building_permits",
)
ALL_VERIFIED_IDS = VERIFIED_IDS + NEW_IDS
OWNER_SOURCES = ("nyc_dob_now_permits", "new_orleans_permits")


class FakeStore:
    def __init__(self, data):
        self.data = data

    async def get_value(self, key):
        return self.data.get(key)

    async def set_value(self, key, value):
        self.data[key] = json.loads(json.dumps(value))


class FakeActor:
    """Stand-in for apify.Actor with the calls permits main() makes."""

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
state_mod = _actor["state"]
main_mod = _actor["main"]


def _text(name):
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _json_text(name):
    return _text(name)


class Scripted:
    def __init__(self, pages, challenge_substrings=None, disallow_netloc=""):
        self.pages = pages
        self.challenge_substrings = challenge_substrings or []
        self.disallow_netloc = disallow_netloc
        self.direct_urls = []
        self.proxy_calls = []
        self.solved = []

    def direct(self, url):
        self.direct_urls.append(url)
        parsed = urlparse(url)
        if parsed.path != "/robots.txt" and any(part in url for part in self.challenge_substrings):
            return {
                "status": 403,
                "text": _text("captcha.html"),
                "error": None,
                "content_type": "text/html",
            }
        body = self._body(url)
        if body is None:
            return {"status": 404, "text": "missing", "error": None, "content_type": "text/plain"}
        kind = "text/plain"
        stripped = body.lstrip()
        if stripped.startswith("[") or stripped.startswith("{"):
            kind = "application/json"
        if "<html" in body.lower() or "<table" in body.lower():
            kind = "text/html"
        return {"status": 200, "text": body, "error": None, "content_type": kind}

    def proxy(self, url, token=None):
        self.proxy_calls.append((url, token))
        if token:
            body = self._body(url) or "[]"
            kind = "application/json" if body.lstrip().startswith(("[", "{")) else "text/html"
            return {"status": 200, "text": body, "error": None, "content_type": kind}
        return {
            "status": 403,
            "text": _text("captcha.html"),
            "error": None,
            "content_type": "text/html",
        }

    def solver(self, url, html):
        self.solved.append(url)
        return "token-1" if "g-recaptcha" in (html or "") else None

    def _body(self, url):
        parsed = urlparse(url)
        if parsed.path == "/robots.txt":
            if self.disallow_netloc and self.disallow_netloc in parsed.netloc:
                return _text("robots_disallow.txt")
            return _text("robots_allow.txt")
        for key, body in self.pages.items():
            if key in url:
                return body
        return None


def _run(scripted, entries=None, seen_state=None, **actor_input):
    config = mapping.actor_input_to_config(actor_input, today=date(2026, 10, 26))
    sleeps = []
    fetch = fetch_mod.build_fetch(
        config,
        scripted.direct,
        proxy=scripted.proxy,
        solver=scripted.solver,
        sleep=lambda seconds: sleeps.append(seconds),
    )
    rows, summary = mapping.scrape(config, fetch, entries=entries, seen_state=seen_state)
    return rows, summary, scripted, config, sleeps


def _run_main(actor_input, scripted=None, stores=None, limit_after=None):
    scripted = scripted or Scripted(_pages())
    actor = FakeActor(actor_input, stores=stores, limit_after=limit_after)
    fake_apify = types.ModuleType("apify")
    fake_apify.Actor = actor

    def live(config, proxy_url_fn=None):
        del proxy_url_fn
        return fetch_mod.build_fetch(
            config,
            scripted.direct,
            proxy=scripted.proxy,
            solver=scripted.solver,
            sleep=lambda _seconds: None,
        )

    with mock.patch.dict(sys.modules, {"apify": fake_apify}), \
            mock.patch.object(main_mod, "Actor", actor), \
            mock.patch.object(main_mod, "make_live_fetch", live):
        asyncio.run(main_mod.main())
    return actor, scripted


def _found(rows):
    return [row for row in rows if row.get("sourceStatus") == "found"]


def _base_input(**extra):
    payload = {
        "dateFrom": "2026-10-01",
        "dateTo": "2026-10-31",
        "maxItems": 50,
        "maxRequests": 40,
        "delaySeconds": 2,
        "maxSpendUsd": 5,
        "maxProxyCostUsd": 0.5,
    }
    payload.update(extra)
    return payload


def _pages():
    return {
        "ydr8-5enu": _json_text("chicago.json"),
        "76t5-zqzr": _json_text("seattle.json"),
        "3syk-w9eu": _json_text("austin.json"),
        "pi9x-tg5x": _json_text("los_angeles.json"),
        "rbx6-tga4": _json_text("nyc.json"),
        "rcm3-fn58": _json_text("new_orleans.json"),
        "uhjb-xac9": _json_text("cincinnati.json"),
    }


def _html_entry():
    return {
        "id": "sample_html_permits",
        "name": "Sample HTML permits",
        "adapter": "http_table",
        "enabled": True,
        "status": "verified",
        "access": "public",
        "url": "https://permits.example.gov/issued",
        "endpoint": "https://permits.example.gov/issued",
        "table": {
            "row_selector": "table tr",
            "columns": {
                "permit_id": "Permit",
                "issued_date": "Issued",
                "type": "Type",
                "description": "Description",
                "value_usd": "Value",
                "address": "Address",
                "city": "City",
                "state": "State",
                "zip": "Zip",
                "contractor_name": "Contractor",
                "contractor_license": "License",
                "owner_name": "Owner",
            },
        },
        "constants": {"state": "OH"},
        "rate_limit": {"page_size": 50, "max_requests_per_run": 1},
    }


def _arcgis_entry():
    return {
        "id": "sample_arcgis_permits",
        "name": "Sample ArcGIS permits",
        "adapter": "open_data",
        "enabled": True,
        "status": "verified",
        "access": "public",
        "url": "https://services.example.gov/arcgis/rest/services/Permits/FeatureServer/0/query",
        "endpoint": "https://services.example.gov/arcgis/rest/services/Permits/FeatureServer/0/query",
        "record_url": "https://services.example.gov/permits/{id}",
        "query": {
            "style": "arcgis",
            "date_column": "ISSUED",
            "extra_where": "",
            "text_columns": ["DESCRIPTION", "PERMITTYPE"],
        },
        "field_map": {
            "permit_id": "PERMITID",
            "issued_date": "ISSUED",
            "type": "PERMITTYPE",
            "description": "DESCRIPTION",
            "value_usd": "VALUE",
            "address": "ADDRESS",
            "zip": "ZIP",
        },
        "constants": {"city": "Sample", "state": "NY"},
        "rate_limit": {"page_size": 25, "max_requests_per_run": 1},
    }


class TestInput(unittest.TestCase):
    def test_bounds_and_defaults(self):
        config = mapping.actor_input_to_config({
            "maxItems": 999,
            "delaySeconds": 0,
            "maxRequests": 0,
            "maxSpendUsd": 1000,
            "maxProxyCostUsd": 50,
            "minValue": -5,
        }, today=date(2026, 10, 26))
        self.assertEqual(config["date_from"], date(2026, 9, 26))
        self.assertEqual(config["date_to"], date(2026, 10, 26))
        self.assertEqual(config["max_items"], 200)
        self.assertEqual(config["max_requests"], 1)
        self.assertEqual(config["delay_seconds"], 1.0)
        self.assertEqual(config["min_value"], 0.0)
        self.assertEqual(config["max_spend_usd"], 100.0)
        self.assertEqual(config["max_proxy_usd"], 20.0)
        self.assertFalse(config["allow_captcha"])
        self.assertTrue(config["headless"])
        self.assertFalse(config["error"])
        self.assertFalse(config["new_since_last_run"])
        self.assertEqual(config["state_store"], "permits-state")

    def test_omitted_proxy_budget_is_zero(self):
        config = mapping.actor_input_to_config({}, today=date(2026, 10, 26))
        self.assertEqual(config["max_proxy_usd"], 0.0)
        config = mapping.actor_input_to_config({"maxProxyCostUsd": 0.3}, today=date(2026, 10, 26))
        self.assertEqual(config["max_proxy_usd"], 0.3)

    def test_new_since_last_run_and_store_name(self):
        config = mapping.actor_input_to_config(
            {"newSinceLastRun": True, "stateStoreName": "  roofers-feed "},
            today=date(2026, 10, 26),
        )
        self.assertTrue(config["new_since_last_run"])
        self.assertEqual(config["state_store"], "roofers-feed")

    def test_proxy_cap_cannot_exceed_spend_cap(self):
        config = mapping.actor_input_to_config({
            "maxSpendUsd": 0.2,
            "maxProxyCostUsd": 5,
        })
        self.assertEqual(config["max_proxy_usd"], 0.2)

    def test_rejects_a_bad_date_window(self):
        self.assertIn("dateFrom", mapping.actor_input_to_config({"dateFrom": "yesterday"})["error"])
        self.assertIn("dateTo", mapping.actor_input_to_config({"dateTo": "10/26/2026"})["error"])
        self.assertIn(
            "on or before",
            mapping.actor_input_to_config({"dateFrom": "2026-11-01", "dateTo": "2026-10-01"})["error"],
        )


class TestCatalog(unittest.TestCase):
    def test_seven_verified_socrata_sources(self):
        entries = sources.load_entries()
        verified = sources.verified_entries(entries)
        self.assertEqual([entry["id"] for entry in verified], list(ALL_VERIFIED_IDS))
        self.assertGreaterEqual(len({tuple(entry["coverage"]["cities"]) for entry in verified}), 5)
        for entry in verified:
            self.assertEqual(entry["adapter"], "open_data")
            self.assertEqual(entry["status"], "verified")
            self.assertTrue(entry["enabled"])
            self.assertIn("/resource/", entry["url"])
            self.assertTrue(entry["query"]["date_column"])
            self.assertIn("permit_id", entry["field_map"])
            self.assertIn("issued_date", entry["field_map"])
            self.assertTrue(entry["terms_checked"]["date"])
            self.assertTrue(entry["notes"].startswith("Verified "))
            if entry["id"] in OWNER_SOURCES:
                self.assertIn("owner_name", entry["field_map"])
            else:
                self.assertNotIn("owner_name", entry.get("field_map") or {})
        for entry in verified:
            if entry["id"] in NEW_IDS:
                self.assertEqual(entry["terms_checked"]["date"], "2026-11-11")

    def test_input_schema_lists_every_verified_source(self):
        schema = json.loads((_ACTOR / ".actor" / "input_schema.json").read_text(encoding="utf-8"))
        items = schema["properties"]["sources"]["items"]
        self.assertEqual(items["enum"], list(ALL_VERIFIED_IDS))
        self.assertEqual(len(items["enumTitles"]), len(items["enum"]))
        types_enum = schema["properties"]["permitTypes"]["items"]["enum"]
        self.assertEqual(sorted(types_enum), sorted(mapping.TYPE_KEYWORDS))
        self.assertFalse(schema["properties"]["newSinceLastRun"]["default"])
        self.assertEqual(schema["properties"]["maxProxyCostUsd"]["default"], 0)


class TestPricing(unittest.TestCase):
    def test_permit_tiers(self):
        data = json.loads((_ACTOR / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        self.assertEqual(list(data["actorChargeEvents"]), ["permit"])
        tiers = data["actorChargeEvents"]["permit"]["eventTieredPricingUsd"]
        prices = {name: tier["tieredEventPriceUsd"] for name, tier in tiers.items()}
        self.assertEqual(prices, {
            "FREE": 0.012,
            "BRONZE": 0.010,
            "SILVER": 0.009,
            "GOLD": 0.008,
            "PLATINUM": 0.008,
            "DIAMOND": 0.008,
        })
        self.assertTrue(data["actorChargeEvents"]["permit"]["isPrimaryEvent"])


class TestFixtures(unittest.TestCase):
    def test_four_sources_return_rows_and_log_summary(self):
        scripted = Scripted(_pages())
        with self.assertLogs("apify", level="CRITICAL") as caught:
            rows, summary, scripted, _config, _sleeps = _run(
                scripted,
                sources=list(VERIFIED_IDS),
                **_base_input(),
            )
        found = _found(rows)
        by_source = {}
        for row in found:
            by_source.setdefault(row["source"], []).append(row)
        self.assertEqual(set(by_source), set(VERIFIED_IDS))
        self.assertEqual(len(found), 11)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["found"], 11)
        self.assertEqual(summary["billedPermits"], 11)
        self.assertEqual(summary["mergedDuplicates"], 2)
        self.assertEqual(summary["proxyCharges"], 0)
        self.assertEqual(summary["captchaCharges"], 0)
        self.assertEqual(summary["spendUsd"], 0.55)
        self.assertEqual(scripted.proxy_calls, [])
        self.assertEqual(len(summary["sources"]), 4)
        for report in summary["sources"]:
            self.assertEqual(report["status"], "ok")
            self.assertGreater(report["kept"], 0)
            self.assertTrue(any(f"Permits source {report['id']}:" in line for line in caught.output))
        self.assertTrue(any("Permits SUMMARY:" in line for line in caught.output))

        chicago = {row["permit_id"]: row for row in by_source["chicago_building_permits"]}
        roof = chicago["B-EXAMPLE-1"]
        self.assertEqual(roof["issued_date"], "2026-10-12")
        self.assertEqual(roof["value_usd"], 18500.0)
        self.assertEqual(roof["address"], "100 N EXAMPLE AVE")
        self.assertEqual(roof["city"], "Chicago")
        self.assertEqual(roof["state"], "IL")
        self.assertEqual(roof["zip"], "")
        self.assertEqual(roof["lat"], 41.5)
        self.assertEqual(roof["lng"], -87.5)
        self.assertEqual(roof["contractor_name"], "Example Roofing Co")
        self.assertEqual(roof["owner_name"], "Example Owner")
        self.assertIn("permit_=B-EXAMPLE-1", roof["source_url"])
        self.assertTrue(mapping.billable_row(roof))
        self.assertEqual(chicago["B-EXAMPLE-2"]["owner_name"], "")
        self.assertEqual(chicago["B-EXAMPLE-2"]["contractor_name"], "Example Siding Co")

        seattle = by_source["seattle_building_permits"][0]
        self.assertEqual(seattle["owner_name"], "")
        self.assertEqual(seattle["contractor_name"], "Example Seattle Roofing")
        self.assertEqual(seattle["zip"], "98101")
        self.assertEqual(seattle["source_url"], "https://services.seattle.gov/portal/example/7000001-CN")

        austin = next(row for row in by_source["austin_issued_permits"] if row["permit_id"] == "2026-EXAMPLE BP")
        self.assertEqual(austin["owner_name"], "")
        self.assertEqual(austin["contractor_name"], "Example Austin Roofing")
        self.assertEqual(austin["source_url"], "https://abc.austintexas.gov/web/permit/example")

        la_row = next(row for row in by_source["los_angeles_building_permits"] if row["permit_id"] == "26000-EXAMPLE")
        self.assertEqual(la_row["owner_name"], "")
        self.assertEqual(la_row["contractor_name"], "")
        self.assertEqual(la_row["contractor_license"], "")
        self.assertEqual(la_row["city"], "Los Angeles")
        self.assertEqual(la_row["state"], "CA")

    def test_dedupe_max_items_and_filters(self):
        scripted = Scripted(_pages())
        rows, summary, scripted, _config, _sleeps = _run(
            scripted,
            sources=["chicago_building_permits"],
            **_base_input(),
        )
        ids = [row["permit_id"] for row in _found(rows)]
        self.assertEqual(ids.count("B-EXAMPLE-1"), 1)
        self.assertNotIn("B-EXAMPLE-3", ids)
        self.assertEqual(summary["mergedDuplicates"], 1)
        self.assertEqual(len(ids), 5)

        rows, summary, scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits", "seattle_building_permits"],
            **_base_input(maxItems=1),
        )
        found = _found(rows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["permit_id"], "B-EXAMPLE-1")
        self.assertTrue(summary["truncated"])
        self.assertEqual(summary["billedPermits"], 1)
        self.assertLessEqual(summary["billedPermits"], 1)
        self.assertFalse(any("76t5-zqzr" in url for url in scripted.direct_urls))

        rows, summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits"],
            **_base_input(permitTypes=["roof"]),
        )
        self.assertEqual([row["permit_id"] for row in _found(rows)], ["B-EXAMPLE-1"])

        rows, _summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits"],
            **_base_input(permitTypes=["deck"]),
        )
        self.assertEqual([row["permit_id"] for row in _found(rows)], ["B-EXAMPLE-6"])

        rows, _summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits"],
            **_base_input(minValue=10000),
        )
        self.assertEqual(
            sorted(row["permit_id"] for row in _found(rows)),
            ["B-EXAMPLE-1", "B-EXAMPLE-4"],
        )

    def test_spend_cap_does_not_bill_extra_permits(self):
        rows, summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits"],
            **_base_input(maxSpendUsd=0.05, maxProxyCostUsd=0),
        )
        self.assertEqual(summary["found"], 5)
        self.assertEqual(summary["billedPermits"], 1)
        self.assertTrue(summary["chargeCapped"])
        self.assertEqual(summary["spendUsd"], 0.05)
        self.assertLessEqual(summary["billedPermits"], summary["found"])

        rows, summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits"],
            **_base_input(maxSpendUsd=0, maxProxyCostUsd=0),
        )
        self.assertEqual(len(_found(rows)), 5)
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(summary["spendUsd"], 0)
        self.assertTrue(summary["chargeCapped"])
        self.assertTrue(all(mapping.billable_row(row) for row in _found(rows)))

    def test_empty_window_is_not_billed(self):
        rows, summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits"],
            **_base_input(dateFrom="2026-12-01", dateTo="2026-12-31"),
        )
        self.assertEqual(_found(rows), [])
        self.assertEqual(rows[0]["sourceStatus"], "not_found")
        self.assertEqual(summary["status"], "not_found")
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(summary["spendUsd"], 0)
        self.assertFalse(mapping.billable_row(rows[0]))

    def test_later_requests_wait(self):
        _rows, _summary, scripted, _config, sleeps = _run(
            Scripted(_pages()),
            sources=["seattle_building_permits"],
            **_base_input(delaySeconds=2),
        )
        self.assertGreaterEqual(len(scripted.direct_urls), 2)
        self.assertGreaterEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], 2)

    def test_query_sends_the_date_window(self):
        _rows, _summary, scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits"],
            **_base_input(permitTypes=["roof"]),
        )
        data_urls = [unquote(url) for url in scripted.direct_urls if "ydr8-5enu" in url]
        self.assertEqual(len(data_urls), 1)
        self.assertIn("$limit=50", data_urls[0])
        self.assertIn("issue_date >= '2026-10-01T00:00:00.000'", data_urls[0])
        self.assertIn("issue_date <= '2026-10-31T23:59:59.999'", data_urls[0])
        self.assertIn("upper(work_description) like '%ROOF%'", data_urls[0])


class TestBlocks(unittest.TestCase):
    def test_block_with_captcha_off_stops_without_a_permit_charge(self):
        scripted = Scripted(_pages(), challenge_substrings=["ydr8-5enu"])
        rows, summary, scripted, _config, _sleeps = _run(
            scripted,
            sources=["chicago_building_permits", "seattle_building_permits"],
            **_base_input(allowCaptcha=False),
        )
        self.assertEqual(_found(rows), [])
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(summary["proxyCharges"], 1)
        self.assertEqual(summary["captchaCharges"], 0)
        self.assertEqual(len(scripted.proxy_calls), 1)
        self.assertEqual(scripted.solved, [])
        self.assertFalse(any("76t5-zqzr" in url for url in scripted.direct_urls))
        blocked = [row for row in rows if row.get("sourceStatus") == "blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertIn("CAPTCHA", blocked[0]["error"])
        self.assertFalse(mapping.billable_row(blocked[0]))

    def test_block_without_proxy_budget_does_not_retry(self):
        scripted = Scripted(_pages(), challenge_substrings=["ydr8-5enu"])
        rows, summary, scripted, _config, _sleeps = _run(
            scripted,
            sources=["chicago_building_permits"],
            **_base_input(maxProxyCostUsd=0, maxSpendUsd=5),
        )
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(summary["proxyCharges"], 0)
        self.assertEqual(scripted.proxy_calls, [])
        self.assertEqual(scripted.solved, [])
        self.assertIn("spend cap", rows[0]["error"])

    def test_captcha_solve_is_billed_only_when_a_token_returns(self):
        scripted = Scripted(_pages(), challenge_substrings=["ydr8-5enu"])
        rows, summary, scripted, _config, _sleeps = _run(
            scripted,
            sources=["chicago_building_permits"],
            **_base_input(allowCaptcha=True, maxSpendUsd=5),
        )
        self.assertEqual(summary["found"], 5)
        self.assertEqual(summary["proxyCharges"], 1)
        self.assertEqual(summary["captchaCharges"], 1)
        self.assertEqual(summary["billedPermits"], 5)
        self.assertEqual(len(scripted.solved), 1)
        self.assertTrue(scripted.proxy_calls[0][1] is None)
        self.assertEqual(scripted.proxy_calls[1][1], "token-1")
        self.assertTrue(all(mapping.billable_row(row) for row in _found(rows)))

    def test_robots_disallow_is_not_retried_through_a_proxy(self):
        scripted = Scripted(_pages(), disallow_netloc="data.cityofchicago.org")
        rows, summary, scripted, _config, _sleeps = _run(
            scripted,
            sources=["chicago_building_permits", "seattle_building_permits"],
            **_base_input(),
        )
        self.assertFalse(any("ydr8-5enu" in url for url in scripted.direct_urls))
        self.assertEqual(scripted.proxy_calls, [])
        self.assertEqual(summary["proxyCharges"], 0)
        self.assertEqual(summary["billedPermits"], 2)
        statuses = [row["sourceStatus"] for row in rows]
        self.assertIn("robots_disallowed", statuses)
        self.assertEqual(summary["found"], 2)
        self.assertTrue(any("76t5-zqzr" in url for url in scripted.direct_urls))

    def test_request_cap_stops_cleanly(self):
        scripted = Scripted(_pages())
        rows, summary, scripted, _config, _sleeps = _run(
            scripted,
            sources=["chicago_building_permits"],
            **_base_input(maxRequests=1),
        )
        self.assertEqual(_found(rows), [])
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(summary["status"], "error")
        self.assertIn("request_cap", rows[0]["error"])
        self.assertFalse(any("ydr8-5enu" in url for url in scripted.direct_urls))

    def test_unknown_source_is_an_error_row(self):
        scripted = Scripted(_pages())
        rows, summary, scripted, _config, _sleeps = _run(
            scripted,
            sources=["not-a-city"],
            **_base_input(),
        )
        self.assertEqual(scripted.direct_urls, [])
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(rows[0]["sourceStatus"], "error")
        self.assertIn("chicago_building_permits", rows[0]["error"])


class TestOtherAdapters(unittest.TestCase):
    def test_html_table_maps_a_published_owner(self):
        scripted = Scripted({"/issued": _text("table.html")})
        rows, summary, _scripted, _config, _sleeps = _run(
            scripted,
            entries=[_html_entry()],
            sources=["sample_html_permits"],
            **_base_input(permitTypes=["roof"]),
        )
        found = _found(rows)
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["permit_id"], "HT-1")
        self.assertEqual(row["value_usd"], 9500.0)
        self.assertEqual(row["contractor_name"], "Example Exterior Co")
        self.assertEqual(row["contractor_license"], "LIC-9")
        self.assertEqual(row["owner_name"], "Example Homeowner")
        self.assertEqual(row["state"], "OH")
        self.assertEqual(summary["billedPermits"], 1)
        self.assertEqual(summary["sources"][0]["status"], "ok")

    def test_arcgis_feature_uses_geometry(self):
        scripted = Scripted({"FeatureServer": _text("arcgis.json")})
        rows, summary, scripted, _config, _sleeps = _run(
            scripted,
            entries=[_arcgis_entry()],
            sources=["sample_arcgis_permits"],
            **_base_input(permitTypes=["roof"]),
        )
        found = _found(rows)
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["permit_id"], "AG-1")
        self.assertEqual(row["issued_date"], "2026-10-09")
        self.assertEqual(row["lat"], 40.7)
        self.assertEqual(row["lng"], -73.9)
        self.assertEqual(row["value_usd"], 11000.0)
        self.assertEqual(row["city"], "Sample")
        self.assertEqual(row["owner_name"], "")
        self.assertEqual(summary["billedPermits"], 1)
        data_urls = [unquote(url) for url in scripted.direct_urls if "FeatureServer" in url]
        self.assertEqual(len(data_urls), 1)
        self.assertIn("resultRecordCount=25", data_urls[0])
        self.assertIn("returnGeometry=true", data_urls[0])
        self.assertIn("DATE '2026-10-01'", data_urls[0])
        self.assertIn("DATE '2026-10-31'", data_urls[0])
        self.assertIn("UPPER(DESCRIPTION) like '%ROOF%'", data_urls[0])

    def test_arcgis_epoch_millisecond_dates(self):
        from datetime import datetime, timezone

        issued = int(datetime(2026, 10, 14, tzinfo=timezone.utc).timestamp() * 1000)
        old = int(datetime(2025, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
        payload = {"features": [
            {"attributes": {"PERMITID": "AG-EPOCH", "ISSUED": issued, "PERMITTYPE": "Roof", "DESCRIPTION": "Reroof"}},
            {"attributes": {"PERMITID": "AG-OLD", "ISSUED": old, "PERMITTYPE": "Roof", "DESCRIPTION": "Reroof"}},
        ]}
        rows, _summary, _scripted, _config, _sleeps = _run(
            Scripted({"FeatureServer": json.dumps(payload)}),
            entries=[_arcgis_entry()],
            sources=["sample_arcgis_permits"],
            **_base_input(),
        )
        found = _found(rows)
        self.assertEqual([row["permit_id"] for row in found], ["AG-EPOCH"])
        self.assertEqual(found[0]["issued_date"], "2026-10-14")


class TestNewSources(unittest.TestCase):
    def _rows(self, source_id, **extra):
        rows, summary, scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=[source_id],
            **_base_input(**extra),
        )
        return {row["permit_id"]: row for row in _found(rows)}, summary, scripted

    def test_nyc_dob_now_mapping_and_initial_permit_filter(self):
        rows, summary, scripted = self._rows("nyc_dob_now_permits")
        self.assertEqual(summary["found"], 3)
        roof = rows["Q00000001-I1-GC"]
        self.assertEqual(roof["issued_date"], "2026-10-14")
        self.assertEqual(roof["type"], "General Construction")
        self.assertEqual(roof["permit_category"], "roof")
        self.assertEqual(roof["permit_categories"], ["roof"])
        self.assertEqual(roof["value_usd"], 42000.0)
        self.assertEqual(roof["address"], "12-34 EXAMPLE AVENUE Queens")
        self.assertEqual(roof["city"], "New York")
        self.assertEqual(roof["state"], "NY")
        self.assertEqual(roof["zip"], "11101")
        self.assertEqual(roof["lat"], 40.745)
        self.assertEqual(roof["lng"], -73.935)
        self.assertEqual(roof["contractor_name"], "EXAMPLE NYC ROOFING CORP")
        self.assertEqual(roof["contractor_license"], "600001")
        self.assertEqual(roof["owner_name"], "EXAMPLE OWNER LLC")
        self.assertIn("work_permit=Q00000001-I1-GC", roof["source_url"])
        self.assertEqual(rows["B00000002-I1-SO"]["permit_category"], "solar")
        self.assertEqual(rows["M00000003-I1-SC"]["permit_category"], "other")
        self.assertEqual(rows["M00000003-I1-SC"]["value_usd"], 0.0)
        data_urls = [unquote(url) for url in scripted.direct_urls if "rbx6-tga4" in url]
        self.assertEqual(len(data_urls), 1)
        self.assertIn("filing_reason = 'Initial Permit'", data_urls[0])
        self.assertIn("issued_date >= '2026-10-01T00:00:00.000'", data_urls[0])
        self.assertIn("$order=issued_date DESC", data_urls[0])

    def test_new_orleans_mapping_uses_location_1(self):
        rows, summary, _scripted = self._rows("new_orleans_permits")
        self.assertEqual(summary["found"], 3)
        pool = rows["26-00001-POOL"]
        self.assertEqual(pool["issued_date"], "2026-10-16")
        self.assertEqual(pool["type"], "Swimming Pool")
        self.assertEqual(pool["permit_category"], "pool")
        self.assertEqual(pool["value_usd"], 53095.0)
        self.assertEqual(pool["address"], "100 Example St")
        self.assertEqual(pool["city"], "New Orleans")
        self.assertEqual(pool["state"], "LA")
        self.assertEqual(pool["zip"], "")
        self.assertEqual(pool["lat"], 29.9275)
        self.assertEqual(pool["lng"], -90.0778)
        self.assertEqual(pool["contractor_name"], "Example Pool Builders LLC")
        self.assertEqual(pool["owner_name"], "Example Homeowner")
        self.assertIn("numstring=26-00001-POOL", pool["source_url"])
        self.assertEqual(rows["26-00002-RNVS"]["permit_category"], "remodel")
        self.assertEqual(rows["26-00003-EVAC"]["permit_category"], "other")

    def test_cincinnati_mapping_strips_quotes(self):
        rows, summary, _scripted = self._rows("cincinnati_building_permits")
        self.assertEqual(summary["found"], 2)
        plumbing = rows["2026P00001"]
        self.assertEqual(plumbing["issued_date"], "2026-10-19")
        self.assertEqual(plumbing["type"], "Plumbing Permits - New")
        self.assertEqual(plumbing["permit_category"], "other")
        self.assertEqual(plumbing["value_usd"], 2500.0)
        self.assertEqual(plumbing["address"], "3200 EXAMPLE AV")
        self.assertEqual(plumbing["city"], "CINCINNATI")
        self.assertEqual(plumbing["state"], "OH")
        self.assertEqual(plumbing["zip"], "45207")
        self.assertIsNone(plumbing["lat"])
        self.assertEqual(plumbing["contractor_name"], "EXAMPLE PLUMBING INC")
        self.assertEqual(plumbing["owner_name"], "")
        self.assertEqual(plumbing["source_url"], "http://cagis.hamilton-co.org/opal/apd.aspx?QSPerm=2026P00001")
        self.assertEqual(rows["2026B00002"]["permit_category"], "remodel")

    def test_remodel_filter_across_new_sources(self):
        rows, _summary, scripted = self._rows("new_orleans_permits", permitTypes=["remodel"])
        self.assertEqual(list(rows), ["26-00002-RNVS"])
        data_url = next(unquote(url) for url in scripted.direct_urls if "rcm3-fn58" in url)
        self.assertIn("upper(description) like '%RENOVATION%'", data_url)


class TestCategories(unittest.TestCase):
    def test_permit_categories(self):
        cases = {
            "PERMIT - RENOVATION Roof Tear off and re-roof with architectural shingles": ["roof", "remodel"],
            "Addition/Alteration Replace roof shingles": ["roof", "remodel"],
            "PERMIT - NEW CONSTRUCTION Pool In-ground swimming pool": ["pool", "new_construction"],
            "New single family dwelling with rooftop solar panels": ["solar", "new_construction"],
            "Bldg-Alter/Repair Re-roof with Class A material": ["roof", "remodel"],
            "Kitchen remodel": ["remodel"],
            "Install vinyl siding": ["siding"],
            "Build a wood deck": ["deck"],
            "Install additional electrical outlets": ["other"],
            "Repair decker gate": ["other"],
            "Plumbing Permits - New": ["other"],
            "Carpool lane signage": ["other"],
            "": ["other"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(mapping.permit_categories(text), expected)

    def test_remodel_type_filter_uses_word_boundaries(self):
        self.assertTrue(mapping.type_matches("Room addition at rear", ["remodel"]))
        self.assertFalse(mapping.type_matches("Additional circuits", ["remodel"]))
        self.assertTrue(mapping.type_matches("Bathroom renovation", ["remodel"]))
        self.assertTrue(mapping.type_matches("Install vinyl siding", ["siding"]))
        self.assertTrue(mapping.type_matches("Build a wood deck", ["deck"]))

    def test_rows_carry_categories_and_status_rows_do_not(self):
        rows, _summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits"],
            **_base_input(),
        )
        by_id = {row["permit_id"]: row for row in _found(rows)}
        self.assertEqual(by_id["B-EXAMPLE-1"]["permit_category"], "roof")
        self.assertEqual(by_id["B-EXAMPLE-4"]["permit_category"], "pool")
        self.assertEqual(by_id["B-EXAMPLE-4"]["permit_categories"], ["pool", "new_construction"])
        blank = mapping._blank_row("blocked", "x", "2026-11-11T00:00:00+00:00")
        self.assertEqual(blank["permit_category"], "")
        self.assertEqual(blank["permit_categories"], [])


class TestFeedRules(unittest.TestCase):
    def test_new_since_last_run_skips_seen_before_max_items(self):
        seen = {state_mod.permit_key("chicago_building_permits", "B-EXAMPLE-1"): "2026-10-20T00:00:00+00:00"}
        rows, summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            seen_state=seen,
            sources=["chicago_building_permits"],
            **_base_input(newSinceLastRun=True, maxItems=2),
        )
        ids = [row["permit_id"] for row in _found(rows)]
        self.assertEqual(ids, ["B-EXAMPLE-2", "B-EXAMPLE-4"])
        self.assertEqual(summary["skippedSeen"], 1)
        self.assertEqual(summary["billedPermits"], 2)
        self.assertTrue(summary["truncated"])
        self.assertTrue(summary["newSinceLastRun"])
        self.assertEqual(summary["sources"][0]["skippedSeen"], 1)

        rows, summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            seen_state=seen,
            sources=["chicago_building_permits"],
            **_base_input(newSinceLastRun=False, maxItems=2),
        )
        self.assertEqual([row["permit_id"] for row in _found(rows)], ["B-EXAMPLE-1", "B-EXAMPLE-2"])
        self.assertEqual(summary["skippedSeen"], 0)

    def test_all_seen_is_not_found_and_not_billed(self):
        seen = {
            state_mod.permit_key("chicago_building_permits", permit_id): "2026-10-20T00:00:00+00:00"
            for permit_id in ("B-EXAMPLE-1", "B-EXAMPLE-2", "B-EXAMPLE-4", "B-EXAMPLE-5", "B-EXAMPLE-6")
        }
        rows, summary, _scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            seen_state=seen,
            sources=["chicago_building_permits"],
            **_base_input(newSinceLastRun=True),
        )
        self.assertEqual(_found(rows), [])
        self.assertEqual(rows[0]["sourceStatus"], "not_found")
        self.assertIn("No new permits", rows[0]["error"])
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(summary["skippedSeen"], 5)

    def test_max_items_is_strict_across_sources(self):
        rows, summary, scripted, _config, _sleeps = _run(
            Scripted(_pages()),
            sources=["chicago_building_permits", "seattle_building_permits", "nyc_dob_now_permits"],
            **_base_input(maxItems=6),
        )
        found = _found(rows)
        self.assertEqual(len(found), 6)
        self.assertEqual(summary["billedPermits"], 6)
        self.assertTrue(summary["truncated"])
        self.assertEqual({row["source"] for row in found}, {"chicago_building_permits", "seattle_building_permits"})
        self.assertFalse(any("rbx6-tga4" in url for url in scripted.direct_urls))

        for cap in (1, 3, 10):
            with self.subTest(maxItems=cap):
                rows, summary, _scripted, _config, _sleeps = _run(
                    Scripted(_pages()),
                    sources=list(ALL_VERIFIED_IDS),
                    **_base_input(maxItems=cap),
                )
                self.assertEqual(len(_found(rows)), cap)
                self.assertLessEqual(summary["billedPermits"], cap)

    def test_dedupe_key_is_source_and_permit_id(self):
        first = _arcgis_entry()
        second = dict(_arcgis_entry(), id="sample_arcgis_permits_two")
        rows, summary, _scripted, _config, _sleeps = _run(
            Scripted({"FeatureServer": _text("arcgis.json")}),
            entries=[first, second],
            sources=["sample_arcgis_permits", "sample_arcgis_permits_two"],
            **_base_input(),
        )
        found = _found(rows)
        self.assertEqual([(row["source"], row["permit_id"]) for row in found], [
            ("sample_arcgis_permits", "AG-1"),
            ("sample_arcgis_permits_two", "AG-1"),
        ])
        self.assertEqual(summary["mergedDuplicates"], 0)

    def test_default_block_pushes_blocked_row_with_no_proxy_or_charge(self):
        scripted = Scripted(_pages(), challenge_substrings=["ydr8-5enu"])
        actor_input = {
            "sources": ["chicago_building_permits", "seattle_building_permits"],
            "dateFrom": "2026-10-01",
            "dateTo": "2026-10-31",
        }
        rows, summary, scripted, config, _sleeps = _run(scripted, **actor_input)
        self.assertEqual(config["max_proxy_usd"], 0.0)
        self.assertEqual(scripted.proxy_calls, [])
        self.assertEqual(scripted.solved, [])
        self.assertEqual(_found(rows), [])
        self.assertEqual([row["sourceStatus"] for row in rows], ["blocked"])
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(summary["proxyCharges"], 0)
        self.assertEqual(summary["captchaCharges"], 0)
        self.assertFalse(any("76t5-zqzr" in url for url in scripted.direct_urls))


class TestState(unittest.TestCase):
    def test_round_trip_and_merge(self):
        self.assertEqual(state_mod.load_state(None), {})
        self.assertEqual(state_mod.load_state({"permits": "bad"}), {})
        merged = state_mod.merge_state({"a:1": "2026-10-01"}, {"a:1": "2026-11-01", "b:2": "2026-11-01"})
        self.assertEqual(merged, {"a:1": "2026-10-01", "b:2": "2026-11-01"})
        dumped = state_mod.dump_state(merged, "2026-11-11T00:00:00+00:00")
        self.assertEqual(state_mod.load_state(json.loads(json.dumps(dumped))), merged)
        capped = state_mod.merge_state({"a:1": "2026-01-01"}, {"b:2": "2026-02-01"}, max_keys=1)
        self.assertEqual(capped, {"b:2": "2026-02-01"})


class TestMain(unittest.TestCase):
    def _input(self, **extra):
        payload = {
            "sources": ["chicago_building_permits"],
            "dateFrom": "2026-10-01",
            "dateTo": "2026-10-31",
            "maxItems": 2,
            "delaySeconds": 1,
            "maxSpendUsd": 5,
            "newSinceLastRun": True,
        }
        payload.update(extra)
        return payload

    def test_new_since_last_run_persists_charged_permits_between_runs(self):
        stores = {}
        actor, _scripted = _run_main(self._input(), stores=stores)
        pushed = [row["permit_id"] for row in actor.pushed if row["sourceStatus"] == "found"]
        self.assertEqual(pushed, ["B-EXAMPLE-1", "B-EXAMPLE-2"])
        self.assertEqual(actor.charges, ["permit", "permit"])
        self.assertEqual(actor.opened, ["permits-state"])
        saved = stores["permits-state"]["SEEN"]
        self.assertEqual(sorted(saved["permits"]), [
            "chicago_building_permits:B-EXAMPLE-1",
            "chicago_building_permits:B-EXAMPLE-2",
        ])
        self.assertEqual(actor.values["SUMMARY"]["stateKeys"], 2)

        actor, _scripted = _run_main(self._input(), stores=stores)
        pushed = [row["permit_id"] for row in actor.pushed if row["sourceStatus"] == "found"]
        self.assertEqual(pushed, ["B-EXAMPLE-4", "B-EXAMPLE-5"])
        self.assertEqual(actor.charges, ["permit", "permit"])
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["skippedSeen"], 2)
        self.assertEqual(summary["billedPermits"], 2)
        self.assertEqual(summary["stateKeys"], 4)
        self.assertEqual(len(stores["permits-state"]["SEEN"]["permits"]), 4)

    def test_uncharged_rows_are_not_recorded(self):
        stores = {}
        actor, _scripted = _run_main(self._input(maxItems=10, maxSpendUsd=0.05), stores=stores)
        found = [row for row in actor.pushed if row["sourceStatus"] == "found"]
        self.assertEqual(len(found), 5)
        self.assertEqual(actor.charges, ["permit"])
        self.assertEqual(list(stores["permits-state"]["SEEN"]["permits"]), ["chicago_building_permits:B-EXAMPLE-1"])
        self.assertTrue(actor.values["SUMMARY"]["chargeCapped"])

    def test_platform_charge_limit_stops_billing(self):
        stores = {}
        actor, _scripted = _run_main(self._input(maxItems=10), stores=stores, limit_after=2)
        self.assertEqual(actor.charges, ["permit", "permit"])
        self.assertEqual(len(stores["permits-state"]["SEEN"]["permits"]), 2)

    def test_blocked_run_exits_cleanly_without_charges(self):
        stores = {}
        scripted = Scripted(_pages(), challenge_substrings=["ydr8-5enu"])
        actor, scripted = _run_main(self._input(), scripted=scripted, stores=stores)
        self.assertEqual(actor.charges, [])
        self.assertEqual([row["sourceStatus"] for row in actor.pushed], ["blocked"])
        self.assertEqual(scripted.proxy_calls, [])
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["billedPermits"], 0)
        self.assertEqual(summary["proxyCharges"], 0)
        self.assertNotIn("SEEN", stores["permits-state"])


if __name__ == "__main__":
    unittest.main()
