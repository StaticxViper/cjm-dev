"""
Unit tests for scripts/apify-scripts/new-business.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_new_business_actor
"""
import importlib
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "scripts" / "apify-scripts" / "new-business" / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "new_business"
_NY = _REPO / "unittests" / "lead_automation" / "fixtures" / "new_business" / "ny_active_corporations" / "payload.json"
_PA = _REPO / "unittests" / "lead_automation" / "fixtures" / "new_business" / "pa_registered_businesses" / "payload.json"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

mapping = importlib.import_module("mapping")
fetch_mod = importlib.import_module("fetch")
spend = importlib.import_module("spend")


def _text(name):
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _json_text(path):
    return path.read_text(encoding="utf-8")


class Scripted:
    def __init__(self, pages, challenge_urls=None):
        self.pages = pages
        self.challenge_urls = challenge_urls or set()
        self.direct_urls = []
        self.proxy_calls = []
        self.solved = []

    def direct(self, url):
        self.direct_urls.append(url)
        if url in self.challenge_urls or self._marked(url):
            return {
                "status": 403,
                "text": _text("captcha.html"),
                "error": None,
                "content_type": "text/html",
            }
        body = self._body(url)
        if body is None:
            return {"status": 404, "text": "missing", "error": None, "content_type": "text/plain"}
        kind = "application/json" if body.lstrip().startswith("[") or body.lstrip().startswith("{") else "text/plain"
        if "<html" in body.lower():
            kind = "text/html"
        return {"status": 200, "text": body, "error": None, "content_type": kind}

    def proxy(self, url, token=None):
        self.proxy_calls.append((url, token))
        if token:
            body = self._body(url)
            return {"status": 200, "text": body or "[]", "error": None, "content_type": "application/json"}
        return {
            "status": 403,
            "text": _text("captcha.html"),
            "error": None,
            "content_type": "text/html",
        }

    def solver(self, url, html):
        self.solved.append(url)
        return "token-1" if "g-recaptcha" in (html or "") else None

    def _marked(self, url):
        return False

    def _body(self, url):
        parsed = urlparse(url)
        if parsed.path == "/robots.txt":
            if parsed.netloc == "reidfiling.co":
                return _text("robots_allow_home.txt")
            return _text("robots_allow_resource.txt")
        if "reidfiling.co" in parsed.netloc:
            return _text("website.html")
        for key, body in self.pages.items():
            if key in url:
                return body
        return None


def _run(scripted, **actor_input):
    entries = actor_input.pop("entries", None)
    config = mapping.actor_input_to_config(actor_input)
    fetch = fetch_mod.build_fetch(
        config,
        scripted.direct,
        proxy=scripted.proxy,
        solver=scripted.solver,
        sleep=lambda _seconds: None,
    )
    rows, summary = mapping.scrape(config, fetch, entries=entries)
    return rows, summary, scripted, config


def _found(rows):
    return [row for row in rows if row.get("sourceStatus") == "found"]


class TestInput(unittest.TestCase):
    def test_state_name_and_spend_bounds(self):
        config = mapping.actor_input_to_config({
            "states": ["New York", "ny"],
            "formedSince": "2026-01-01",
            "maxResults": 999,
            "delaySeconds": 0,
            "maxSpendUsd": 1000,
            "maxProxyCostUsd": 50,
        })
        self.assertEqual(config["states"], ["NY"])
        self.assertEqual(config["max_results"], 200)
        self.assertEqual(config["delay_seconds"], 1.0)
        self.assertEqual(config["max_spend_usd"], 100.0)
        self.assertEqual(config["max_proxy_usd"], 20.0)
        self.assertFalse(config["enrich_website"])
        self.assertFalse(config["allow_captcha"])
        self.assertTrue(config["headless"])
        self.assertFalse(config["error"])

    def test_requires_a_state(self):
        config = mapping.actor_input_to_config({})
        self.assertIn("state", config["error"])

    def test_rejects_a_full_state_name_without_a_mapping(self):
        config = mapping.actor_input_to_config({"states": ["Texas"]})
        self.assertIn("two-letter", config["error"])

    def test_proxy_cap_cannot_exceed_spend_cap(self):
        config = mapping.actor_input_to_config({
            "states": ["NY"],
            "maxSpendUsd": 0.2,
            "maxProxyCostUsd": 5,
        })
        self.assertEqual(config["max_proxy_usd"], 0.2)


