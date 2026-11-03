"""
Unit tests for scripts/apify-scripts/ats-jobs.

Run from repo root:
    python -m pytest unittests/apify_scripts/test_ats_jobs_actor.py -q

Fixtures only. The board fetch is scripted and ``apify.Actor`` is a stand-in,
so these tests never call Greenhouse, Lever, Ashby, Workable, or Apify.
"""
import asyncio
import importlib
import json
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

_REPO = Path(__file__).resolve().parents[2]
_ACTOR = _REPO / "scripts" / "apify-scripts" / "ats-jobs"
_SRC = _ACTOR / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ats_jobs"
_ACTOR_MODULES = ("runtime", "spend", "sources", "state", "fetch", "mapping", "main")

NOW = "2026-11-02T12:00:00+00:00"


class FakeStore:
    def __init__(self, data):
        self.data = data

    async def get_value(self, key):
        return self.data.get(key)

    async def set_value(self, key, value):
        self.data[key] = json.loads(json.dumps(value))


class FakeActor:
    """Stand-in for apify.Actor with the calls main() and push_charged_rows make."""

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


BOARDS = {
    "boards-api.greenhouse.io/v1/boards/exampleco/": "greenhouse.json",
    "api.lever.co/v0/postings/examplelever": "lever.json",
    "api.eu.lever.co/v0/postings/exampleeu": "lever.json",
    "api.ashbyhq.com/posting-api/job-board/exampleashby": "ashby.json",
    "apply.workable.com/api/v1/widget/accounts/examplewk": "workable.json",
}


class Scripted:
    """Answers board URLs from fixtures. Unknown boards are 404."""

    def __init__(self, blocked=None, robots=None):
        self.blocked = blocked or {}
        self.robots = robots or {}
        self.urls = []

    def direct(self, url):
        self.urls.append(url)
        parsed = urlparse(url)
        if parsed.path == "/robots.txt":
            if parsed.netloc in self.robots:
                return self.robots[parsed.netloc]
            return {"status": 200, "text": "User-agent: *\nAllow: /\n", "content_type": "text/plain"}
        for needle, response in self.blocked.items():
            if needle in url:
                return dict(response)
        for needle, name in BOARDS.items():
            if needle in url:
                return {"status": 200, "text": _text(name), "content_type": "application/json"}
        return {"status": 404, "text": "Not Found", "content_type": "text/plain"}

    def board_urls(self):
        return [url for url in self.urls if not url.endswith("/robots.txt")]


def _base_input(**extra):
    payload = {
        "greenhouse": ["exampleco"],
        "lever": ["examplelever"],
        "ashby": ["exampleashby"],
        "workable": ["examplewk"],
        "maxItems": 100,
        "maxSpendUsd": 5,
    }
    payload.update(extra)
    return payload


def _run(scripted=None, seen=None, **actor_input):
    scripted = scripted or Scripted()
    config = mapping.actor_input_to_config(actor_input)
    sleeps = []
    fetch = fetch_mod.build_fetch(config, scripted.direct, sleep=sleeps.append)
    rows, summary, new_seen = mapping.scrape(config, fetch, seen=seen, now=NOW)
    return rows, summary, new_seen, scripted, sleeps


def _found(rows):
    return [row for row in rows if row.get("sourceStatus") == "found"]


def _by_id(rows):
    return {row["jobId"]: row for row in _found(rows)}


def _run_main(actor_input, scripted=None, stores=None, limit_after=None):
    scripted = scripted or Scripted()
    actor = FakeActor(actor_input, stores=stores, limit_after=limit_after)
    fake_apify = types.ModuleType("apify")
    fake_apify.Actor = actor

    def live(config):
        return fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _s: None)

    with mock.patch.dict(sys.modules, {"apify": fake_apify}), \
            mock.patch.object(main_mod, "Actor", actor), \
            mock.patch.object(main_mod, "make_live_fetch", live):
        asyncio.run(main_mod.main())
    return actor, scripted


def _utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")


