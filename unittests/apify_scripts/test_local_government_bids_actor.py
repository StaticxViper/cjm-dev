"""
Unit tests for scripts/apify-scripts/local-government-bids.

Run from repo root:
    python -m pytest unittests/apify_scripts/test_local_government_bids_actor.py -q

Fixtures only. The open-data fetch is scripted and ``apify.Actor`` is a
stand-in, so these tests never call the city portals or Apify.
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
from urllib.parse import parse_qs, urlparse

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "scripts" / "apify-scripts" / "local-government-bids" / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "local_government_bids"
_ACTOR_MODULES = ("runtime", "spend", "state", "stream", "sources", "fetch", "mapping", "main")

NOW = "2026-11-16T18:00:00+00:00"
TODAY = date(2026, 11, 16)


class FakeStore:
    def __init__(self, bucket):
        self.bucket = bucket

    async def get_value(self, key):
        return self.bucket.get(key)

    async def set_value(self, key, value):
        self.bucket[key] = value


class FakeActor:
    def __init__(self, actor_input, limit_after=None, stores=None, store_error=None):
        self.input = actor_input
        self.pushed = []
        self.charges = []
        self.values = {}
        self.opened = []
        self.limit_after = limit_after
        self.stores = stores if stores is not None else {}
        self.store_error = store_error

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
        if self.store_error:
            raise self.store_error
        self.stores.setdefault(name, {})
        return FakeStore(self.stores[name])


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


def _load(name):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _config(**overrides):
    raw = {
        "sources": ["montgomery_solicitations"],
        "dateFrom": "2023-03-23",
        "dateTo": "2023-03-23",
        "maxItems": 5,
        "maxSpendUsd": 1,
        "appToken": "",
    }
    raw.update(overrides)
    config = mapping.actor_input_to_config(raw, today=TODAY)
    if "_page_size" in overrides:
        config["_page_size"] = overrides["_page_size"]
    if "_max_bytes" in overrides:
        config["_max_bytes"] = overrides["_max_bytes"]
    return config


class Scripted:
    def __init__(self, montgomery=None, los_angeles=None, robots=None, status=200):
        self.montgomery = _load("montgomery_page.json") if montgomery is None else montgomery
        self.los_angeles = _load("los_angeles_page.json") if los_angeles is None else los_angeles
        self.robots = "User-agent: *\nAllow: /\n" if robots is None else robots
        self.status = status
        self.calls = []

    def direct(self, request):
        url = request["url"]
        self.calls.append(url)
        if urlparse(url).path.endswith("/robots.txt"):
            if isinstance(self.robots, dict):
                return dict(self.robots)
            return {"status": 200, "text": self.robots, "error": None, "chunks": None}
        if self.status != 200:
            return {"status": self.status, "text": "blocked", "error": None, "chunks": None}
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if "$limit" not in query:
            raise AssertionError(url)
        host = parsed.netloc
        if "lacity" in host:
            rows = self.los_angeles
        elif "montgomery" in host:
            rows = self.montgomery
        else:
            rows = []
        limit = int(query["$limit"][0])
        offset = int(query.get("$offset", ["0"])[0])
        page = rows[offset:offset + limit]
        return {
            "status": 200,
            "chunks": self._page_chunks(page),
            "error": None,
            "content_type": "application/json",
        }

    def _page_chunks(self, page):
        yield b"["
        for index, row in enumerate(page):
            prefix = b"" if index == 0 else b","
            yield prefix + json.dumps(row).encode()
        yield b"]"


def _run(scripted, config, seen=None):
    fetch = fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _seconds: None)
    return mapping.scrape(config, fetch, seen=seen, now=NOW)


def _data_calls(scripted):
    return [url for url in scripted.calls if not url.endswith("/robots.txt")]


def _bids(rows):
    return [row for row in rows if row.get("decision") == "opportunity"]


def _run_main(actor_input, scripted=None, **actor_kwargs):
    scripted = scripted or Scripted()
    actor = FakeActor(actor_input, **actor_kwargs)
    fake_apify = types.ModuleType("apify")
    fake_apify.Actor = actor

    def live(config):
        fetch = fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _seconds: None)
        fetch.close = lambda: None
        return fetch

    with mock.patch.dict(sys.modules, {"apify": fake_apify}), \
            mock.patch.object(main_mod, "Actor", actor), \
            mock.patch.object(main_mod, "make_live_fetch", live):
        asyncio.run(main_mod.main())
    return actor, scripted


class TestInput(unittest.TestCase):
    def test_defaults_are_one_source_and_fourteen_days(self):
        config = mapping.actor_input_to_config({}, today=TODAY)
        self.assertEqual(config["sources"], ["montgomery_solicitations"])
        self.assertEqual(config["max_items"], 25)
        self.assertEqual(config["max_spend_usd"], 0.50)
        self.assertEqual(config["delay_seconds"], 1)
        self.assertFalse(config["new_since_last_run"])
        self.assertEqual(config["state_store"], "local-government-bids-state")
        self.assertEqual(config["date_from"], "2026-11-03")
        self.assertEqual(config["date_to"], "2026-11-16")
        self.assertEqual(config["state"], "")
        self.assertEqual(config["error"], "")

    def test_one_sided_date_is_an_error(self):
        config = mapping.actor_input_to_config({"dateFrom": "2023-03-23"}, today=TODAY)
        self.assertIn("both", config["error"])

    def test_page_url_is_bounded_and_drops_injection(self):
        config = _config(keywords=["PARKING'; DROP", "x"])
        self.assertEqual(config["keywords"], ["PARKING DROP"])
        feed = sources.VERIFIED["montgomery_solicitations"]
        url = sources.soda_url(
            feed["endpoint"],
            sources.where_clause(feed, "2023-03-23", "2023-03-23", config["keywords"]),
            100,
            0,
            feed["order"],
        )
        self.assertIn("%24limit=100", url)
        self.assertIn("PARKING+DROP", url)
        self.assertNotIn("'", url)
        self.assertNotIn("DROP TABLE", url.upper())
        self.assertNotIn("export.csv", url)
        with self.assertRaises(ValueError):
            sources.soda_url(feed["endpoint"].replace(".json", ".csv"), "1=1", 10, 0, "number")


class TestMapping(unittest.TestCase):
    def test_montgomery_fixture_maps_the_official_row(self):
        rows, summary = _run(Scripted(), _config())
        bids = _bids(rows)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(len(bids), 2)
        first = bids[0]
        self.assertEqual(first["solicitationId"], "1134941")
        self.assertEqual(first["title"], "Parking Meters")
        self.assertEqual(first["agency"], "Department of Transportation")
        self.assertEqual(first["state"], "MD")
        self.assertEqual(first["city"], "")
        self.assertEqual(first["postedDate"], "2023-03-23")
        self.assertEqual(first["dueDate"], "2023-05-03")
        self.assertEqual(first["category"], "RFP")
        self.assertEqual(first["status"], "Closed")
        self.assertEqual(first["contactName"], "Javier Torres")
        self.assertEqual(first["contactEmail"], "")
        self.assertEqual(first["naics"], "")
        self.assertEqual(first["estimatedValue"], "")
        self.assertTrue(first["sourceUrl"].startswith("https://data.montgomerycountymd.gov/"))
        self.assertEqual(first["description"], "Parking Meters")

    def test_los_angeles_fixture_keeps_the_published_link(self):
        scripted = Scripted()
        rows, _summary = _run(scripted, _config(sources=["los_angeles_ramp"], dateFrom="2026-11-16", dateTo="2026-11-16"))
        first = _bids(rows)[0]
        self.assertEqual(first["solicitationId"], "233104")
        self.assertEqual(first["city"], "Los Angeles")
        self.assertEqual(first["state"], "CA")
        self.assertEqual(first["status"], "Open")
        self.assertEqual(first["description"], "")
        self.assertEqual(first["contactName"], "")
        self.assertIn("rampla.org", first["sourceUrl"])
        self.assertNotIn("rampla.org", " ".join(_data_calls(scripted)))

    def test_keyword_and_state_filter(self):
        scripted = Scripted()
        rows, _summary = _run(scripted, _config(
            sources=["los_angeles_ramp", "montgomery_solicitations"],
            state="CA",
            keywords=["vacuum"],
            dateFrom="2026-11-16",
            dateTo="2026-11-16",
        ))
        bids = _bids(rows)
        self.assertEqual([row["solicitationId"] for row in bids], ["233104"])
        self.assertTrue(any(row["status"] == "skipped" and row["state"] == "MD" for row in rows))
        joined = " ".join(_data_calls(scripted))
        self.assertIn("data.lacity.org", joined)
        self.assertNotIn("montgomerycountymd", joined)
        self.assertIn("VACUUM", joined.upper())

    def test_email_column_is_copied_and_a_sentence_is_not_mined(self):
        page = _load("montgomery_page.json")
        page[0]["deptcontact"] = "buyer@montgomerycountymd.gov"
        page[1]["deptcontact"] = "Email Javier at buyer@montgomerycountymd.gov"
        rows, _summary = _run(Scripted(montgomery=page), _config())
        bids = _bids(rows)
        self.assertEqual(bids[0]["contactEmail"], "buyer@montgomerycountymd.gov")
        self.assertEqual(bids[0]["contactName"], "")
        self.assertEqual(bids[1]["contactEmail"], "")
        self.assertIn("@", bids[1]["contactName"])

    def test_description_is_truncated(self):
        page = _load("montgomery_page.json")
        page[0]["description"] = "Parking " + ("meter " * 200)
        rows, _summary = _run(Scripted(montgomery=page), _config(maxItems=1))
        self.assertTrue(_bids(rows)[0]["description"].endswith("..."))
        self.assertLessEqual(len(_bids(rows)[0]["description"]), 500)

    def test_unsupported_source_is_free_and_not_fetched(self):
        scripted = Scripted()
        rows, summary = _run(scripted, _config(sources=["bonfire", "montgomery_solicitations"]))
        self.assertEqual(rows[0]["status"], "unsupported")
        self.assertIn("Bonfire", rows[0]["error"])
        self.assertEqual(len(_bids(rows)), 2)
        self.assertEqual(summary["unsupported"], 1)
        self.assertNotIn("bonfire", " ".join(_data_calls(scripted)).lower())

    def test_missing_token_skips_that_source_and_continues(self):
        gated = dict(sources.VERIFIED["montgomery_solicitations"])
        gated["requires_token"] = True
        scripted = Scripted()
        with mock.patch.dict(mapping.VERIFIED, {"montgomery_solicitations": gated}):
            rows, _summary = _run(scripted, _config(sources=["montgomery_solicitations", "los_angeles_ramp"]))
        self.assertEqual(rows[0]["status"], "skipped")
        self.assertIn("app token", rows[0]["error"])
        self.assertEqual(_bids(rows)[0]["state"], "CA")
        joined = " ".join(_data_calls(scripted))
        self.assertNotIn("montgomerycountymd", joined)
        self.assertIn("data.lacity.org", joined)

    def test_max_items_does_not_call_the_next_source(self):
        scripted = Scripted()
        rows, summary = _run(scripted, _config(sources=["los_angeles_ramp", "montgomery_solicitations"], maxItems=1))
        self.assertEqual(len(_bids(rows)), 1)
        self.assertTrue(summary["truncated"])
        self.assertNotIn("montgomerycountymd", " ".join(_data_calls(scripted)))

    def test_seen_bids_do_not_use_up_max_items(self):
        seen = {state_mod.opportunity_key("data.montgomerycountymd.gov", "1134941"): NOW}
        rows, summary = _run(Scripted(), _config(maxItems=1), seen=seen)
        self.assertEqual([row["solicitationId"] for row in _bids(rows)], ["1138052"])
        self.assertEqual(summary["skippedSeen"], 1)

    def test_block_does_not_retry(self):
        scripted = Scripted(status=403)
        rows, _summary = _run(scripted, _config())
        self.assertEqual(rows[0]["status"], "blocked")
        self.assertEqual(len(_data_calls(scripted)), 1)

    def test_not_found_is_a_status_row(self):
        rows, summary = _run(Scripted(montgomery=[]), _config())
        self.assertEqual(rows[0]["status"], "not_found")
        self.assertEqual(summary["opportunities"], 0)
        self.assertFalse(mapping.billable_row(rows[0]))


class TestMain(unittest.TestCase):
    def test_success_charges_opportunity_and_asks_for_a_rating(self):
        actor, _scripted = _run_main({
            "sources": ["montgomery_solicitations"],
            "dateFrom": "2023-03-23",
            "dateTo": "2023-03-23",
            "maxItems": 2,
            "maxSpendUsd": 1,
            "appToken": "secret-token-value",
        })
        self.assertEqual(actor.charges, ["opportunity", "opportunity"])
        self.assertEqual(len(_bids(actor.pushed)), 2)
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["billedOpportunities"], 2)
        self.assertEqual(summary["reviewAsk"], mapping.REVIEW_ASK)
        self.assertNotIn("secret-token-value", json.dumps(summary))
        self.assertNotIn("app_token", summary)
        saved = actor.stores["local-government-bids-state"]["SEEN"]["bids"]
        self.assertIn("data.montgomerycountymd.gov:1134941", saved)

    def test_spend_cap_holds_the_rest_back(self):
        actor, _scripted = _run_main({
            "sources": ["montgomery_solicitations"],
            "dateFrom": "2023-03-23",
            "dateTo": "2023-03-23",
            "maxItems": 5,
            "maxSpendUsd": 0.008,
            "appToken": "",
        })
        self.assertEqual(actor.charges, ["opportunity"])
        self.assertEqual(len(_bids(actor.pushed)), 1)
        self.assertTrue(any(row["status"] == "spend_capped" for row in actor.pushed))
        saved = actor.stores["local-government-bids-state"]["SEEN"]["bids"]
        self.assertEqual(list(saved), ["data.montgomerycountymd.gov:1134941"])
        self.assertEqual(actor.values["SUMMARY"]["reviewAsk"], mapping.REVIEW_ASK)
        self.assertTrue(actor.values["SUMMARY"]["chargeCapped"])

    def test_status_rows_are_not_charged(self):
        actor, scripted = _run_main({
            "sources": ["bonfire"],
            "maxSpendUsd": 1,
            "appToken": "",
        })
        self.assertEqual(actor.charges, [])
        self.assertEqual(scripted.calls, [])
        self.assertEqual(actor.pushed[0]["status"], "unsupported")
        self.assertNotIn("reviewAsk", actor.values["SUMMARY"])

    def test_new_since_last_run_does_not_fail_open(self):
        actor, scripted = _run_main(
            {
                "sources": ["montgomery_solicitations"],
                "dateFrom": "2023-03-23",
                "dateTo": "2023-03-23",
                "newSinceLastRun": True,
                "maxSpendUsd": 1,
                "appToken": "",
            },
            store_error=RuntimeError("kvs down"),
        )
        self.assertEqual(actor.charges, [])
        self.assertEqual(scripted.calls, [])
        self.assertEqual([row["status"] for row in actor.pushed], ["error"])
        self.assertIn("kvs down", actor.pushed[0]["error"])
        self.assertNotIn("reviewAsk", actor.values["SUMMARY"])
        self.assertEqual(actor.values["SUMMARY"]["billedOpportunities"], 0)

    def test_corrupt_state_with_new_since_last_run_charges_nothing(self):
        stores = {"local-government-bids-state": {"SEEN": {"version": 1, "bids": ["not-a-map"]}}}
        actor, scripted = _run_main(
            {
                "sources": ["montgomery_solicitations"],
                "newSinceLastRun": True,
                "dateFrom": "2023-03-23",
                "dateTo": "2023-03-23",
                "appToken": "",
            },
            stores=stores,
        )
        self.assertEqual(scripted.calls, [])
        self.assertEqual(actor.charges, [])
        self.assertEqual(actor.pushed[0]["status"], "error")
        self.assertEqual(stores["local-government-bids-state"]["SEEN"]["bids"], ["not-a-map"])

    def test_unreadable_state_without_the_flag_still_bills(self):
        actor, _scripted = _run_main(
            {
                "sources": ["montgomery_solicitations"],
                "newSinceLastRun": False,
                "dateFrom": "2023-03-23",
                "dateTo": "2023-03-23",
                "maxItems": 1,
                "maxSpendUsd": 1,
                "appToken": "",
            },
            store_error=RuntimeError("kvs down"),
        )
        self.assertEqual(actor.charges, ["opportunity"])
        self.assertEqual(actor.values["SUMMARY"]["stateError"], "kvs down")

    def test_date_error_does_not_fetch(self):
        actor, scripted = _run_main({
            "dateFrom": "2024-06-03",
            "dateTo": "2020-01-01",
            "maxSpendUsd": 1,
            "appToken": "",
        })
        self.assertEqual(scripted.calls, [])
        self.assertEqual(actor.charges, [])
        self.assertEqual(actor.pushed[0]["status"], "error")
        self.assertNotIn("reviewAsk", actor.values["SUMMARY"])

    def test_header_carries_the_token_and_the_url_does_not(self):
        self.assertEqual(fetch_mod._headers("secret-token-value")["X-App-Token"], "secret-token-value")
        self.assertNotIn("X-App-Token", fetch_mod._headers(""))
        feed = sources.VERIFIED["los_angeles_ramp"]
        url = sources.soda_url(feed["endpoint"], "1=1", 1, 0, feed["order"])
        self.assertNotIn("secret-token-value", url)


if __name__ == "__main__":
    unittest.main()
