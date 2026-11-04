"""
Unit tests for scripts/apify-scripts/gov-contracts.

Run from repo root:
    python -m pytest unittests/apify_scripts/test_gov_contracts_actor.py -q

Fixtures only. The API fetch is scripted and ``apify.Actor`` is a stand-in,
so these tests never call api.sam.gov, api.usaspending.gov, or Apify.
"""
import asyncio
import importlib
import json
import sys
import types
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

_REPO = Path(__file__).resolve().parents[2]
_ACTOR = _REPO / "scripts" / "apify-scripts" / "gov-contracts"
_SRC = _ACTOR / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gov_contracts"
_ACTOR_MODULES = ("runtime", "spend", "sources", "fetch", "mapping", "main")

NOW = "2026-11-03T12:00:00+00:00"
SECRET = "sam-test-key-0123456789"
TODAY = date(2026, 11, 3)


class FakeActor:
    """Stand-in for apify.Actor with the calls main() makes."""

    def __init__(self, actor_input, limit_after=None):
        self.input = actor_input
        self.pushed = []
        self.charges = []
        self.values = {}
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
main_mod = _actor["main"]


def _text(name):
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _as_result(payload):
    if isinstance(payload, dict) and "status" in payload and "text" not in payload:
        return dict(payload)
    if isinstance(payload, dict) and "status" in payload:
        return dict(payload)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"status": 200, "text": text, "content_type": "application/json"}


class Scripted:
    """Answers SAM.gov and USAspending from fixtures. No network."""

    def __init__(self, robots=None, sam=None, awards=None, blocked=None):
        self.robots = robots or {}
        self.sam = sam
        self.awards = awards
        self.blocked = blocked or {}
        self.calls = []

    def direct(self, request):
        self.calls.append(request)
        url = request["url"]
        parsed = urlparse(url)
        if parsed.path == "/robots.txt":
            spec = self.robots.get(parsed.netloc)
            if spec is None:
                return {"status": 200, "text": "User-agent: *\nAllow: /\n", "content_type": "text/plain"}
            if isinstance(spec, str):
                return {"status": 200, "text": spec, "content_type": "text/plain"}
            return dict(spec)
        for needle, response in self.blocked.items():
            if needle in url:
                return dict(response)
        if parsed.path.endswith("/opportunities/v2/search"):
            query = parse_qs(parsed.query)
            offset = int((query.get("offset") or ["0"])[0])
            limit = int((query.get("limit") or ["1"])[0])
            payload = self.sam(offset, limit, query) if self.sam else _text("sam_page.json")
            return _as_result(payload)
        if parsed.path.rstrip("/").endswith("spending_by_award"):
            payload = self.awards(request.get("json") or {}) if self.awards else _text("usaspending_page.json")
            return _as_result(payload)
        return {"status": 404, "text": "missing", "content_type": "text/plain"}


def _base(**overrides):
    raw = {
        "sources": ["opportunities", "awards"],
        "naics": ["541512"],
        "state": "VA",
        "setAside": "SBA",
        "postedFrom": "2024-01-01",
        "postedTo": "2024-03-31",
        "maxItems": 10,
        "samApiKey": SECRET,
        "maxSpendUsd": 5,
    }
    raw.update(overrides)
    return raw


def _run(scripted=None, **actor_input):
    scripted = scripted or Scripted()
    config = mapping.actor_input_to_config(actor_input, today=TODAY)
    sleeps = []
    fetch = fetch_mod.build_fetch(config, scripted.direct, sleep=sleeps.append)
    rows, summary = mapping.scrape(config, fetch, now=NOW)
    return rows, summary, scripted, sleeps


def _ok(rows):
    return [row for row in rows if row.get("sourceStatus") == "ok"]


def _run_main(actor_input, scripted=None, limit_after=None):
    scripted = scripted or Scripted()
    actor = FakeActor(actor_input, limit_after=limit_after)
    fake_apify = types.ModuleType("apify")
    fake_apify.Actor = actor

    def live(config):
        return fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _s: None)

    with mock.patch.dict(sys.modules, {"apify": fake_apify}), \
            mock.patch.object(main_mod, "Actor", actor), \
            mock.patch.object(main_mod, "make_live_fetch", live):
        asyncio.run(main_mod.main())
    return actor, scripted