class TestNewYorkFixture(unittest.TestCase):
    def test_ny_fixture_returns_a_row(self):
        scripted = Scripted({"n9v6-gdp6": _json_text(_NY)})
        rows, summary, scripted, _config = _run(
            scripted,
            states=["NY"],
            formedSince="2020-01-01",
            maxRequests=12,
        )
        found = _found(rows)
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["entity_id"], "EXAMPLE7931947")
        self.assertEqual(row["name"], "Example Reid LLC")
        self.assertEqual(row["type"], "DOMESTIC LIMITED LIABILITY COMPANY")
        self.assertEqual(row["county"], "Montgomery")
        self.assertEqual(row["state"], "NY")
        self.assertTrue(row["formation_date"])
        self.assertTrue(row["source_url"].startswith("https://data.ny.gov/resource/n9v6-gdp6.json?dos_id="))
        self.assertTrue(row["ok"])
        self.assertTrue(mapping.billable_business(row))
        self.assertFalse(mapping.billable_enrichment(row))
        self.assertEqual(summary["billedBusiness"], 1)
        self.assertEqual(summary["billedEnrichment"], 0)
        self.assertEqual(summary["proxyCharges"], 0)
        self.assertEqual(summary["captchaCharges"], 0)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(scripted.proxy_calls, [])
        self.assertTrue(any("n9v6-gdp6" in url for url in scripted.direct_urls))
        self.assertTrue(any(url.endswith("/robots.txt") for url in scripted.direct_urls))

    def test_later_requests_wait(self):
        sleeps = []
        scripted = Scripted({"n9v6-gdp6": _json_text(_NY)})
        config = mapping.actor_input_to_config({
            "states": ["NY"],
            "formedSince": "2020-01-01",
            "delaySeconds": 3,
        })
        fetch = fetch_mod.build_fetch(
            config,
            scripted.direct,
            proxy=scripted.proxy,
            solver=scripted.solver,
            sleep=sleeps.append,
        )
        mapping.scrape(config, fetch)
        self.assertTrue(sleeps)
        self.assertGreaterEqual(min(sleeps), 3)
        self.assertLessEqual(max(sleeps), 7)

    def test_entity_type_and_county_filters(self):
        scripted = Scripted({"n9v6-gdp6": _json_text(_NY)})
        kept, summary, _scripted, _config = _run(
            scripted,
            states=["NY"],
            counties=["Montgomery County"],
            entityTypes=["LLC"],
            formedSince="2020-01-01",
        )
        self.assertEqual(_found(kept)[0]["entity_id"], "EXAMPLE7931947")
        self.assertEqual(summary["billedBusiness"], 1)

        missed, summary, _scripted, _config = _run(
            Scripted({"n9v6-gdp6": _json_text(_NY)}),
            states=["NY"],
            entityTypes=["Nonprofit"],
            formedSince="2020-01-01",
        )
        self.assertEqual(missed[0]["sourceStatus"], "not_found")
        self.assertEqual(summary["billedBusiness"], 0)
        self.assertEqual(summary["spendUsd"], 0)

    def test_unsupported_state_is_free(self):
        rows, summary, scripted, _config = _run(
            Scripted({"n9v6-gdp6": _json_text(_NY)}),
            states=["NY", "TX"],
            formedSince="2020-01-01",
        )
        self.assertEqual(len(_found(rows)), 1)
        unsupported = [row for row in rows if row["sourceStatus"] == "unsupported"]
        self.assertEqual(unsupported[0]["state"], "TX")
        self.assertFalse(mapping.billable_business(unsupported[0]))
        self.assertEqual(summary["billedBusiness"], 1)
        self.assertFalse(any("data.pa.gov" in url for url in scripted.direct_urls))

    def test_old_formation_is_omitted(self):
        payload = json.loads(_json_text(_NY))
        payload.append({
            "dos_id": "OLD1",
            "current_entity_name": "Old Co LLC",
            "initial_dos_filing_date": "2010-01-01",
            "county": "Albany",
            "entity_type": "DOMESTIC LIMITED LIABILITY COMPANY",
            "location_state": "NY",
        })
        rows, _summary, _scripted, _config = _run(
            Scripted({"n9v6-gdp6": json.dumps(payload)}),
            states=["NY"],
            formedSince="2026-01-01",
        )
        ids = [row["entity_id"] for row in _found(rows)]
        self.assertEqual(ids, ["EXAMPLE7931947"])


