"""
Unit tests for scripts/apify-scripts/ucc-filing.

Run from repo root:
    python -m pytest unittests/apify_scripts/test_ucc_filing_actor.py -q

Fixtures only. The open-data fetch is scripted and ``apify.Actor`` is a
stand-in, so these tests never call data.ct.gov, data.oregon.gov, or Apify.
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
_SRC = _REPO / "scripts" / "apify-scripts" / "ucc-filing" / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ucc_filing"
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
stream_mod = _actor["stream"]
main_mod = _actor["main"]


def _load(name):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _config(**overrides):
    raw = {
        "states": ["CT"],
        "dateFrom": "2024-06-03",
        "dateTo": "2024-06-03",
        "filingTypes": ["UCC-1"],
        "maxItems": 5,
        "maxSpendUsd": 1,
    }
    raw.update(overrides)
    config = mapping.actor_input_to_config(raw, today=TODAY)
    if "_page_size" in overrides:
        config["_page_size"] = overrides["_page_size"]
    if "_max_bytes" in overrides:
        config["_max_bytes"] = overrides["_max_bytes"]
    return config


class Scripted:
    def __init__(self, rows=None, robots=None, status=200, huge=0):
        self.rows = rows if rows is not None else []
        self.robots = "User-agent: *\nAllow: /\n" if robots is None else robots
        self.status = status
        self.huge = huge
        self.calls = []
        self.pulls = 0

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
        if self.huge:
            return {"status": 200, "chunks": self._huge_chunks(), "error": None, "content_type": "application/json"}
        limit = int(query["$limit"][0])
        offset = int(query.get("$offset", ["0"])[0])
        page = self.rows[offset:offset + limit]
        return {"status": 200, "chunks": self._page_chunks(page), "error": None, "content_type": "application/json"}

    def _page_chunks(self, page):
        self.pulls += 1
        yield b"["
        for index, row in enumerate(page):
            self.pulls += 1
            prefix = b"" if index == 0 else b","
            yield prefix + json.dumps(row).encode()
        self.pulls += 1
        yield b"]"

    def _huge_chunks(self):
        self.pulls += 1
        yield b"["
        for index in range(self.huge):
            self.pulls += 1
            prefix = b"" if index == 0 else b","
            row = {
                "id_ucc_flng_nbr": f"{index:07d}",
                "cd_flng_type": "ORIG FIN STMT",
                "tx_lien_descript": "OFS",
                "debtor_nm_bus": f"DEBTOR {index}",
                "dt_accept": "2024-06-03T00:00:00.000",
                "dt_lapse": "2029-06-03T00:00:00.000",
                "sec_party_nm_bus": "LENDER",
            }
            yield prefix + json.dumps(row).encode()
        self.pulls += 1
        yield b"]"


def _run(scripted, config, seen=None):
    fetch = fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _seconds: None)
    return mapping.scrape(config, fetch, seen=seen, now=NOW)


def _data_calls(scripted):
    return [url for url in scripted.calls if not url.endswith("/robots.txt")]


def _run_main(actor_input, scripted=None, **actor_kwargs):
    scripted = scripted or Scripted(_load("ct_page.json"))
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


def _filings(rows):
    return [row for row in rows if row.get("status") == "ok"]


class TestInput(unittest.TestCase):
    def test_defaults_are_one_state_and_seven_days(self):
        config = mapping.actor_input_to_config({}, today=TODAY)
        self.assertEqual(config["states"], ["CT"])
        self.assertEqual(config["filing_types"], ["UCC-1"])
        self.assertEqual(config["max_items"], 25)
        self.assertEqual(config["max_spend_usd"], 0.50)
        self.assertEqual(config["delay_seconds"], 1)
        self.assertFalse(config["new_since_last_run"])
        self.assertEqual(config["state_store"], "ucc-filing-state")
        self.assertEqual(config["date_from"], "2026-11-10")
        self.assertEqual(config["date_to"], "2026-11-16")
        self.assertEqual(config["error"], "")

    def test_caps_and_unknown_filing_type(self):
        config = mapping.actor_input_to_config({
            "states": ["ct", "CT", "or", "fl"],
            "filingTypes": ["ucc1", "nope", "UCC-3"],
            "maxItems": 9000,
            "maxSpendUsd": 250,
            "delaySeconds": 0,
            "dateFrom": "2024-01-01",
            "dateTo": "2024-12-31",
        }, today=TODAY)
        self.assertEqual(config["states"], ["CT", "OR", "FL"])
        self.assertEqual(config["filing_types"], ["UCC-1", "UCC-3"])
        self.assertEqual(config["max_items"], 500)
        self.assertEqual(config["max_spend_usd"], 100)
        self.assertEqual(config["delay_seconds"], 1)
        self.assertIn("92", config["error"])

    def test_one_sided_date_is_an_error(self):
        config = mapping.actor_input_to_config({"dateFrom": "2024-06-03"}, today=TODAY)
        self.assertIn("both", config["error"])


class TestSources(unittest.TestCase):
    def test_page_url_is_bounded(self):
        feed = sources.VERIFIED["CT"]
        where = sources.where_clause(feed, ["UCC-1"], "2024-06-03", "2024-06-03")
        url = sources.soda_url(feed["endpoint"], where, 100, 0, feed["order"])
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["$limit"], ["100"])
        self.assertIn("ORIG FIN STMT", query["$where"][0])
        self.assertIn("OFS", query["$where"][0])
        self.assertNotIn("export.csv", url.lower())
        self.assertNotIn("rows.csv", url.lower())
        self.assertEqual(sources.guard_url(url), "")

    def test_statewide_export_is_refused(self):
        self.assertEqual(
            sources.guard_url("https://data.ct.gov/api/views/xfev-8smz/rows.csv?accessType=DOWNLOAD"),
            "statewide_export",
        )
        with self.assertRaises(ValueError):
            sources.soda_url("https://data.oregon.gov/api/views/snfi-f79b/rows.csv", "x", 10, 0, "file_number")
        with self.assertRaises(ValueError):
            sources.soda_url(sources.VERIFIED["CT"]["endpoint"], "x", 500, 0, "dt_accept")

    def test_injection_does_not_reach_the_query(self):
        feed = sources.VERIFIED["OR"]
        where = sources.where_clause(feed, ["UCC-1"], "2026-10-01", "2026-10-31")
        self.assertNotIn("OR 1=1", where)
        self.assertIn("INITIAL", where)
        self.assertIn("lien_type = 'UCC'", where)


class TestStream(unittest.TestCase):
    def test_byte_cap_stops_before_the_rest_of_the_body(self):
        pulls = {"n": 0}

        def chunks():
            yield b"["
            while pulls["n"] < 10000:
                pulls["n"] += 1
                yield b'{"n":1,"pad":"' + (b"y" * 40) + b'"},'

        reader = stream_mod.ArrayReader(chunks(), max_bytes=500)
        rows = list(reader)
        self.assertTrue(reader.truncated)
        self.assertLess(pulls["n"], 40)
        self.assertLess(len(rows), 20)
        self.assertGreater(len(rows), 0)

    def test_error_object_is_not_a_filing(self):
        reader = stream_mod.ArrayReader([b'{"message":"query timeout"}'])
        self.assertEqual(list(reader), [])
        self.assertIn("query timeout", reader.error)


class TestFilings(unittest.TestCase):
    def test_connecticut_fixture_folds_party_rows(self):
        scripted = Scripted(_load("ct_page.json"))
        rows, summary = _run(scripted, _config(maxItems=5))
        filings = _filings(rows)
        self.assertEqual(len(filings), 1)
        row = filings[0]
        self.assertEqual(row["state"], "CT")
        self.assertEqual(row["filingNumber"], "0005219659")
        self.assertEqual(row["filingType"], "UCC-1")
        self.assertEqual(row["filingDate"], "2024-06-03")
        self.assertEqual(row["lapseDate"], "2029-06-03")
        self.assertIn("COMPASSIONATE HANDS IN HOME AGENCY LLC", row["debtorName"])
        self.assertIn("MAYE SHAWNEISHA PUBLISHING", row["debtorName"])
        self.assertIn("COMPASSIONATE HOMECARE AGENCY LLC", row["debtorName"])
        self.assertIn("Shawneisha L Maye", row["debtorName"])
        self.assertEqual(row["securedPartyName"], "Bitty Advance 2, LLC")
        self.assertIn("Dania Beach", row["securedPartyAddress"])
        self.assertEqual(row["collateral"], "")
        self.assertEqual(row["source"], "data.ct.gov")
        self.assertEqual(row["status"], "ok")
        self.assertTrue(row["ok"])
        self.assertTrue(mapping.billable_row(row))
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(len(_data_calls(scripted)), 1)
        self.assertIn("limit=", _data_calls(scripted)[0])

    def test_oregon_fixture_folds_debtor_and_secured_party(self):
        rows, _summary = _run(
            Scripted(_load("or_page.json")),
            _config(states=["OR"], dateFrom="2026-10-01", dateTo="2026-10-31"),
        )
        filings = _filings(rows)
        self.assertEqual(len(filings), 1)
        row = filings[0]
        self.assertEqual(row["state"], "OR")
        self.assertEqual(row["filingNumber"], "94624849")
        self.assertEqual(row["filingType"], "UCC-1")
        self.assertEqual(row["filingDate"], "2026-10-21")
        self.assertEqual(row["lapseDate"], "2031-10-21")
        self.assertEqual(row["debtorName"], "RIDGES, KEVIN")
        self.assertIn("SANDY", row["debtorAddress"])
        self.assertEqual(row["securedPartyName"], "SUNGAGE FINANCIAL LLC, AS COLLATERAL AGENT")
        self.assertIn("ORSOSWebDrawer", row["sourceUrl"])
        self.assertEqual(row["source"], "data.oregon.gov")

    def test_unsupported_states_are_free_and_not_fetched(self):
        def explode(_request):
            raise AssertionError("unsupported state was fetched")

        config = _config(states=["FL", "NJ", "KY", "CO"])
        fetch = fetch_mod.build_fetch(config, explode, sleep=lambda _seconds: None)
        rows, summary = mapping.scrape(config, fetch, now=NOW)
        self.assertEqual([row["status"] for row in rows], ["unsupported", "unsupported", "unsupported", "unsupported"])
        self.assertIn("Sunbiz", rows[0]["error"])
        self.assertIn("portal", rows[1]["error"])
        self.assertIn("paid", rows[2]["error"])
        self.assertIn("no debtor", rows[3]["error"])
        self.assertEqual(summary["status"], "unsupported")
        self.assertTrue(all(not mapping.billable_row(row) for row in rows))

    def test_not_found_is_a_status_row(self):
        rows, summary = _run(Scripted([]), _config())
        self.assertEqual([row["status"] for row in rows], ["not_found"])
        self.assertEqual(summary["notFound"], 1)
        self.assertFalse(mapping.billable_row(rows[0]))

    def test_block_does_not_retry(self):
        scripted = Scripted(_load("ct_page.json"), status=403)
        rows, summary = _run(scripted, _config())
        self.assertEqual([row["status"] for row in rows], ["blocked"])
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(len(_data_calls(scripted)), 1)

    def test_robots_disallow_skips_the_file(self):
        scripted = Scripted(_load("ct_page.json"), robots="User-agent: *\nDisallow: /resource\n")
        rows, summary = _run(scripted, _config())
        self.assertEqual([row["status"] for row in rows], ["robots"])
        self.assertEqual(summary["robots"], 1)
        self.assertEqual(_data_calls(scripted), [])

    def test_huge_page_stops_at_max_items(self):
        scripted = Scripted(huge=5000)
        rows, summary = _run(scripted, _config(maxItems=2))
        filings = _filings(rows)
        self.assertEqual(len(filings), 2)
        self.assertEqual(filings[0]["filingNumber"], "0000000")
        self.assertEqual(filings[1]["filingNumber"], "0000001")
        self.assertLess(scripted.pulls, 20)
        self.assertEqual(len(_data_calls(scripted)), 1)
        self.assertIn("limit=100", _data_calls(scripted)[0])
        self.assertNotIn("export.csv", _data_calls(scripted)[0])
        self.assertFalse(summary["truncated"])

    def test_filing_split_across_pages_is_kept_whole(self):
        rows = []
        for debtor in ("ONE", "TWO", "THREE"):
            rows.append({
                "id_ucc_flng_nbr": "0000001",
                "cd_flng_type": "ORIG FIN STMT",
                "tx_lien_descript": "OFS",
                "debtor_nm_bus": debtor,
                "dt_accept": "2024-06-03T00:00:00.000",
                "sec_party_nm_bus": "LENDER",
            })
        rows.append({
            "id_ucc_flng_nbr": "0000002",
            "cd_flng_type": "ORIG FIN STMT",
            "tx_lien_descript": "OFS",
            "debtor_nm_bus": "OTHER",
            "dt_accept": "2024-06-03T00:00:00.000",
            "sec_party_nm_bus": "LENDER",
        })
        scripted = Scripted(rows)
        got, _summary = _run(scripted, _config(maxItems=1, _page_size=2))
        filings = _filings(got)
        self.assertEqual(len(filings), 1)
        self.assertEqual(filings[0]["filingNumber"], "0000001")
        self.assertIn("ONE", filings[0]["debtorName"])
        self.assertIn("TWO", filings[0]["debtorName"])
        self.assertIn("THREE", filings[0]["debtorName"])
        self.assertNotIn("OTHER", filings[0]["debtorName"])
        offsets = [parse_qs(urlparse(url).query)["$offset"][0] for url in _data_calls(scripted)]
        self.assertEqual(offsets, ["0", "2"])

    def test_later_state_is_not_called_once_max_items_is_full(self):
        scripted = Scripted(_load("ct_page.json"))
        rows, summary = _run(scripted, _config(states=["CT", "OR"], maxItems=1))
        self.assertEqual(len(_filings(rows)), 1)
        self.assertTrue(all("data.oregon.gov" not in url for url in scripted.calls))
        self.assertTrue(any(item["state"] == "OR" and item["status"] == "maxItems" for item in summary["states"]))

    def test_collateral_and_sentinel_lapse(self):
        row = dict(_load("ct_page.json")[0])
        row["collateral"] = "inventory " * 800
        row["dt_lapse"] = "9999-12-31T00:00:00.000"
        filings = _filings(_run(Scripted([row]), _config())[0])
        self.assertEqual(len(filings[0]["collateral"]), 2000)
        self.assertTrue(filings[0]["collateral"].endswith("..."))
        self.assertEqual(filings[0]["lapseDate"], "")

    def test_seen_filings_do_not_use_up_max_items(self):
        first = dict(_load("ct_page.json")[0])
        second = dict(first)
        second["id_ucc_flng_nbr"] = "0000002"
        second["debtor_nm_bus"] = "SECOND DEBTOR"
        seen = {state_mod.filing_key("CT", "0005219659", "UCC-1"): NOW}
        rows, summary = _run(Scripted([first, second]), _config(maxItems=1), seen=seen)
        filings = _filings(rows)
        self.assertEqual([row["filingNumber"] for row in filings], ["0000002"])
        self.assertEqual(summary["skippedSeen"], 1)


class TestMain(unittest.TestCase):
    def test_success_charges_filing_and_asks_for_a_rating(self):
        actor, _scripted = _run_main({
            "states": ["CT"],
            "dateFrom": "2024-06-03",
            "dateTo": "2024-06-03",
            "maxItems": 2,
            "maxSpendUsd": 1,
        })
        self.assertEqual(actor.charges, ["filing"])
        self.assertEqual(len(_filings(actor.pushed)), 1)
        self.assertEqual(actor.values["SUMMARY"]["billedFilings"], 1)
        self.assertEqual(actor.values["SUMMARY"]["reviewAsk"], mapping.REVIEW_ASK)
        self.assertIn("CT:0005219659:UCC-1", actor.stores["ucc-filing-state"]["SEEN"]["filings"])

    def test_spend_cap_holds_the_rest_back(self):
        first = dict(_load("ct_page.json")[0])
        second = dict(first)
        second["id_ucc_flng_nbr"] = "0000002"
        actor, _scripted = _run_main(
            {
                "states": ["CT"],
                "dateFrom": "2024-06-03",
                "dateTo": "2024-06-03",
                "maxItems": 5,
                "maxSpendUsd": 0.008,
            },
            scripted=Scripted([first, second]),
        )
        self.assertEqual(actor.charges, ["filing"])
        self.assertEqual(len(_filings(actor.pushed)), 1)
        self.assertTrue(any(row["status"] == "spend_capped" for row in actor.pushed))
        saved = actor.stores["ucc-filing-state"]["SEEN"]["filings"]
        self.assertEqual(list(saved), ["CT:0005219659:UCC-1"])
        self.assertEqual(actor.values["SUMMARY"]["reviewAsk"], mapping.REVIEW_ASK)
        self.assertTrue(actor.values["SUMMARY"]["chargeCapped"])

    def test_new_since_last_run_does_not_fail_open(self):
        actor, scripted = _run_main(
            {
                "states": ["CT"],
                "dateFrom": "2024-06-03",
                "dateTo": "2024-06-03",
                "newSinceLastRun": True,
                "maxSpendUsd": 1,
            },
            store_error=RuntimeError("kvs down"),
        )
        self.assertEqual(actor.charges, [])
        self.assertEqual(scripted.calls, [])
        self.assertEqual([row["status"] for row in actor.pushed], ["error"])
        self.assertIn("kvs down", actor.pushed[0]["error"])
        self.assertNotIn("reviewAsk", actor.values["SUMMARY"])
        self.assertEqual(actor.values["SUMMARY"]["billedFilings"], 0)

    def test_corrupt_state_with_new_since_last_run_charges_nothing(self):
        stores = {"ucc-filing-state": {"SEEN": {"version": 1, "filings": ["not-a-map"]}}}
        actor, scripted = _run_main(
            {"states": ["CT"], "newSinceLastRun": True, "dateFrom": "2024-06-03", "dateTo": "2024-06-03"},
            stores=stores,
        )
        self.assertEqual(scripted.calls, [])
        self.assertEqual(actor.charges, [])
        self.assertEqual(actor.pushed[0]["status"], "error")
        self.assertEqual(stores["ucc-filing-state"]["SEEN"]["filings"], ["not-a-map"])

    def test_unreadable_state_without_the_flag_still_bills(self):
        actor, _scripted = _run_main(
            {"states": ["CT"], "newSinceLastRun": False, "dateFrom": "2024-06-03", "dateTo": "2024-06-03", "maxSpendUsd": 1},
            store_error=RuntimeError("kvs down"),
        )
        self.assertEqual(actor.charges, ["filing"])
        self.assertEqual(actor.values["SUMMARY"]["stateError"], "kvs down")

    def test_date_error_does_not_fetch(self):
        actor, scripted = _run_main({"dateFrom": "2024-06-03", "dateTo": "2020-01-01", "maxSpendUsd": 1})
        self.assertEqual(scripted.calls, [])
        self.assertEqual(actor.charges, [])
        self.assertEqual(actor.pushed[0]["status"], "error")
        self.assertNotIn("reviewAsk", actor.values["SUMMARY"])


if __name__ == "__main__":
    unittest.main()
