"""
Unit tests for scripts/apify-scripts/permits.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_permits

Fixtures only. These tests do not call a live permit portal.
"""
import importlib
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "scripts" / "apify-scripts" / "permits" / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "permits"
_ACTOR_MODULES = ("spend", "runtime", "sources", "fetch", "mapping")

VERIFIED_IDS = (
    "chicago_building_permits",
    "seattle_building_permits",
    "austin_issued_permits",
    "los_angeles_building_permits",
)


def _load_actor():
    saved = {name: sys.modules.pop(name) for name in _ACTOR_MODULES if name in sys.modules}
    inserted = str(_SRC) not in sys.path[:1]
    if inserted:
        sys.path.insert(0, str(_SRC))
    try:
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


def _run(scripted, entries=None, **actor_input):
    config = mapping.actor_input_to_config(actor_input, today=date(2026, 10, 26))
    sleeps = []
    fetch = fetch_mod.build_fetch(
        config,
        scripted.direct,
        proxy=scripted.proxy,
        solver=scripted.solver,
        sleep=lambda seconds: sleeps.append(seconds),
    )
    rows, summary = mapping.scrape(config, fetch, entries=entries)
    return rows, summary, scripted, config, sleeps


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
    def test_four_verified_socrata_sources(self):
        entries = sources.load_entries()
        verified = sources.verified_entries(entries)
        self.assertEqual([entry["id"] for entry in verified], list(VERIFIED_IDS))
        for entry in verified:
            self.assertEqual(entry["adapter"], "open_data")
            self.assertEqual(entry["status"], "verified")
            self.assertTrue(entry["enabled"])
            self.assertIn("/resource/", entry["url"])
            self.assertTrue(entry["query"]["date_column"])
            self.assertIn("permit_id", entry["field_map"])
            self.assertIn("issued_date", entry["field_map"])
            self.assertNotIn("owner_name", entry.get("field_map") or {})


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


if __name__ == "__main__":
    unittest.main()