class TestDedupe(unittest.TestCase):
    def test_matches_pipeline_dedupe(self):
        payload = json.loads(_json_text(_NY))
        twin = dict(payload[0])
        sibling = dict(payload[0])
        sibling["dos_id"] = "EXAMPLE7931948"
        sibling["county"] = "Albany"
        payload = [payload[0], twin, sibling]
        scripted = Scripted({"n9v6-gdp6": json.dumps(payload)})
        rows, summary, _scripted, config = _run(
            scripted,
            states=["NY"],
            formedSince="2020-01-01",
            maxResults=50,
        )
        mapping.prepare_imports()
        from new_business_dedupe import dedupe_new_businesses
        from new_business_sources.base import resolve_fixture_dates
        from new_business_sources.open_data import OpenDataAdapter
        from sources import entity_sources

        entry = entity_sources(["NY"])[0][0]
        adapter = OpenDataAdapter(entry)
        records = adapter.parse_payload(
            resolve_fixture_dates(payload),
            since_date=config["formed_since"],
            limit=None,
        )
        merged, stats = dedupe_new_businesses([record.as_dict() for record in records])
        self.assertEqual(
            sorted(row["entity_id"] for row in _found(rows)),
            sorted(row["entity_id"] for row in merged),
        )
        self.assertEqual(summary["mergedDuplicates"], stats["merged_duplicates"])
        self.assertEqual(summary["mergedDuplicates"], 1)
        self.assertEqual(len(_found(rows)), 2)


class TestEnrichment(unittest.TestCase):
    def test_registry_email_is_charged_only_when_enrichment_runs(self):
        pages = {"xvd7-5r2c": _json_text(_PA)}
        off, off_summary, _scripted, _config = _run(
            Scripted(pages),
            states=["PA"],
            formedSince="2020-01-01",
            enrichWebsite=False,
        )
        self.assertEqual(_found(off)[0]["email"], "smithlandscapingpa@gmail.com")
        self.assertFalse(_found(off)[0]["enrichmentFound"])
        self.assertFalse(mapping.billable_enrichment(_found(off)[0]))
        self.assertEqual(off_summary["billedBusiness"], 1)
        self.assertEqual(off_summary["billedEnrichment"], 0)

        on, on_summary, _scripted, _config = _run(
            Scripted(pages),
            states=["PA"],
            formedSince="2020-01-01",
            enrichWebsite=True,
        )
        self.assertEqual(_found(on)[0]["email"], "smithlandscapingpa@gmail.com")
        self.assertTrue(_found(on)[0]["enrichmentFound"])
        self.assertTrue(mapping.billable_enrichment(_found(on)[0]))
        self.assertEqual(on_summary["billedEnrichment"], 1)
        self.assertEqual(on_summary["billedBusiness"], 1)

    def test_ny_without_a_site_does_not_charge_enrichment(self):
        rows, summary, scripted, _config = _run(
            Scripted({"n9v6-gdp6": _json_text(_NY)}),
            states=["NY"],
            formedSince="2020-01-01",
            enrichWebsite=True,
        )
        self.assertEqual(_found(rows)[0]["website"], "")
        self.assertEqual(_found(rows)[0]["email"], "")
        self.assertFalse(_found(rows)[0]["enrichmentFound"])
        self.assertEqual(summary["billedEnrichment"], 0)
        self.assertEqual(summary["billedBusiness"], 1)
        self.assertFalse(any("google.com/search" in url for url in scripted.direct_urls))

    def test_website_email_is_charged_and_robots_skip_is_not(self):
        payload = json.loads(_json_text(_NY))
        payload[0]["website"] = "https://reidfiling.co"
        body = json.dumps(payload)
        entries = _ny_with_website()
        rows, summary, scripted, _config = _run(
            Scripted({"n9v6-gdp6": body}),
            states=["NY"],
            formedSince="2020-01-01",
            enrichWebsite=True,
            entries=entries,
        )
        row = _found(rows)[0]
        self.assertEqual(row["website"], "https://reidfiling.co")
        self.assertEqual(row["email"], "hello@reidfiling.co")
        self.assertTrue(row["enrichmentFound"])
        self.assertEqual(summary["billedEnrichment"], 1)
        self.assertTrue(any("reidfiling.co" in url and not url.endswith("/robots.txt") for url in scripted.direct_urls))

        blocked = Scripted({"n9v6-gdp6": body})
        blocked._home_robots = _text("robots_disallow_all.txt")
        original = blocked._body

        def _body(url):
            parsed = urlparse(url)
            if parsed.netloc == "reidfiling.co" and parsed.path == "/robots.txt":
                return blocked._home_robots
            return original(url)

        blocked._body = _body
        rows, summary, blocked, _config = _run(
            blocked,
            states=["NY"],
            formedSince="2020-01-01",
            enrichWebsite=True,
            entries=entries,
        )
        self.assertFalse(_found(rows)[0]["enrichmentFound"])
        self.assertEqual(summary["billedEnrichment"], 0)
        self.assertFalse(any(
            "reidfiling.co" in url and not url.endswith("/robots.txt")
            for url in blocked.direct_urls
        ))