def _data_calls(scripted, needle):
    return [call for call in scripted.calls if needle in call["url"] and not call["url"].endswith("/robots.txt")]


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []
        self.bodies = []
        self.methods = []

    def request(self, method, url, headers=None, json=None):
        self.methods.append(method)
        self.urls.append(url)
        self.bodies.append(json)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


def _response(status, body=b"ok", content_type="text/plain"):
    return types.SimpleNamespace(
        status_code=status,
        headers={"Content-Type": content_type},
        content=body,
    )


class TestInput(unittest.TestCase):
    def test_defaults_and_bounds(self):
        config = mapping.actor_input_to_config({"naics": ["541512"]}, today=TODAY)
        self.assertEqual(config["sources"], ["opportunities", "awards"])
        self.assertEqual(config["posted_from"], (TODAY - timedelta(days=90)).isoformat())
        self.assertEqual(config["posted_to"], TODAY.isoformat())
        self.assertEqual(config["max_items"], 50)
        self.assertEqual(config["delay_seconds"], 1.0)
        self.assertEqual(config["max_spend_usd"], 5.0)
        self.assertEqual(config["error"], "")

        bounded = mapping.actor_input_to_config({
            "naics": ["541512", "541512", " 236220 "],
            "state": "va",
            "setAside": "biciv",
            "maxItems": 99999,
            "delaySeconds": 0,
            "maxSpendUsd": 1000,
            "postedFrom": "2024-01-01",
            "postedTo": "2024-03-31",
        }, today=TODAY)
        self.assertEqual(bounded["naics"], ["541512", "236220"])
        self.assertEqual(bounded["state"], "VA")
        self.assertEqual(bounded["set_aside"], "BICiv")
        self.assertEqual(bounded["max_items"], 200)
        self.assertEqual(bounded["delay_seconds"], 1.0)
        self.assertEqual(bounded["max_spend_usd"], 100.0)

    def test_bad_input_is_one_error_and_does_not_fetch(self):
        cases = [
            {"naics": ["541512"], "state": "Virginia"},
            {"naics": ["54151"], "postedFrom": "01/01/2024", "postedTo": "2024-03-31"},
            {"naics": ["541512"], "postedFrom": "2024-03-31", "postedTo": "2024-01-01"},
            {"naics": ["541512"], "postedFrom": "2020-01-01", "postedTo": "2024-01-01"},
            {"naics": ["nope"]},
            {"state": "VA", "setAside": "small"},
            {"naics": ["541512"], "sources": ["grants"]},
            {},
        ]
        for raw in cases:
            rows, _summary, scripted, _sleeps = _run(**raw)
            self.assertEqual(len(rows), 1, raw)
            self.assertEqual(rows[0]["sourceStatus"], "error", raw)
            self.assertEqual(scripted.calls, [], raw)
            self.assertNotIn(SECRET, json.dumps(rows))

    def test_schema_files_declare_the_contract(self):
        form = json.loads((_ACTOR / ".actor" / "input_schema.json").read_text(encoding="utf-8"))
        props = form["properties"]
        for key in (
            "sources", "naics", "state", "setAside", "postedFrom", "postedTo",
            "maxItems", "samApiKey", "delaySeconds", "maxSpendUsd",
        ):
            self.assertIn(key, props)
        self.assertTrue(props["samApiKey"]["isSecret"])
        self.assertEqual(props["naics"]["maxItems"], 10)
        self.assertEqual(props["sources"]["editor"], "select")
        self.assertEqual(props["state"]["editor"], "select")
        self.assertEqual(props["setAside"]["editor"], "select")
        self.assertEqual(props["maxItems"]["default"], 50)
        self.assertEqual(props["maxItems"]["maximum"], 200)
        for dropped in ("maxProxyCostUsd", "allowCaptcha", "proxyConfiguration", "proxyGroups", "headless"):
            self.assertNotIn(dropped, props)

        dataset = json.loads((_ACTOR / ".actor" / "dataset_schema.json").read_text(encoding="utf-8"))
        fields = dataset["fields"]["fields"]
        for key in (
            "id", "recordType", "source", "agency", "title", "naics", "value", "deadline",
            "awardee", "contactName", "contactEmail", "contactPhone", "url", "sourceStatus",
        ):
            self.assertIn(key, fields)
        self.assertEqual(set(dataset["views"]), {"overview", "detail"})
        overview = dataset["views"]["overview"]["transformation"]["fields"]
        detail = dataset["views"]["detail"]["transformation"]["fields"]
        self.assertIn("value", overview)
        self.assertEqual(detail, list(fields))

        output = json.loads((_ACTOR / ".actor" / "output_schema.json").read_text(encoding="utf-8"))
        self.assertIn("apiDefaultDatasetUrl", output["properties"]["results"]["template"])
        store = json.loads((_ACTOR / ".actor" / "key_value_store_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(store["collections"]["summary"]["key"], "SUMMARY")

        prices = json.loads((_ACTOR / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        events = prices["actorChargeEvents"]
        self.assertEqual(events["opportunity"]["eventPriceUsd"], 0.008)
        self.assertTrue(events["opportunity"]["isPrimaryEvent"])
        self.assertEqual(events["award"]["eventPriceUsd"], 0.008)
        self.assertFalse(events["award"]["isPrimaryEvent"])
        self.assertEqual(spend.PRICES_USD["opportunity"], events["opportunity"]["eventPriceUsd"])
        self.assertEqual(spend.PRICES_USD["award"], events["award"]["eventPriceUsd"])

        actor = json.loads((_ACTOR / ".actor" / "actor.json").read_text(encoding="utf-8"))
        self.assertEqual(actor["name"], "gov-contracts")
        self.assertLessEqual(len(actor["title"]), 63)
        self.assertNotIn("dockerContextDir", actor)
        dockerfile = (_ACTOR / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM apify/actor-python:3.12", dockerfile)
        self.assertFalse(any(line.startswith("WORKDIR") for line in dockerfile.splitlines()))
        self.assertNotIn("ACTOR_PATH_IN_DOCKER_CONTEXT", dockerfile)
        bundle = (_ACTOR / "bundle.txt").read_text(encoding="utf-8")
        self.assertIn("scripts/apify-scripts/runtime.py", bundle)
        self.assertIn("scripts/apify-scripts/access.py", bundle)


class TestRows(unittest.TestCase):
    def test_opportunity_and_award_fields(self):
        rows, summary, scripted, _sleeps = _run(**_base())
        found = _ok(rows)
        self.assertEqual([row["recordType"] for row in found], ["opportunity", "opportunity", "award", "award"])
        notice = found[0]
        self.assertEqual(notice["id"], "abc123notice")
        self.assertEqual(notice["source"], "sam.gov")
        self.assertEqual(notice["agency"], "GENERAL SERVICES ADMINISTRATION.PUBLIC BUILDINGS SERVICE")
        self.assertEqual(notice["naics"], "236220")
        self.assertEqual(notice["value"], 800620)
        self.assertEqual(notice["deadline"], "2024-03-15T17:00:00-04:00")
        self.assertEqual(notice["awardee"], "D.G. Beyer, Inc.")
        self.assertEqual(notice["contactName"], "Casey Officer")
        self.assertEqual(notice["contactEmail"], "co@example.com")
        self.assertEqual(notice["contactPhone"], "2025550100")
        self.assertEqual(notice["uei"], "025114695AST")
        self.assertEqual(notice["setAside"], "SBA")
        self.assertEqual(notice["state"], "WI")
        self.assertEqual(notice["solicitationNumber"], "47PF0018R0023")
        self.assertEqual(notice["url"], "https://sam.gov/opp/abc123notice/view")
        self.assertNotIn("beta.sam.gov", notice["url"])
        self.assertEqual(found[1]["value"], None)
        self.assertEqual(found[1]["contactName"], "")
        self.assertEqual(found[1]["url"], "https://sam.gov/opp/def456notice/view")
        self.assertEqual(found[1]["subAgency"], "DEPT OF THE AIR FORCE")

        award = found[2]
        self.assertEqual(award["id"], "47QFCA21F0001")
        self.assertEqual(award["source"], "usaspending.gov")
        self.assertEqual(award["agency"], "General Services Administration")
        self.assertEqual(award["subAgency"], "Federal Acquisition Service")
        self.assertEqual(award["title"], "Enterprise IT services")
        self.assertEqual(award["naics"], "541512")
        self.assertEqual(award["value"], 1200.5)
        self.assertEqual(award["deadline"], "2024-12-31")
        self.assertEqual(award["periodStart"], "2024-01-15")
        self.assertEqual(award["awardee"], "SCIENCE APPLICATIONS INTERNATIONAL CORPORATION")
        self.assertEqual(award["uei"], "MMLKPW9JLX64")
        self.assertEqual(award["contactName"], "")
        self.assertEqual(award["contactEmail"], "")
        self.assertEqual(award["contactPhone"], "")
        self.assertEqual(award["state"], "VA")
        self.assertEqual(
            award["url"],
            "https://www.usaspending.gov/award/CONT_AWD_47QFCA21F0001_4732_47QTCK18D0001_4732",
        )
        self.assertEqual(found[3]["naics"], "")
        self.assertEqual(found[3]["value"], 50000)
        self.assertEqual(summary["found"], 4)
        self.assertEqual(summary["billedOpportunities"], 2)
        self.assertEqual(summary["billedAwards"], 2)
        self.assertEqual(summary["spendUsd"], 0.032)
        self.assertNotIn(SECRET, json.dumps({"rows": rows, "summary": summary}))
        self.assertTrue(any(SECRET in call["url"] for call in _data_calls(scripted, "api.sam.gov")))

    def test_sam_query_uses_page_index_and_official_filters(self):
        def sam(offset, limit, query):
            if offset == 0:
                records = [
                    {"noticeId": "a", "title": "A"},
                    {"noticeId": "a", "title": "A again"},
                    {"noticeId": "b", "title": "B"},
                    {"noticeId": "c", "title": "C"},
                ]
            else:
                self.assertEqual(limit, 1)
                records = [{"noticeId": "d", "title": "D"}]
            return json.dumps({"opportunitiesData": records})

        rows, summary, scripted, _sleeps = _run(
            scripted=Scripted(sam=sam),
            **_base(sources=["opportunities"], maxItems=4),
        )
        found = _ok(rows)
        self.assertEqual([row["id"] for row in found], ["a", "b", "c", "d"])
        self.assertEqual(summary["mergedDuplicates"], 1)
        pages = _data_calls(scripted, "/opportunities/v2/search")
        self.assertEqual(len(pages), 2)
        first = parse_qs(urlparse(pages[0]["url"]).query)
        second = parse_qs(urlparse(pages[1]["url"]).query)
        self.assertEqual(first["offset"], ["0"])
        self.assertEqual(second["offset"], ["1"])
        self.assertEqual(first["postedFrom"], ["01/01/2024"])
        self.assertEqual(first["postedTo"], ["03/31/2024"])
        self.assertEqual(first["ncode"], ["541512"])
        self.assertEqual(first["state"], ["VA"])
        self.assertEqual(first["typeOfSetAside"], ["SBA"])
        self.assertNotIn(SECRET, json.dumps(rows))

    def test_max_items_does_not_request_the_second_source(self):
        rows, _summary, scripted, _sleeps = _run(**_base(maxItems=1))
        found = _ok(rows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["recordType"], "opportunity")
        self.assertEqual(_data_calls(scripted, "spending_by_award"), [])

    def test_missing_key_skips_sam_and_still_reads_awards(self):
        rows, summary, scripted, _sleeps = _run(**_base(samApiKey=""))
        found = _ok(rows)
        self.assertEqual([row["recordType"] for row in found], ["award", "award"])
        skipped = [row for row in rows if row["sourceStatus"] == "skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertIn("samApiKey", skipped[0]["error"])
        self.assertFalse(mapping.billable_row(skipped[0]))
        self.assertEqual(_data_calls(scripted, "api.sam.gov"), [])
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["billedAwards"], 2)
        self.assertEqual(summary["billedOpportunities"], 0)

    def test_sam_block_still_reads_awards(self):
        scripted = Scripted(blocked={"api.sam.gov/opportunities": {"status": 403, "text": "no", "content_type": "text/plain"}})
        rows, summary, scripted, _sleeps = _run(scripted=scripted, **_base())
        blocked = [row for row in rows if row["sourceStatus"] == "blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertIn("HTTP 403", blocked[0]["error"])
        self.assertNotIn(SECRET, blocked[0]["error"])
        self.assertEqual(len(_ok(rows)), 2)
        self.assertEqual(summary["status"], "partial")
        self.assertTrue(all(row["recordType"] == "award" for row in _ok(rows)))

    def test_award_block_is_one_row_when_it_is_the_only_source(self):
        scripted = Scripted(blocked={
            "spending_by_award": {"status": 429, "text": "slow", "content_type": "text/plain"},
        })
        rows, summary, _scripted, _sleeps = _run(scripted=scripted, **_base(sources=["awards"], samApiKey=""))
        self.assertEqual([row["sourceStatus"] for row in rows], ["blocked"])
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["spendUsd"], 0)

    def test_robots_disallow_skips_the_host(self):
        scripted = Scripted(robots={"api.usaspending.gov": "User-agent: *\nDisallow: /api/\n"})
        rows, summary, scripted, _sleeps = _run(scripted=scripted, **_base(sources=["awards"], samApiKey=""))
        self.assertEqual([row["sourceStatus"] for row in rows], ["robots"])
        self.assertEqual(_data_calls(scripted, "spending_by_award"), [])
        self.assertEqual(summary["billedAwards"], 0)

    def test_robots_404_still_fetches(self):
        scripted = Scripted(robots={
            "api.usaspending.gov": {"status": 404, "text": "missing", "content_type": "text/plain"},
        })
        rows, _summary, scripted, _sleeps = _run(scripted=scripted, **_base(sources=["awards"], samApiKey=""))
        self.assertEqual(len(_ok(rows)), 2)
        self.assertFalse(any(row["sourceStatus"] == "robots" for row in rows))
        self.assertEqual(len(_data_calls(scripted, "spending_by_award")), 1)

    def test_award_request_body(self):
        _rows, _summary, scripted, _sleeps = _run(**_base(sources=["awards"], samApiKey="", maxItems=2))
        body = _data_calls(scripted, "spending_by_award")[0]["json"]
        self.assertEqual(body["limit"], 2)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["filters"]["award_type_codes"], ["A", "B", "C", "D"])
        self.assertEqual(body["filters"]["naics_codes"], {"require": ["541512"]})
        self.assertEqual(body["filters"]["place_of_performance_locations"], [{"country": "USA", "state": "VA"}])
        self.assertEqual(body["filters"]["set_aside_type_codes"], ["SBA"])
        self.assertEqual(body["filters"]["time_period"], [{"start_date": "2024-01-01", "end_date": "2024-03-31"}])
        self.assertNotIn("api_key", json.dumps(body))


class TestCharging(unittest.TestCase):
    def test_events_follow_the_row_and_the_cap_holds_the_rest(self):
        actor, _scripted = _run_main(_base(maxItems=10, maxSpendUsd=0.024))
        found = _ok(actor.pushed)
        self.assertEqual(len(found), 3)
        self.assertEqual(actor.charges, ["opportunity", "opportunity", "award"])
        capped = [row for row in actor.pushed if row["sourceStatus"] == "spend_capped"]
        self.assertEqual(len(capped), 1)
        self.assertFalse(mapping.billable_row(capped[0]))
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["heldBack"], 1)
        self.assertEqual(summary["billedOpportunities"], 2)
        self.assertEqual(summary["billedAwards"], 1)
        self.assertEqual(summary["spendUsd"], 0.024)
        self.assertTrue(summary["chargeCapped"])
        self.assertNotIn(SECRET, json.dumps(summary))
        self.assertNotIn("sam_api_key", json.dumps(summary))

    def test_charge_failure_keeps_the_row_and_does_not_bill_it(self):
        scripted = Scripted()
        actor = FakeActor(_base(sources=["awards"], samApiKey="", maxItems=10, maxSpendUsd=5))

        async def flaky(event_name=None):
            raise RuntimeError("charge down")

        actor.charge = flaky
        fake_apify = types.ModuleType("apify")
        fake_apify.Actor = actor

        def live(config):
            return fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _s: None)

        with mock.patch.dict(sys.modules, {"apify": fake_apify}), \
                mock.patch.object(main_mod, "Actor", actor), \
                mock.patch.object(main_mod, "make_live_fetch", live):
            asyncio.run(main_mod.main())
        self.assertEqual(len(_ok(actor.pushed)), 1)
        self.assertEqual(actor.charges, [])
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["billedAwards"], 0)
        self.assertEqual(summary["spendUsd"], 0)
        self.assertEqual(summary["stopped"], "chargeFailed")
        self.assertEqual(summary["heldBack"], 1)
        self.assertTrue(any(row["sourceStatus"] == "spend_capped" for row in actor.pushed))

    def test_micro_dollar_ledger_rejects_proxy(self):
        ledger = spend.LeadLedger(0.02)
        self.assertTrue(ledger.fits(["opportunity"]))
        self.assertTrue(ledger.fits(["award"]))
        self.assertFalse(ledger.can("proxy"))
        self.assertFalse(ledger.can("captcha"))
        ledger.commit("opportunity")
        ledger.commit("award")
        self.assertFalse(ledger.fits(["award"]))
        self.assertEqual(ledger.spend_usd, 0.016)


class TestHttp(unittest.TestCase):
    def test_api_key_is_redacted_from_the_result(self):
        url = f"https://api.sam.gov/opportunities/v2/search?api_key={SECRET}&limit=1"
        client = _Client([_response(403, b"no")])
        body = fetch_mod.http_request("GET", url, client=client)
        self.assertIn(SECRET, client.urls[0])
        self.assertNotIn(SECRET, json.dumps(body))
        self.assertNotIn("api_key=", body["url"])
        self.assertEqual(len(client.urls), 1)

    def test_post_body_is_sent_and_403_is_not_retried(self):
        client = _Client([_response(403, b"{}", "application/json")])
        body = fetch_mod.http_request("POST", "https://api.usaspending.gov/api/v2/search/spending_by_award/", json_body={"limit": 1}, client=client)
        self.assertEqual(body["status"], 403)
        self.assertEqual(client.methods, ["POST"])
        self.assertEqual(client.bodies, [{"limit": 1}])

    def test_server_error_retries_once(self):
        client = _Client([
            _response(503, b"busy"),
            _response(200, b"{}", "application/json"),
        ])
        with mock.patch.object(fetch_mod.time, "sleep"):
            body = fetch_mod.http_request("GET", "https://api.sam.gov/opportunities/v2/search", client=client)
        self.assertEqual(body["status"], 200)
        self.assertEqual(len(client.urls), 2)


class TestSmokeFixture(unittest.TestCase):
    def test_ci_fixture_is_awards_only_and_the_budget_is_exact(self):
        fixture = json.loads((_ACTOR / "fixtures" / "INPUT.json").read_text(encoding="utf-8"))
        budget = json.loads((_ACTOR / "fixtures" / "budget.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["sources"], ["awards"])
        self.assertNotIn("samApiKey", fixture)
        self.assertEqual(fixture["naics"], ["541512"])
        self.assertEqual(fixture["state"], "VA")
        self.assertEqual(fixture["postedFrom"], "2024-01-01")
        self.assertEqual(fixture["postedTo"], "2024-03-31")
        self.assertEqual(fixture["maxItems"], 2)
        self.assertEqual(budget["minItems"], fixture["maxItems"])
        self.assertEqual(budget["maxItems"], fixture["maxItems"])
        price = json.loads((_ACTOR / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        award_price = price["actorChargeEvents"]["award"]["eventPriceUsd"]
        self.assertEqual(budget["maxChargeUsd"], fixture["maxItems"] * award_price)
        self.assertLessEqual(budget["maxChargeUsd"], fixture["maxSpendUsd"])
        self.assertEqual(budget["memoryMbytes"], 512)
        self.assertGreaterEqual(budget["maxDurationSecs"], 60)
        self.assertLessEqual(budget["maxDurationSecs"], 1800)
        self.assertIn("does not need a SAM key", budget["notes"])


if __name__ == "__main__":
    unittest.main()