class TestInput(unittest.TestCase):
    def test_defaults_and_bounds(self):
        config = mapping.actor_input_to_config({
            "greenhouse": ["airbnb"],
            "maxItems": 999999,
            "delaySeconds": 0,
            "maxSpendUsd": 1000,
            "remote": "sometimes",
        })
        self.assertEqual(config["max_items"], 10000)
        self.assertEqual(config["delay_seconds"], 1.0)
        self.assertEqual(config["max_spend_usd"], 100.0)
        self.assertEqual(config["remote"], "any")
        self.assertEqual(config["state_store"], "ats-jobs-state")
        self.assertFalse(config["new_since_last_run"])
        self.assertEqual(config["error"], "")

    def test_slugs_from_urls_eu_and_duplicates(self):
        config = mapping.actor_input_to_config({
            "greenhouse": ["https://boards.greenhouse.io/airbnb", "airbnb", "AIRBNB", "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"],
            "lever": ["https://jobs.eu.lever.co/euco/abc"],
            "leverEu": ["exampleeu"],
            "ashby": ["jobs.ashbyhq.com/Ashby"],
            "workable": ["apply.workable.com/huggingface/", "bad slug!"],
        })
        targets = [(t["ats"], t["slug"], t["eu"]) for t in config["targets"]]
        self.assertEqual(targets, [
            ("greenhouse", "airbnb", False),
            ("greenhouse", "stripe", False),
            ("lever", "euco", True),
            ("lever", "exampleeu", True),
            ("ashby", "Ashby", False),
            ("workable", "huggingface", False),
        ])
        self.assertEqual(config["duplicate_targets"], 2)
        self.assertEqual(config["invalid"], [("workable", "bad slug!")])
        self.assertEqual(
            sources.board_url("lever", "exampleeu", eu=True),
            "https://api.eu.lever.co/v0/postings/exampleeu?mode=json",
        )

    def test_keyword_accepts_a_string(self):
        config = mapping.actor_input_to_config({"greenhouse": ["x"], "keyword": "Engineer, Sales"})
        self.assertEqual(config["keywords"], ["engineer", "sales"])

    def test_no_companies_is_one_error_row(self):
        rows, summary, _new, scripted, _sleeps = _run(Scripted())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sourceStatus"], "error")
        self.assertIn("company slug", rows[0]["error"])
        self.assertEqual(scripted.urls, [])
        self.assertEqual(summary["billedJobs"], 0)

    def test_schema_files_declare_the_contract(self):
        form = json.loads((_ACTOR / ".actor" / "input_schema.json").read_text(encoding="utf-8"))
        props = form["properties"]
        for key in ("greenhouse", "lever", "ashby", "workable", "location", "remote", "keywords",
                    "newSinceLastRun", "maxItems", "maxSpendUsd"):
            self.assertIn(key, props)
        for key in ("greenhouse", "lever", "leverEu", "ashby", "workable", "keywords"):
            self.assertEqual(props[key]["editor"], "stringList")
            self.assertIn("maxItems", props[key])
        self.assertEqual(props["remote"]["editor"], "select")
        self.assertEqual(props["remote"]["enum"], ["any", "remote", "exclude"])
        for dropped in ("maxProxyCostUsd", "allowCaptcha", "proxyConfiguration", "proxyGroups", "headless"):
            self.assertNotIn(dropped, props)

        dataset = json.loads((_ACTOR / ".actor" / "dataset_schema.json").read_text(encoding="utf-8"))
        fields = dataset["fields"]["fields"]
        for key in ("company", "title", "location", "remote", "salary", "department", "postedDate",
                    "url", "ats", "firstSeen", "sourceStatus", "decision", "error", "scrapedAt"):
            self.assertIn(key, fields)
        self.assertEqual(fields["salary"]["type"], "object")
        self.assertEqual(set(fields["salary"]["properties"]), {"min", "max", "currency", "interval", "raw"})
        self.assertEqual(set(dataset["views"]), {"overview", "detail"})

        events = json.loads((_ACTOR / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        self.assertEqual(list(events["actorChargeEvents"]), ["job"])
        self.assertEqual(events["actorChargeEvents"]["job"]["eventPriceUsd"], spend.PRICES_USD["job"])

        actor = json.loads((_ACTOR / ".actor" / "actor.json").read_text(encoding="utf-8"))
        self.assertEqual(actor["name"], "ats-jobs")
        self.assertNotIn("dockerContextDir", actor)
        self.assertIn("timeoutSecs", actor["defaultRunOptions"])
        docker = (_ACTOR / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("ACTOR_PATH_IN_DOCKER_CONTEXT", docker)
        self.assertIn("CJM_REPO_ROOT=/usr/src/app/platform_bundle", docker)
        bundle = (_ACTOR / "bundle.txt").read_text(encoding="utf-8")
        self.assertIn("scripts/apify-scripts/runtime.py", bundle)
        self.assertIn("scripts/apify-scripts/access.py", bundle)
        self.assertTrue((_ACTOR / "fixtures" / "budget.json").is_file())
        self.assertTrue((_ACTOR / "fixtures" / "INPUT.json").is_file())
        requirements = (_ACTOR / "requirements.txt").read_text(encoding="utf-8").splitlines()
        packages = [line for line in requirements if line.strip() and not line.startswith("#")]
        self.assertFalse(any("playwright" in line for line in packages))
        self.assertNotIn("playwright", docker.split("FROM", 1)[1].splitlines()[0])


class TestMapping(unittest.TestCase):
    def test_four_ats_map_to_one_shape(self):
        with self.assertLogs("apify", level="CRITICAL") as caught:
            rows, summary, _new, scripted, _sleeps = _run(**_base_input())
        found = _found(rows)
        self.assertEqual(len(found), 12)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["mergedDuplicates"], 1)
        self.assertEqual({row["ats"] for row in found}, {"greenhouse", "lever", "ashby", "workable"})
        keys = set(found[0])
        for row in found:
            self.assertEqual(set(row), keys)
            self.assertTrue(row["ok"])
            self.assertEqual(row["decision"], "new")
            self.assertEqual(row["firstSeen"], NOW)
            self.assertEqual(row["scrapedAt"], NOW)
            self.assertTrue(row["url"].startswith("https://"))
            self.assertTrue(mapping.billable_row(row))
        self.assertEqual(len(summary["companies"]), 4)
        self.assertTrue(any("ATS board greenhouse/exampleco" in line for line in caught.output))
        self.assertTrue(any("ATS jobs SUMMARY" in line for line in caught.output))
        self.assertIn("content=true", scripted.board_urls()[0])
        self.assertIn("includeCompensation=true", scripted.board_urls()[2])

    def test_greenhouse_fields(self):
        rows, *_ = _run(**_base_input(lever=[], ashby=[], workable=[]))
        jobs = _by_id(rows)
        self.assertEqual(set(jobs), {"1001", "1002", "1003"})
        sse = jobs["1001"]
        self.assertEqual(sse["company"], "Example Co")
        self.assertEqual(sse["companySlug"], "exampleco")
        self.assertEqual(sse["title"], "Senior Software Engineer, Payments")
        self.assertEqual(sse["location"], "San Francisco, CA")
        self.assertEqual(sse["locations"], ["San Francisco, CA", "San Francisco, CA, United States"])
        self.assertEqual(sse["department"], "Engineering")
        self.assertEqual(sse["postedDate"], "2026-10-20T13:00:00+00:00")
        self.assertEqual(sse["url"], "https://boards.greenhouse.io/exampleco/jobs/1001")
        self.assertEqual(sse["workplaceType"], "hybrid")
        self.assertFalse(sse["remote"])
        self.assertIsNone(jobs["1003"]["salary"])

    def test_lever_fields(self):
        rows, *_ = _run(**_base_input(greenhouse=[], ashby=[], workable=[]))
        jobs = _by_id(rows)
        backend = jobs["0b8c7a52-1111-4f3e-9a63-1e3c5b2d0001"]
        self.assertEqual(backend["company"], "examplelever")
        self.assertEqual(backend["title"], "Backend Engineer")
        self.assertEqual(backend["locations"], ["London, United Kingdom", "Remote - UK"])
        self.assertEqual(backend["department"], "Engineering")
        self.assertEqual(backend["postedDate"], _utc(1790000000000))
        self.assertEqual(backend["url"], "https://jobs.lever.co/examplelever/0b8c7a52-1111-4f3e-9a63-1e3c5b2d0001")

    def test_lever_eu_host(self):
        rows, _summary, _new, scripted, _sleeps = _run(leverEu=["exampleeu"])
        self.assertEqual(len(_found(rows)), 3)
        self.assertTrue(all(row["ats"] == "lever" for row in _found(rows)))
        self.assertTrue(scripted.board_urls()[0].startswith("https://api.eu.lever.co/v0/postings/exampleeu"))

    def test_ashby_fields(self):
        rows, *_ = _run(**_base_input(greenhouse=[], lever=[], workable=[]))
        jobs = _by_id(rows)
        self.assertEqual(len(jobs), 3)
        self.assertNotIn("7458d4e9-da2e-47bd-98cb-adfda43d4203", jobs)
        manager = jobs["7458d4e9-da2e-47bd-98cb-adfda43d4201"]
        self.assertEqual(manager["locations"], ["Remote - European Union", "Spain", "Germany"])
        self.assertEqual(manager["postedDate"], "2026-10-01T14:29:08+00:00")
        self.assertEqual(manager["department"], "Engineering")
        support = jobs["https://jobs.ashbyhq.com/exampleashby/support-specialist"]
        self.assertEqual(support["department"], "Support")
        self.assertEqual(support["workplaceType"], "onsite")

    def test_workable_fields(self):
        rows, *_ = _run(**_base_input(greenhouse=[], lever=[], ashby=[]))
        jobs = _by_id(rows)
        emea = jobs["81B46579FE"]
        self.assertEqual(emea["company"], "Example Workable Co")
        self.assertEqual(emea["location"], "Paris, Île-de-France, France")
        self.assertIn("Remote", emea["locations"])
        self.assertEqual(emea["postedDate"], "2026-05-29")
        self.assertEqual(emea["department"], "Open Source")
        self.assertEqual(emea["url"], "https://apply.workable.com/j/81B46579FE")
        self.assertIsNone(emea["salary"])


class TestSalary(unittest.TestCase):
    def setUp(self):
        rows, *_ = _run(**_base_input())
        self.jobs = _by_id(rows)

    def test_greenhouse_pay_range_and_content_text(self):
        self.assertEqual(self.jobs["1001"]["salary"], {
            "min": 180000, "max": 220000, "currency": "USD", "interval": None,
            "raw": "SF Zone: USD 180,000 - USD 220,000",
        })
        annual = mapping._greenhouse_salary({"pay_input_ranges": [
            {"min_cents": 5800000, "max_cents": 6800000, "currency_type": "CAD", "title": "Canada Annual Pay Range"},
        ]})
        self.assertEqual((annual["min"], annual["max"], annual["currency"], annual["interval"]), (58000, 68000, "CAD", "year"))
        self.assertEqual(self.jobs["1002"]["salary"], {
            "min": 150000, "max": 180000, "currency": "USD", "interval": "year",
            "raw": "$150,000 — $180,000 USD",
        })

    def test_lever_range_and_description(self):
        self.assertEqual(self.jobs["0b8c7a52-1111-4f3e-9a63-1e3c5b2d0001"]["salary"], {
            "min": 70000, "max": 90000, "currency": "GBP", "interval": "year",
            "raw": "GBP 70,000 - GBP 90,000 per year",
        })
        self.assertEqual(self.jobs["0b8c7a52-2222-4f3e-9a63-1e3c5b2d0002"]["salary"], {
            "min": 85000, "max": 105000, "currency": "USD", "interval": "year",
            "raw": "$85,000 - $105,000",
        })
        self.assertIsNone(self.jobs["0b8c7a52-3333-4f3e-9a63-1e3c5b2d0003"]["salary"])

    def test_ashby_components_and_summary_text(self):
        self.assertEqual(self.jobs["7458d4e9-da2e-47bd-98cb-adfda43d4201"]["salary"], {
            "min": 150000, "max": 250000, "currency": "EUR", "interval": "year", "raw": "€150K - €250K",
        })
        self.assertEqual(self.jobs["7458d4e9-da2e-47bd-98cb-adfda43d4202"]["salary"], {
            "min": 140000, "max": 170000, "currency": "USD", "interval": None, "raw": "$140K - $170K",
        })

    def test_free_text_parser(self):
        self.assertEqual(mapping.parse_salary_text("Pay $45 - $60 per hour"), {
            "min": 45, "max": 60, "currency": "USD", "interval": "hour", "raw": "$45 - $60",
        })
        self.assertEqual(mapping.parse_salary_text("£40k to £55k annually")["currency"], "GBP")
        self.assertEqual(mapping.parse_salary_text("£40k to £55k annually")["min"], 40000)
        self.assertEqual(mapping.parse_salary_text("EUR 60,000 - 80,000 a year")["max"], 80000)
        self.assertIsNone(mapping.parse_salary_text("Competitive salary and equity"))
        self.assertIsNone(mapping.parse_salary_text("$200,000 - $100,000"))


class TestRemote(unittest.TestCase):
    def setUp(self):
        rows, *_ = _run(**_base_input())
        self.jobs = _by_id(rows)

    def test_flags_from_each_ats(self):
        remote = {job_id for job_id, row in self.jobs.items() if row["remote"]}
        self.assertEqual(remote, {
            "1002",
            "0b8c7a52-2222-4f3e-9a63-1e3c5b2d0002",
            "7458d4e9-da2e-47bd-98cb-adfda43d4201",
            "81B46579FE",
            "19A136F8E2",
        })
        self.assertEqual(self.jobs["7458d4e9-da2e-47bd-98cb-adfda43d4202"]["workplaceType"], "hybrid")
        self.assertFalse(self.jobs["0b8c7a52-1111-4f3e-9a63-1e3c5b2d0001"]["remote"])

    def test_location_text_when_no_workplace_field(self):
        self.assertTrue(mapping._remote("", ["Remote - US"]))
        self.assertFalse(mapping._remote("", ["Austin, TX"]))
        self.assertFalse(mapping._remote("onsite", ["Remote - US"]))


class TestFilters(unittest.TestCase):
    def test_keyword_matches_title_or_department(self):
        rows, summary, *_ = _run(**_base_input(keywords=["engineer"]))
        self.assertEqual(set(_by_id(rows)), {
            "1001", "1002",
            "0b8c7a52-1111-4f3e-9a63-1e3c5b2d0001",
            "81B46579FE", "19A136F8E2",
        })
        self.assertEqual(summary["filteredOut"], 7)

        rows, *_ = _run(**_base_input(keywords=["engineering"]))
        self.assertIn("7458d4e9-da2e-47bd-98cb-adfda43d4201", _by_id(rows))

        rows, *_ = _run(**_base_input(keywords=["SALES"]))
        self.assertEqual(set(_by_id(rows)), {"1003"})

    def test_keyword_is_whole_word(self):
        config = mapping.actor_input_to_config({"greenhouse": ["x"], "keywords": ["ai", "go", "C++", ".NET"]})

        def keep(title):
            return mapping.keep_job({"title": title, "department": "", "locations": []}, config)

        self.assertFalse(keep("Open Source Maintainer"))
        self.assertFalse(keep("Google Ads Specialist"))
        self.assertTrue(keep("AI Researcher"))
        self.assertTrue(keep("Backend Engineer (Go)"))
        self.assertTrue(keep("Senior C++ Developer"))
        self.assertTrue(keep(".NET Engineer"))

    def test_location_remote_matches_the_remote_flag(self):
        config = mapping.actor_input_to_config({"greenhouse": ["x"], "location": "Remote"})
        flagged = {"title": "Engineer", "locations": ["Berlin, Germany"], "remote": True}
        office = {"title": "Engineer", "locations": ["Berlin, Germany"], "remote": False}
        self.assertTrue(mapping.keep_job(flagged, config))
        self.assertFalse(mapping.keep_job(office, config))
        berlin = mapping.actor_input_to_config({"greenhouse": ["x"], "location": "berlin"})
        self.assertTrue(mapping.keep_job(office, berlin))

    def test_location_substring_any_location(self):
        rows, *_ = _run(**_base_input(location="PARIS"))
        self.assertEqual(set(_by_id(rows)), {"81B46579FE", "C0FFEE1234"})
        rows, *_ = _run(**_base_input(location="remote - uk, toronto"))
        self.assertEqual(set(_by_id(rows)), {
            "0b8c7a52-1111-4f3e-9a63-1e3c5b2d0001",
            "https://jobs.ashbyhq.com/exampleashby/support-specialist",
        })

    def test_remote_select(self):
        rows, *_ = _run(**_base_input(remote="remote"))
        self.assertEqual(len(_found(rows)), 5)
        self.assertTrue(all(row["remote"] for row in _found(rows)))
        rows, *_ = _run(**_base_input(remote="exclude"))
        self.assertEqual(len(_found(rows)), 7)
        self.assertFalse(any(row["remote"] for row in _found(rows)))

    def test_nothing_matches_is_one_free_row(self):
        rows, summary, *_ = _run(**_base_input(keywords=["astronaut"]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sourceStatus"], "not_found")
        self.assertFalse(mapping.billable_row(rows[0]))
        self.assertEqual(summary["status"], "not_found")
        self.assertEqual(summary["billedJobs"], 0)


class TestDedupeAndState(unittest.TestCase):
    def test_dedupe_within_a_run(self):
        rows, summary, *_ = _run(greenhouse=["exampleco", "https://boards.greenhouse.io/ExampleCo"])
        ids = [row["jobId"] for row in _found(rows)]
        self.assertEqual(sorted(ids), ["1001", "1002", "1003"])
        self.assertEqual(summary["mergedDuplicates"], 1)
        self.assertEqual(summary["duplicateCompanies"], 1)

    def test_new_since_last_run_skips_seen_jobs(self):
        rows, _summary, new_seen, *_ = _run(**_base_input())
        self.assertEqual(len(new_seen), 12)
        self.assertIn("greenhouse:exampleco:1001", new_seen)
        seen = state_mod.merge_state({}, new_seen)

        rows, summary, again, *_ = _run(seen=seen, **_base_input(newSinceLastRun=True))
        self.assertEqual(_found(rows), [])
        self.assertEqual(summary["skippedSeen"], 12)
        self.assertEqual(again, {})
        self.assertIn("No new jobs since the last run", rows[0]["error"])

        partial = {key: value for key, value in seen.items() if not key.startswith("workable:")}
        rows, summary, again, *_ = _run(seen=partial, **_base_input(newSinceLastRun=True))
        self.assertEqual({row["ats"] for row in _found(rows)}, {"workable"})
        self.assertEqual(len(again), 3)

    def test_repeat_rows_keep_first_seen_when_not_filtering(self):
        seen = {"greenhouse:exampleco:1001": "2026-10-01T00:00:00+00:00"}
        rows, summary, new_seen, *_ = _run(seen=seen, greenhouse=["exampleco"])
        jobs = _by_id(rows)
        self.assertEqual(jobs["1001"]["decision"], "repeat")
        self.assertEqual(jobs["1001"]["firstSeen"], "2026-10-01T00:00:00+00:00")
        self.assertEqual(jobs["1002"]["decision"], "new")
        self.assertNotIn("greenhouse:exampleco:1001", new_seen)
        self.assertEqual(summary["repeatJobs"], 1)

    def test_merge_state_prunes_blank_then_oldest_first(self):
        seen = {
            "a": "2026-10-01T00:00:00+00:00",
            "b": "",
            "c": "2026-11-01T00:00:00+00:00",
        }
        merged = state_mod.merge_state(seen, {"d": "2026-11-02T00:00:00+00:00", "a": "2026-12-01T00:00:00+00:00"}, max_keys=3)
        self.assertEqual(set(merged), {"a", "c", "d"})
        self.assertEqual(merged["a"], "2026-10-01T00:00:00+00:00")
        merged = state_mod.merge_state(merged, {}, max_keys=2)
        self.assertEqual(set(merged), {"c", "d"})

    def test_state_round_trip_through_named_store(self):
        stores = {}
        actor, _scripted = _run_main(_base_input(newSinceLastRun=True), stores=stores)
        self.assertEqual(actor.opened, ["ats-jobs-state"])
        saved = stores["ats-jobs-state"]["SEEN"]
        self.assertEqual(saved["version"], 1)
        self.assertEqual(len(saved["jobs"]), 12)
        self.assertEqual(len(actor.charges), 12)

        second, _scripted = _run_main(_base_input(newSinceLastRun=True), stores=stores)
        self.assertEqual(second.charges, [])
        self.assertEqual([row["sourceStatus"] for row in second.pushed], ["not_found"])
        self.assertEqual(second.values["SUMMARY"]["skippedSeen"], 12)
        self.assertEqual(second.values["SUMMARY"]["stateKeys"], 12)

    def test_jobs_held_back_by_max_items_stay_new(self):
        stores = {}
        first, _ = _run_main(_base_input(newSinceLastRun=True, maxItems=5), stores=stores)
        self.assertEqual(len(first.pushed), 5)
        self.assertEqual(len(stores["ats-jobs-state"]["SEEN"]["jobs"]), 5)
        second, _ = _run_main(_base_input(newSinceLastRun=True, maxItems=100), stores=stores)
        self.assertEqual(len(second.pushed), 7)
        self.assertFalse({r["jobId"] for r in first.pushed} & {r["jobId"] for r in second.pushed})


class TestMaxItems(unittest.TestCase):
    def test_exact_cap_across_companies(self):
        for cap in (1, 4, 7, 12):
            rows, summary, *_ = _run(**_base_input(maxItems=cap))
            self.assertEqual(len(_found(rows)), cap, cap)
            self.assertEqual(summary["truncated"], cap < 12, cap)

    def test_cap_stops_fetching_later_boards(self):
        rows, _summary, _new, scripted, _sleeps = _run(**_base_input(maxItems=3))
        self.assertEqual(len(_found(rows)), 3)
        self.assertEqual(len(scripted.board_urls()), 1)

    def test_main_pushes_and_charges_exactly_max_items(self):
        actor, _ = _run_main(_base_input(maxItems=4))
        self.assertEqual(len(actor.pushed), 4)
        self.assertEqual(actor.charges, ["job"] * 4)
        self.assertEqual(actor.values["SUMMARY"]["billedJobs"], 4)


class TestBlocksAndMisses(unittest.TestCase):
    def test_403_blocks_only_that_host(self):
        scripted = Scripted(blocked={"api.lever.co": {"status": 403, "text": "Forbidden", "content_type": "text/plain"}})
        rows, summary, *_ = _run(scripted, **_base_input(lever=["examplelever", "secondlever"]))
        blocked = [row for row in rows if row["sourceStatus"] == "blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["ats"], "lever")
        self.assertEqual(blocked[0]["decision"], "stopped")
        self.assertIn("HTTP 403", blocked[0]["error"])
        self.assertFalse(mapping.billable_row(blocked[0]))
        self.assertEqual({row["ats"] for row in _found(rows)}, {"greenhouse", "ashby", "workable"})
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["stopped"], "blocked")
        self.assertEqual(summary["skippedBlockedHost"], 1)
        self.assertFalse(any("secondlever" in url for url in scripted.urls))
        skipped = [r for r in summary["companies"] if r["slug"] == "secondlever"]
        self.assertEqual(skipped[0]["status"], "skipped_blocked_host")

    def test_429_after_retries_and_challenge_html_are_blocks(self):
        for response in (
            {"status": 429, "text": "Too Many Requests", "content_type": "text/plain"},
            {"status": 200, "text": _text("challenge.html"), "content_type": "text/html"},
            {"status": 200, "text": "<html><body>Sign in</body></html>", "content_type": "text/html"},
        ):
            scripted = Scripted(blocked={"boards-api.greenhouse.io/v1": response})
            rows, summary, *_ = _run(scripted, greenhouse=["exampleco", "otherco"], maxItems=100)
            self.assertEqual([row["sourceStatus"] for row in rows], ["blocked"], response["status"])
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["billedJobs"], 0)
            self.assertEqual(len(scripted.board_urls()), 1)

    def test_blocked_run_through_main_exits_cleanly_without_charge(self):
        scripted = Scripted(blocked={"boards-api.greenhouse.io/v1": {"status": 401, "text": "", "content_type": ""}})
        actor, _ = _run_main({"greenhouse": ["exampleco"], "maxSpendUsd": 5}, scripted=scripted)
        self.assertEqual([row["sourceStatus"] for row in actor.pushed], ["blocked"])
        self.assertEqual(actor.charges, [])
        self.assertEqual(actor.values["SUMMARY"]["status"], "blocked")
        self.assertEqual(actor.values["SUMMARY"]["spendUsd"], 0)

    def test_404_is_not_found_and_the_run_continues(self):
        rows, summary, *_ = _run(**_base_input(greenhouse=["nosuchboard", "exampleco"], workable=["ghostco"]))
        misses = [row for row in rows if row["sourceStatus"] == "not_found"]
        self.assertEqual([(row["ats"], row["companySlug"]) for row in misses], [("greenhouse", "nosuchboard"), ("workable", "ghostco")])
        self.assertTrue(all(not mapping.billable_row(row) for row in misses))
        self.assertIn("HTTP 404", misses[0]["error"])
        self.assertEqual(len(_found(rows)), 9)
        self.assertEqual({row["ats"] for row in _found(rows)}, {"greenhouse", "lever", "ashby"})
        self.assertEqual(summary["notFound"], 2)
        self.assertEqual(summary["status"], "ok")

    def test_invalid_json_and_bad_slug_are_free_error_rows(self):
        scripted = Scripted(blocked={"api.ashbyhq.com": {"status": 200, "text": "not json", "content_type": "text/plain"}})
        rows, summary, *_ = _run(scripted, **_base_input(workable=["examplewk", "bad slug!"]))
        errors = [row for row in rows if row["sourceStatus"] == "error"]
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("invalid_json" in row["error"] for row in errors))
        self.assertTrue(any("bad slug!" in row["error"] for row in errors))
        self.assertEqual(len(_found(rows)), 9)

    def test_robots_rules_and_unavailable_host(self):
        scripted = Scripted(robots={
            "api.lever.co": {"status": 200, "text": "User-agent: *\nDisallow: /v0/\n", "content_type": "text/plain"},
            "api.ashbyhq.com": {"status": 401, "text": "Unauthorized", "content_type": "text/plain"},
            "apply.workable.com": {"status": 503, "text": "", "content_type": "text/plain"},
        })
        rows, summary, *_ = _run(scripted, **_base_input())
        status = {row["ats"]: row["sourceStatus"] for row in rows if row["sourceStatus"] != "found"}
        self.assertEqual(status, {"lever": "robots_disallowed", "workable": "error"})
        self.assertEqual({row["ats"] for row in _found(rows)}, {"greenhouse", "ashby"})
        self.assertFalse(any("api.lever.co/v0" in url for url in scripted.urls))
        self.assertEqual(summary["robots"], 1)

    def test_requests_are_paced(self):
        _rows, _summary, _new, scripted, sleeps = _run(**_base_input())
        self.assertEqual(len(sleeps), len(scripted.urls) - 1)
        self.assertTrue(all(1.0 <= value <= 2.0 for value in sleeps))


class TestCharging(unittest.TestCase):
    def test_only_found_rows_are_charged(self):
        scripted = Scripted(blocked={"apply.workable.com/api": {"status": 403, "text": "", "content_type": ""}})
        actor, _ = _run_main(_base_input(greenhouse=["nosuchboard", "exampleco"]), scripted=scripted)
        statuses = [row["sourceStatus"] for row in actor.pushed]
        self.assertEqual(statuses.count("found"), 9)
        self.assertEqual(statuses.count("not_found"), 1)
        self.assertEqual(statuses.count("blocked"), 1)
        self.assertEqual(actor.charges, ["job"] * 9)
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["billedJobs"], 9)
        self.assertEqual(summary["spendUsd"], 0.018)
        self.assertFalse(summary["chargeCapped"])

    def test_max_spend_stops_pushing_unbilled_jobs(self):
        actor, _ = _run_main(_base_input(maxSpendUsd=0.01))
        self.assertEqual(len([r for r in actor.pushed if r["sourceStatus"] == "found"]), 5)
        self.assertEqual(actor.charges, ["job"] * 5)
        capped = [r for r in actor.pushed if r["sourceStatus"] == "spend_capped"]
        self.assertEqual(len(capped), 1)
        self.assertIn("7 matching job(s)", capped[0]["error"])
        self.assertFalse(mapping.billable_row(capped[0]))
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["found"], 5)
        self.assertEqual(summary["billedJobs"], 5)
        self.assertEqual(summary["heldBackJobs"], 7)
        self.assertEqual(summary["spendUsd"], 0.01)
        self.assertTrue(summary["chargeCapped"])
        self.assertTrue(summary["truncated"])

    def test_zero_spend_gives_no_free_jobs(self):
        actor, _ = _run_main(_base_input(maxSpendUsd=0))
        self.assertEqual(actor.charges, [])
        self.assertEqual([r["sourceStatus"] for r in actor.pushed], ["spend_capped"])
        summary = actor.values["SUMMARY"]
        self.assertTrue(summary["chargeCapped"])
        self.assertEqual(summary["status"], "spend_capped")

    def test_platform_charge_limit_stops_pushing(self):
        actor, _ = _run_main(_base_input(), limit_after=3)
        self.assertEqual(len(actor.charges), 3)
        self.assertEqual(len([r for r in actor.pushed if r["sourceStatus"] == "found"]), 3)
        self.assertEqual(actor.values["SUMMARY"]["heldBackJobs"], 9)

    def test_capped_jobs_stay_new_for_the_next_run(self):
        stores = {}
        first, _ = _run_main(_base_input(newSinceLastRun=True, maxSpendUsd=0.01), stores=stores)
        self.assertEqual(len(stores["ats-jobs-state"]["SEEN"]["jobs"]), 5)
        second, _ = _run_main(_base_input(newSinceLastRun=True), stores=stores)
        first_ids = {r["jobId"] for r in first.pushed if r["sourceStatus"] == "found"}
        second_ids = {r["jobId"] for r in second.pushed if r["sourceStatus"] == "found"}
        self.assertEqual(len(second_ids), 7)
        self.assertFalse(first_ids & second_ids)

    def test_push_failure_is_not_recorded_as_seen(self):
        stores = {}
        calls = {"n": 0}
        original = FakeActor.push_data

        async def flaky(self, row):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("dataset unavailable")
            await original(self, row)

        with mock.patch.object(FakeActor, "push_data", flaky):
            actor, _ = _run_main(_base_input(newSinceLastRun=True), stores=stores)
        self.assertEqual(actor.charges, ["job"] * 2)
        self.assertEqual(len(stores["ats-jobs-state"]["SEEN"]["jobs"]), 2)
        self.assertEqual(actor.values["SUMMARY"]["stopped"], "pushFailed")

    def test_micro_dollar_ledger(self):
        ledger = spend.JobLedger(0.005)
        self.assertEqual(ledger.affordable("job", 10), 2)
        self.assertTrue(ledger.can("job"))
        ledger.commit("job")
        ledger.commit("job")
        self.assertFalse(ledger.can("job"))
        self.assertEqual(ledger.spend_usd, 0.004)
        self.assertFalse(ledger.can("proxy"))


if __name__ == "__main__":
    unittest.main()