class TestAccessAndSpend(unittest.TestCase):
    def test_direct_success_does_not_use_proxy(self):
        _rows, summary, scripted, _config = _run(
            Scripted({"n9v6-gdp6": _json_text(_NY)}),
            states=["NY"],
            formedSince="2020-01-01",
        )
        self.assertEqual(scripted.proxy_calls, [])
        self.assertEqual(summary["proxyCharges"], 0)
        self.assertGreaterEqual(len(scripted.direct_urls), 2)

    def test_proxy_only_after_a_block(self):
        scripted = Scripted({"n9v6-gdp6": _json_text(_NY)})
        scripted.challenge_urls_part = "n9v6-gdp6"

        def _marked(url):
            return "n9v6-gdp6" in url

        scripted._marked = _marked

        def proxy(url, token=None):
            scripted.proxy_calls.append((url, token))
            if "n9v6-gdp6" in url:
                return {
                    "status": 200,
                    "text": _json_text(_NY),
                    "error": None,
                    "content_type": "application/json",
                }
            return {"status": 200, "text": _text("robots_allow_resource.txt"), "error": None, "content_type": "text/plain"}

        scripted.proxy = proxy
        rows, summary, scripted, _config = _run(
            scripted,
            states=["NY"],
            formedSince="2020-01-01",
            allowCaptcha=False,
        )
        self.assertEqual(_found(rows)[0]["entity_id"], "EXAMPLE7931947")
        self.assertEqual(len(scripted.proxy_calls), 1)
        self.assertEqual(summary["proxyCharges"], 1)
        self.assertEqual(summary["captchaCharges"], 0)
        self.assertEqual(scripted.solved, [])
        data_direct = [url for url in scripted.direct_urls if "n9v6-gdp6" in url]
        self.assertTrue(data_direct)
        self.assertLess(scripted.direct_urls.index(data_direct[0]), len(scripted.direct_urls))

    def test_no_proxy_budget_pushes_blocked(self):
        scripted = Scripted({"n9v6-gdp6": _json_text(_NY)})
        scripted._marked = lambda url: "n9v6-gdp6" in url

        def proxy(url, token=None):
            raise AssertionError("proxy must not be called when the proxy cap is zero")

        scripted.proxy = proxy
        rows, summary, scripted, _config = _run(
            scripted,
            states=["NY"],
            formedSince="2020-01-01",
            maxProxyCostUsd=0,
            allowCaptcha=True,
        )
        self.assertEqual(rows[0]["sourceStatus"], "blocked")
        self.assertIn("spend cap", rows[0]["error"].lower())
        self.assertEqual(summary["billedBusiness"], 0)
        self.assertEqual(summary["proxyCharges"], 0)
        self.assertEqual(summary["captchaCharges"], 0)
        self.assertEqual(summary["status"], "blocked")

    def test_captcha_disabled_stops_without_a_solve_charge(self):
        scripted = Scripted({"n9v6-gdp6": _json_text(_NY)})
        scripted._marked = lambda url: "n9v6-gdp6" in url
        rows, summary, scripted, _config = _run(
            scripted,
            states=["NY", "PA"],
            formedSince="2020-01-01",
            allowCaptcha=False,
        )
        self.assertEqual(rows[0]["sourceStatus"], "blocked")
        self.assertIn("CAPTCHA", rows[0]["error"])
        self.assertEqual(summary["captchaCharges"], 0)
        self.assertEqual(summary["proxyCharges"], 1)
        self.assertEqual(scripted.solved, [])
        self.assertFalse(any("xvd7-5r2c" in url for url in scripted.direct_urls))

    def test_captcha_solve_is_charged_only_when_a_token_comes_back(self):
        scripted = Scripted({"n9v6-gdp6": _json_text(_NY)})
        scripted._marked = lambda url: "n9v6-gdp6" in url
        rows, summary, scripted, _config = _run(
            scripted,
            states=["NY"],
            formedSince="2020-01-01",
            allowCaptcha=True,
            maxSpendUsd=5,
        )
        self.assertEqual(_found(rows)[0]["entity_id"], "EXAMPLE7931947")
        self.assertEqual(scripted.solved, [url for url in scripted.solved])
        self.assertTrue(scripted.solved)
        self.assertEqual(summary["captchaCharges"], 1)
        self.assertEqual(summary["proxyCharges"], 1)
        self.assertTrue(any(token == "token-1" for _url, token in scripted.proxy_calls))

        poor = Scripted({"n9v6-gdp6": _json_text(_NY)})
        poor._marked = lambda url: "n9v6-gdp6" in url
        rows, summary, poor, _config = _run(
            poor,
            states=["NY"],
            formedSince="2020-01-01",
            allowCaptcha=True,
            maxSpendUsd=0.05,
        )
        self.assertEqual(rows[0]["sourceStatus"], "blocked")
        self.assertEqual(summary["captchaCharges"], 0)
        self.assertEqual(poor.solved, [])

    def test_robots_disallow_does_not_fetch_or_proxy(self):
        scripted = Scripted({"n9v6-gdp6": _json_text(_NY)})

        def _body(url):
            if urlparse(url).path == "/robots.txt":
                return _text("robots_disallow_all.txt")
            return _json_text(_NY)

        scripted._body = _body

        def proxy(url, token=None):
            raise AssertionError("proxy must not bypass robots.txt")

        scripted.proxy = proxy
        rows, summary, scripted, _config = _run(
            scripted,
            states=["NY"],
            formedSince="2020-01-01",
        )
        self.assertEqual(rows[0]["sourceStatus"], "robots_disallowed")
        self.assertEqual(summary["billedBusiness"], 0)
        self.assertFalse(any("n9v6-gdp6" in url for url in scripted.direct_urls))

    def test_spend_cap_saves_later_entities_without_billing_them(self):
        payload = json.loads(_json_text(_NY))
        second = dict(payload[0])
        second["dos_id"] = "EXAMPLE2"
        second["current_entity_name"] = "Second Filing LLC"
        payload.append(second)
        rows, summary, _scripted, _config = _run(
            Scripted({"n9v6-gdp6": json.dumps(payload)}),
            states=["NY"],
            formedSince="2020-01-01",
            maxSpendUsd=spend.PRICES_USD["business"],
        )
        self.assertEqual(len(_found(rows)), 2)
        self.assertEqual(summary["billedBusiness"], 1)
        self.assertTrue(summary["chargeCapped"])
        self.assertEqual(sum(1 for row in rows if row.get("_chargeBusiness")), 1)


