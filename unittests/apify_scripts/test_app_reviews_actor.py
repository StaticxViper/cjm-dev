"""
Unit tests for scripts/apify-scripts/app-reviews.

Run from repo root:
    python -m pytest unittests/apify_scripts/test_app_reviews_actor.py -q

Fixtures only. The feed fetch is scripted and ``apify.Actor`` is a stand-in,
so these tests never call itunes.apple.com, play.google.com, or Apify.
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
_ACTOR = _REPO / "scripts" / "apify-scripts" / "app-reviews"
_SRC = _ACTOR / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "app_reviews"
_ACTOR_MODULES = ("runtime", "spend", "sources", "fetch", "mapping", "main")

NOW = "2026-11-03T12:00:00+00:00"
FACEBOOK = "284882215"


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


def _rss(reviews):
    entries = [{
        "im:name": {"label": "Many"},
        "title": {"label": "Many"},
        "id": {"label": "https://apps.apple.com/us/app/many/id777"},
    }]
    for index in reviews:
        entries.append({
            "im:rating": {"label": "5"},
            "id": {"label": str(index)},
            "title": {"label": "Fine"},
            "content": {"label": "A review", "attributes": {"type": "text"}},
            "im:version": {"label": "1"},
            "author": {"name": {"label": "Pat"}},
            "updated": {"label": "2026-10-01T00:00:00Z"},
            "link": {"attributes": {"href": f"https://itunes.apple.com/us/review?id={index}"}},
        })
    return json.dumps({"feed": {"entry": entries}})


def _lookup(name="Many", url="https://apps.apple.com/us/app/many/id777"):
    return json.dumps({"resultCount": 1, "results": [{"trackName": name, "trackViewUrl": url}]})


class Scripted:
    """Answers iTunes URLs from fixtures. Unknown apps are an empty lookup."""

    def __init__(self, blocked=None, robots=None, pages=None, lookups=None):
        self.blocked = blocked or {}
        self.robots = robots or {}
        self.pages = pages or {}
        self.lookups = lookups or {}
        self.urls = []

    def direct(self, url):
        self.urls.append(url)
        parsed = urlparse(url)
        if parsed.path == "/robots.txt":
            if parsed.netloc in self.robots:
                body = self.robots[parsed.netloc]
                if isinstance(body, str):
                    return {"status": 200, "text": body, "content_type": "text/plain"}
                return dict(body)
            return {"status": 200, "text": "User-agent: *\nAllow: /\n", "content_type": "text/plain"}
        for needle, response in self.blocked.items():
            if needle in url:
                return dict(response)
        if parsed.path == "/lookup":
            app_id = (parse_qs(parsed.query).get("id") or [""])[0]
            payload = self.lookups.get(app_id)
            if payload is None:
                payload = _text("lookup.json") if app_id == FACEBOOK else _text("lookup_empty.json")
            if isinstance(payload, dict):
                return dict(payload)
            return {"status": 200, "text": payload, "content_type": "application/json"}
        match = __import__("re").search(r"/customerreviews/page=(\d+)/id=(\d+)/", parsed.path)
        if match:
            page, app_id = int(match.group(1)), match.group(2)
            payload = self.pages.get((app_id, page))
            if payload is None:
                if app_id == FACEBOOK and page == 1:
                    payload = _text("rss_page1.json")
                elif app_id == FACEBOOK and page == 2:
                    payload = _text("rss_page2.json")
                else:
                    payload = _text("rss_empty.json")
            if isinstance(payload, dict):
                return dict(payload)
            return {"status": 200, "text": payload, "content_type": "application/json"}
        return {"status": 404, "text": "Not Found", "content_type": "text/plain"}


def _run(scripted=None, **actor_input):
    scripted = scripted or Scripted()
    config = mapping.actor_input_to_config(actor_input)
    sleeps = []
    fetch = fetch_mod.build_fetch(config, scripted.direct, sleep=sleeps.append)
    rows, summary = mapping.scrape(config, fetch, now=NOW)
    return rows, summary, scripted, sleeps


def _ok(rows):
    return [row for row in rows if row.get("sourceStatus") == "ok"]


def _run_main(actor_input, scripted=None, limit_after=None, charge=None):
    scripted = scripted or Scripted()
    actor = FakeActor(actor_input, limit_after=limit_after)
    if charge is not None:
        actor.charge = charge
    fake_apify = types.ModuleType("apify")
    fake_apify.Actor = actor

    def live(config):
        return fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _s: None)

    with mock.patch.dict(sys.modules, {"apify": fake_apify}), \
            mock.patch.object(main_mod, "Actor", actor), \
            mock.patch.object(main_mod, "make_live_fetch", live):
        asyncio.run(main_mod.main())
    return actor, scripted


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, headers=None):
        self.urls.append(url)
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
        config = mapping.actor_input_to_config({"appStoreIds": ["1"]})
        self.assertEqual(config["country"], "us")
        self.assertIsNone(config["since"])
        self.assertFalse(config["sentiment"])
        self.assertEqual(config["max_items"], 100)
        self.assertEqual(config["delay_seconds"], 1.0)
        self.assertEqual(config["max_spend_usd"], 5.0)
        self.assertEqual(config["error"], "")

        bounded = mapping.actor_input_to_config({
            "appStoreIds": ["1"],
            "maxItems": 99999,
            "delaySeconds": 0,
            "maxSpendUsd": 1000,
            "country": "US",
            "sentiment": "false",
        })
        self.assertEqual(bounded["max_items"], 1000)
        self.assertEqual(bounded["delay_seconds"], 1.0)
        self.assertEqual(bounded["max_spend_usd"], 100.0)
        self.assertEqual(bounded["country"], "us")
        self.assertFalse(bounded["sentiment"])

    def test_url_id_extraction_and_duplicates(self):
        config = mapping.actor_input_to_config({
            "appStoreIds": [
                "https://apps.apple.com/us/app/facebook/id284882215",
                "https://itunes.apple.com/lookup?id=284882215&country=gb",
                "id284882215",
                "999",
            ],
        })
        self.assertEqual(config["app_ids"], [FACEBOOK, "999"])
        self.assertEqual(config["duplicate_ids"], 2)
        self.assertEqual(
            sources.lookup_url(FACEBOOK, "us"),
            "https://itunes.apple.com/lookup?id=284882215&country=us",
        )
        self.assertEqual(
            sources.reviews_url(FACEBOOK, "us", 2),
            "https://itunes.apple.com/us/rss/customerreviews/page=2/id=284882215/sortby=mostrecent/json",
        )

    def test_invalid_country_is_one_error_and_does_not_fetch(self):
        rows, summary, scripted, _sleeps = _run(appStoreIds=[FACEBOOK], country="usa")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sourceStatus"], "error")
        self.assertIn("country", rows[0]["error"])
        self.assertEqual(scripted.urls, [])
        self.assertEqual(summary["billedReviews"], 0)

    def test_bad_since_is_one_error(self):
        rows, _summary, scripted, _sleeps = _run(appStoreIds=[FACEBOOK], since="10/01/2026")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sourceStatus"], "error")
        self.assertIn("since", rows[0]["error"])
        self.assertEqual(scripted.urls, [])

    def test_schema_files_declare_the_contract(self):
        form = json.loads((_ACTOR / ".actor" / "input_schema.json").read_text(encoding="utf-8"))
        props = form["properties"]
        for key in ("appStoreIds", "playIds", "country", "since", "maxItems", "sentiment", "delaySeconds", "maxSpendUsd"):
            self.assertIn(key, props)
        for key in ("appStoreIds", "playIds"):
            self.assertEqual(props[key]["editor"], "stringList")
            self.assertEqual(props[key]["maxItems"], 20)
        self.assertEqual(props["country"]["editor"], "textfield")
        self.assertEqual(props["maxItems"]["maximum"], 1000)
        for dropped in ("maxProxyCostUsd", "allowCaptcha", "proxyConfiguration", "proxyGroups", "headless"):
            self.assertNotIn(dropped, props)

        dataset = json.loads((_ACTOR / ".actor" / "dataset_schema.json").read_text(encoding="utf-8"))
        fields = dataset["fields"]["fields"]
        for key in ("app", "appId", "store", "country", "reviewId", "rating", "title", "text",
                    "version", "date", "author", "url", "sentiment", "sentimentScore",
                    "sourceStatus", "decision", "ok", "error", "scrapedAt"):
            self.assertIn(key, fields)
        self.assertEqual(fields["sentimentScore"]["type"], "number")
        self.assertEqual(fields["rating"]["type"], "integer")
        self.assertEqual(set(dataset["views"]), {"overview", "detail"})

        events = json.loads((_ACTOR / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        self.assertEqual(set(events["actorChargeEvents"]), {"review", "sentiment"})
        self.assertEqual(events["actorChargeEvents"]["review"]["eventPriceUsd"], spend.PRICES_USD["review"])
        self.assertEqual(events["actorChargeEvents"]["sentiment"]["eventPriceUsd"], spend.PRICES_USD["sentiment"])
        self.assertTrue(events["actorChargeEvents"]["review"]["isPrimaryEvent"])
        self.assertFalse(events["actorChargeEvents"]["sentiment"]["isPrimaryEvent"])
        for banned in ("proxy", "captcha"):
            self.assertNotIn(banned, events["actorChargeEvents"])

        actor = json.loads((_ACTOR / ".actor" / "actor.json").read_text(encoding="utf-8"))
        self.assertEqual(actor["name"], "app-reviews")
        self.assertNotIn("dockerContextDir", actor)
        self.assertEqual(actor["defaultRunOptions"]["timeoutSecs"], 1800)
        self.assertEqual(actor["defaultMemoryMbytes"], 512)
        docker = (_ACTOR / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("ACTOR_PATH_IN_DOCKER_CONTEXT", docker)
        self.assertIn("CJM_REPO_ROOT=/usr/src/app/platform_bundle", docker)
        self.assertIn("apify/actor-python:3.12", docker)
        bundle = (_ACTOR / "bundle.txt").read_text(encoding="utf-8")
        self.assertIn("scripts/apify-scripts/runtime.py", bundle)
        self.assertIn("scripts/apify-scripts/access.py", bundle)
        self.assertIn("scripts/lead_automation/crm_enrich_robots.py", bundle)
        self.assertTrue((_ACTOR / "fixtures" / "budget.json").is_file())
        self.assertTrue((_ACTOR / "fixtures" / "INPUT.json").is_file())
        requirements = (_ACTOR / "requirements.txt").read_text(encoding="utf-8").splitlines()
        packages = [line for line in requirements if line.strip() and not line.startswith("#")]
        self.assertFalse(any("playwright" in line.lower() for line in packages))


class TestParse(unittest.TestCase):
    def test_rss_skips_the_app_entry_and_dedupes(self):
        rows, summary, scripted, _sleeps = _run(appStoreIds=[FACEBOOK])
        found = _ok(rows)
        self.assertEqual([row["reviewId"] for row in found], ["1001", "1002"])
        self.assertEqual(summary["mergedDuplicates"], 1)
        self.assertTrue(any("page=2" in url for url in scripted.urls))
        self.assertFalse(any("page=3" in url for url in scripted.urls))
        first = found[0]
        self.assertEqual(first["app"], "Facebook")
        self.assertEqual(first["appId"], FACEBOOK)
        self.assertEqual(first["store"], "appstore")
        self.assertEqual(first["country"], "us")
        self.assertEqual(first["rating"], 5)
        self.assertIsInstance(first["rating"], int)
        self.assertEqual(first["title"], "Love this app")
        self.assertEqual(first["text"], "Really great and helpful every day.")
        self.assertEqual(first["version"], "532.0")
        self.assertEqual(first["date"], "2026-10-20T08:15:00-07:00")
        self.assertEqual(first["author"], "Alex Rivera")
        self.assertEqual(first["url"], "https://itunes.apple.com/us/review?id=284882215&type=Purple%20Software")
        self.assertEqual(first["sourceStatus"], "ok")
        self.assertEqual(first["decision"], "review")
        self.assertTrue(first["ok"])
        self.assertEqual(first["scrapedAt"], NOW)
        self.assertNotIn("Facebook", [row["title"] for row in found])
        self.assertTrue(mapping.billable_row(first))

    def test_calendar_day_uses_the_offset(self):
        self.assertEqual(mapping.calendar_day("2026-01-15T23:30:00-07:00"), "2026-01-15")
        self.assertEqual(mapping.calendar_day("2026-01-16T01:00:00+00:00"), "2026-01-16")
        self.assertEqual(mapping.calendar_day("2026-01-16T01:00:00"), "2026-01-16")
        self.assertEqual(mapping.calendar_day("2026-01-16T01:00:00Z"), "2026-01-16")

    def test_since_filter_stops_before_the_next_page(self):
        rows, summary, scripted, _sleeps = _run(appStoreIds=[FACEBOOK], since="2026-10-01")
        self.assertEqual([row["reviewId"] for row in _ok(rows)], ["1001"])
        self.assertEqual(summary["filteredOut"], 1)
        self.assertFalse(any("page=2" in url for url in scripted.urls))

    def test_max_items_does_not_fetch_another_page_or_app(self):
        rows, summary, scripted, _sleeps = _run(appStoreIds=[FACEBOOK, "333"], maxItems=1)
        self.assertEqual([row["reviewId"] for row in _ok(rows)], ["1001"])
        self.assertTrue(summary["truncated"])
        self.assertFalse(any("page=2" in url for url in scripted.urls))
        self.assertFalse(any("id=333" in url for url in scripted.urls))


class TestBlocksAndMisses(unittest.TestCase):
    def test_block_stops_before_later_apps(self):
        for status in (403, 429):
            scripted = Scripted(blocked={
                "lookup?id=222&": {"status": status, "text": "no", "content_type": "text/plain"},
            })
            rows, summary, scripted, _sleeps = _run(
                scripted, appStoreIds=[FACEBOOK, "222", "333"],
            )
            blocked = [row for row in rows if row["sourceStatus"] == "blocked"]
            self.assertEqual(len(blocked), 1, status)
            self.assertEqual(blocked[0]["decision"], "blocked")
            self.assertEqual(blocked[0]["appId"], "222")
            self.assertIn(f"HTTP {status}", blocked[0]["error"])
            self.assertFalse(mapping.billable_row(blocked[0]))
            self.assertEqual([row["reviewId"] for row in _ok(rows)], ["1001", "1002"])
            self.assertFalse(any("id=333" in url for url in scripted.urls))
            self.assertFalse(any("play.google.com" in url for url in scripted.urls))
            self.assertEqual(summary["stopped"], "blocked")
            self.assertEqual(summary["status"], "partial")

    def test_challenge_page_is_a_block(self):
        scripted = Scripted(blocked={
            "lookup?id=222&": {
                "status": 200,
                "text": "<html><body>cf-challenge</body></html>",
                "content_type": "text/html",
            },
        })
        rows, _summary, scripted, _sleeps = _run(scripted, appStoreIds=["222", "333"])
        self.assertEqual([row["sourceStatus"] for row in rows], ["blocked"])
        self.assertIn("challenge", rows[0]["error"])
        self.assertFalse(any("id=333" in url for url in scripted.urls))

    def test_blocked_run_is_not_charged(self):
        scripted = Scripted(blocked={
            "lookup?id=222&": {"status": 403, "text": "Forbidden", "content_type": "text/plain"},
        })
        actor, scripted = _run_main(
            {"appStoreIds": [FACEBOOK, "222", "333"], "maxSpendUsd": 5},
            scripted=scripted,
        )
        self.assertEqual(actor.charges, ["review", "review"])
        self.assertEqual([row["sourceStatus"] for row in actor.pushed].count("blocked"), 1)
        self.assertFalse(any("id=333" in url for url in scripted.urls))
        self.assertEqual(actor.values["SUMMARY"]["spendUsd"], 0.002)

    def test_not_found_is_free_and_the_run_continues(self):
        rows, summary, scripted, _sleeps = _run(appStoreIds=["000", FACEBOOK])
        misses = [row for row in rows if row["sourceStatus"] == "not_found"]
        self.assertEqual([row["appId"] for row in misses], ["000"])
        self.assertFalse(misses[0]["ok"])
        self.assertFalse(mapping.billable_row(misses[0]))
        self.assertEqual([row["reviewId"] for row in _ok(rows)], ["1001", "1002"])
        self.assertEqual(summary["notFound"], 1)
        self.assertEqual(summary["status"], "ok")
        self.assertTrue(any("id=284882215" in url for url in scripted.urls))

    def test_play_is_one_blocked_row_and_is_not_fetched(self):
        rows, _summary, scripted, _sleeps = _run(playIds=["com.facebook.katana"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sourceStatus"], "blocked")
        self.assertEqual(rows[0]["decision"], "blocked")
        self.assertEqual(rows[0]["store"], "play")
        self.assertEqual(rows[0]["appId"], "com.facebook.katana")
        self.assertIn("deferred", rows[0]["error"])
        self.assertIn("unproxied Play blocks at volume", rows[0]["error"])
        self.assertEqual(scripted.urls, [])

        rows, _summary, scripted, _sleeps = _run(
            appStoreIds=[FACEBOOK], playIds=["com.facebook.katana"],
        )
        blocked = [row for row in rows if row["sourceStatus"] == "blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(len(_ok(rows)), 2)
        self.assertFalse(any("play.google.com" in url for url in scripted.urls))

    def test_robots_disallow_does_not_fetch_the_reviews_url(self):
        scripted = Scripted(robots={
            "itunes.apple.com": "User-agent: *\nDisallow: /us/rss/\n",
        })
        rows, summary, scripted, _sleeps = _run(scripted, appStoreIds=[FACEBOOK])
        self.assertEqual([row["sourceStatus"] for row in rows], ["robots"])
        self.assertFalse(mapping.billable_row(rows[0]))
        self.assertTrue(any(urlparse(url).path == "/lookup" for url in scripted.urls))
        self.assertFalse(any("/rss/" in url for url in scripted.urls))
        self.assertEqual(summary["robots"], 1)
        self.assertEqual(summary["status"], "robots")

    def test_requests_are_paced(self):
        _rows, _summary, scripted, sleeps = _run(appStoreIds=[FACEBOOK])
        self.assertGreaterEqual(len(scripted.urls), 2)
        self.assertEqual(len(sleeps), len(scripted.urls) - 1)
        self.assertTrue(all(1.0 <= value <= 2.0 for value in sleeps))


class TestFetchRetry(unittest.TestCase):
    def test_block_status_is_not_retried(self):
        for status in (401, 403, 429):
            client = _Client([_response(status), _response(200)])
            with mock.patch.object(fetch_mod.time, "sleep"):
                body = fetch_mod.http_get("https://itunes.apple.com/lookup?id=1", client=client)
            self.assertEqual(body["status"], status)
            self.assertEqual(len(client.urls), 1)

    def test_server_error_retries_once(self):
        client = _Client([_response(503), _response(200, b"{}", "application/json")])
        with mock.patch.object(fetch_mod.time, "sleep"):
            body = fetch_mod.http_get("https://itunes.apple.com/lookup?id=1", client=client)
        self.assertEqual(body["status"], 200)
        self.assertEqual(body["text"], "{}")
        self.assertEqual(len(client.urls), 2)

        client = _Client([_response(500), _response(502)])
        with mock.patch.object(fetch_mod.time, "sleep"):
            body = fetch_mod.http_get("https://itunes.apple.com/lookup?id=1", client=client)
        self.assertEqual(body["status"], 502)
        self.assertEqual(len(client.urls), 2)

    def test_network_error_retries_once(self):
        client = _Client([OSError("timed out"), _response(200, b"{}", "application/json")])
        with mock.patch.object(fetch_mod.time, "sleep"):
            body = fetch_mod.http_get("https://itunes.apple.com/lookup?id=1", client=client)
        self.assertEqual(body["status"], 200)
        self.assertEqual(len(client.urls), 2)


class TestCharging(unittest.TestCase):
    def test_sentiment_off_omits_fields_and_does_not_charge_it(self):
        actor, _scripted = _run_main({
            "appStoreIds": [FACEBOOK],
            "sentiment": False,
            "maxSpendUsd": 1,
        })
        found = _ok(actor.pushed)
        self.assertEqual(len(found), 2)
        self.assertNotIn("sentiment", found[0])
        self.assertNotIn("sentimentScore", found[0])
        self.assertEqual(actor.charges, ["review", "review"])
        self.assertEqual(actor.values["SUMMARY"]["billedSentiment"], 0)
        self.assertEqual(actor.values["SUMMARY"]["spendUsd"], 0.002)

    def test_sentiment_on_labels_and_charges_both_events(self):
        actor, _scripted = _run_main({
            "appStoreIds": [FACEBOOK],
            "sentiment": True,
            "maxSpendUsd": 1,
        })
        found = _ok(actor.pushed)
        self.assertEqual(found[0]["sentiment"], "positive")
        self.assertEqual(found[0]["sentimentScore"], 1.0)
        self.assertEqual(found[1]["sentiment"], "negative")
        self.assertEqual(found[1]["sentimentScore"], -1.0)
        self.assertEqual(actor.charges, ["review", "sentiment", "review", "sentiment"])
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["billedReviews"], 2)
        self.assertEqual(summary["billedSentiment"], 2)
        self.assertEqual(summary["spendUsd"], 0.003)

    def test_neutral_lexicon_is_zero(self):
        self.assertEqual(mapping.sentiment_of("Ok", "It is an app"), ("neutral", 0.0))

    def test_spend_cap_holds_back_the_review_that_would_exceed_it(self):
        scripted = Scripted(
            pages={("777", 1): _rss(range(12))},
            lookups={"777": _lookup()},
        )
        actor, _scripted = _run_main(
            {"appStoreIds": ["777"], "maxItems": 100, "maxSpendUsd": 0.01, "sentiment": False},
            scripted=scripted,
        )
        found = _ok(actor.pushed)
        self.assertEqual(len(found), 10)
        self.assertEqual(actor.charges, ["review"] * 10)
        capped = [row for row in actor.pushed if row["sourceStatus"] == "spend_capped"]
        self.assertEqual(len(capped), 1)
        self.assertFalse(mapping.billable_row(capped[0]))
        self.assertTrue(capped[0]["error"].startswith(
            "maxSpendUsd cannot cover the next review. 2 matching review(s) were not pushed."
        ))
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["found"], 10)
        self.assertEqual(summary["heldBackReviews"], 2)
        self.assertEqual(summary["billedReviews"], 10)
        self.assertEqual(summary["spendUsd"], 0.01)
        self.assertTrue(summary["chargeCapped"])
        self.assertEqual(summary["status"], "ok")

    def test_sentiment_charge_must_fit_with_the_review(self):
        scripted = Scripted(
            pages={("777", 1): _rss(range(12))},
            lookups={"777": _lookup()},
        )
        actor, _scripted = _run_main(
            {"appStoreIds": ["777"], "maxItems": 100, "maxSpendUsd": 0.01, "sentiment": True},
            scripted=scripted,
        )
        found = _ok(actor.pushed)
        self.assertEqual(len(found), 6)
        self.assertTrue(all("sentiment" in row for row in found))
        self.assertEqual(actor.charges, ["review", "sentiment"] * 6)
        summary = actor.values["SUMMARY"]
        self.assertEqual(summary["heldBackReviews"], 6)
        self.assertEqual(summary["billedReviews"], 6)
        self.assertEqual(summary["billedSentiment"], 6)
        self.assertEqual(summary["spendUsd"], 0.009)
        self.assertTrue(summary["chargeCapped"])

    def test_sentiment_charge_failure_stops_the_feed(self):
        scripted = Scripted()

        async def flaky(event_name=None):
            if event_name == "sentiment":
                raise RuntimeError("charge down")
            actor.charges.append(event_name)
            return types.SimpleNamespace(event_charge_limit_reached=False)

        actor = FakeActor({
            "appStoreIds": [FACEBOOK],
            "sentiment": True,
            "maxSpendUsd": 1,
        })
        actor.charge = flaky
        fake_apify = types.ModuleType("apify")
        fake_apify.Actor = actor

        def live(config):
            return fetch_mod.build_fetch(config, scripted.direct, sleep=lambda _s: None)

        with mock.patch.dict(sys.modules, {"apify": fake_apify}), \
                mock.patch.object(main_mod, "Actor", actor), \
                mock.patch.object(main_mod, "make_live_fetch", live):
            asyncio.run(main_mod.main())
        found = _ok(actor.pushed)
        self.assertEqual([row["reviewId"] for row in found], ["1001"])
        self.assertEqual(actor.charges, ["review"])
        self.assertEqual(actor.values["SUMMARY"]["stopped"], "chargeFailed")
        self.assertTrue(any(row["sourceStatus"] == "spend_capped" for row in actor.pushed))

    def test_micro_dollar_ledger(self):
        ledger = spend.ReviewLedger(0.0015)
        self.assertTrue(ledger.fits(["review", "sentiment"]))
        self.assertEqual(ledger.affordable(["review", "sentiment"], 10), 1)
        ledger.commit("review")
        ledger.commit("sentiment")
        self.assertFalse(ledger.fits(["review", "sentiment"]))
        self.assertFalse(ledger.can("review"))
        self.assertEqual(ledger.spend_usd, 0.0015)
        self.assertFalse(ledger.can("proxy"))


if __name__ == "__main__":
    unittest.main()