class TestPricingFile(unittest.TestCase):
    def test_pay_per_event_matches_the_ledger(self):
        path = _REPO / "scripts" / "apify-scripts" / "new-business" / ".actor" / "pay_per_event.json"
        events = json.loads(path.read_text(encoding="utf-8"))["actorChargeEvents"]
        self.assertEqual(set(events), set(spend.PRICES_USD))
        for name, price in spend.PRICES_USD.items():
            self.assertEqual(events[name]["eventPriceUsd"], price)
        self.assertTrue(events["business"]["isPrimaryEvent"])
        self.assertNotIn("isPrimaryEvent", events["enrichment"])

    def test_image_copies_the_pipeline_modules(self):
        text = (_REPO / "scripts" / "apify-scripts" / "new-business" / "Dockerfile").read_text(encoding="utf-8")
        for name in (
            "new_business_pipeline.py",
            "new_business_dedupe.py",
            "new_business_website.py",
            "new_business_email.py",
        ):
            self.assertIn(name, text)


def _ny_with_website():
    mapping.prepare_imports()
    from sources import load_entries

    entries = []
    for entry in load_entries():
        if entry.get("id") != "ny_active_corporations":
            continue
        cloned = json.loads(json.dumps(entry))
        cloned["field_map"] = dict(cloned["field_map"])
        cloned["field_map"]["website"] = "website"
        cloned["query"] = dict(cloned["query"])
        cloned["query"]["select"] = list(cloned["query"]["select"]) + ["website"]
        entries.append(cloned)
    return entries


if __name__ == "__main__":
    unittest.main()
