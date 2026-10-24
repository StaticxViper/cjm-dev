"""
Unit tests for scripts/apify-scripts/contractor-license.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_contractor_license_actor
"""
import importlib
import json
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "scripts" / "apify-scripts" / "contractor-license" / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contractor_license"
_ACTOR = _SRC.parent

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

mapping = importlib.import_module("mapping")
ca = importlib.import_module("adapters.ca_cslb")
az = importlib.import_module("adapters.az_roc")
nj = importlib.import_module("adapters.nj_dca")
pa = importlib.import_module("adapters.pa_hic")
politeness = importlib.import_module("politeness")
dedupe = importlib.import_module("dedupe")
base = importlib.import_module("adapters.base")


def _text(name):
    return (_FIXTURES / name).read_text(encoding="utf-8")


class MapFetch:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        page = self.pages.get(url)
        if page is None:
            return {"status": 404, "text": "missing fixture", "error": None, "content_type": "text/html"}
        body, content_type = page
        return {"status": 200, "text": body, "error": None, "content_type": content_type}


def _ca_fetch():
    return MapFetch({
        ca.CSV_URL: (_text("ca_master.csv"), "text/csv"),
    })


def _run(**actor_input):
    config = mapping.actor_input_to_config(actor_input)
    fetch = actor_input.pop("_fetch")
    return mapping.scrape(config, fetch)


class TestInput(unittest.TestCase):
    def test_state_name_and_bounds(self):
        config = mapping.actor_input_to_config({
            "state": "California",
            "license_no": "1000001",
            "maxResults": 99,
            "delaySeconds": 0,
        })
        self.assertEqual(config["query"].state, "CA")
        self.assertEqual(config["query"].license_no, "1000001")
        self.assertEqual(config["query"].max_results, 50)
        self.assertEqual(config["delay_seconds"], 1.0)
        self.assertFalse(config["error"])
        self.assertTrue(config["headless"])

    def test_requires_a_lookup_field(self):
        config = mapping.actor_input_to_config({"state": "CA"})
        self.assertIn("license number", config["error"])

    def test_rejects_a_full_state_name_without_a_mapping(self):
        config = mapping.actor_input_to_config({"state": "Texas", "name": "Ace"})
        self.assertIn("two-letter", config["error"])


class TestCalifornia(unittest.TestCase):
    def test_license_hit_is_billable(self):
        fetch = _ca_fetch()
        rows, summary = _run(state="CA", licenseNo="0001000001", _fetch=fetch)
        self.assertEqual(fetch.urls, [ca.CSV_URL])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["sourceStatus"], "found")
        self.assertEqual(row["license_no"], "1000001")
        self.assertEqual(row["name"], "NORTHWIND BUILDERS LLC")
        self.assertEqual(row["status"], "CLEAR")
        self.assertEqual(row["class"], "B")
        self.assertEqual(row["issue_date"], "01/10/2015")
        self.assertEqual(row["expiry_date"], "01/31/2027")
        self.assertEqual(row["bond"], "Contractor: SURETY EXAMPLE 15000")
        self.assertEqual(row["insurance"], "Exempt")
        self.assertEqual(row["address"], "100 Example St, Sacramento, CA, 95814")
        self.assertEqual(row["source_url"], ca.PORTAL_URL)
        self.assertTrue(row["ok"])
        self.assertTrue(row["scrapedAt"])
        self.assertTrue(mapping.billable_row(row))
        self.assertEqual(summary["billed"], 1)
        self.assertEqual(summary["status"], "ok")

    def test_missing_license_is_a_free_not_found(self):
        rows, summary = _run(state="CA", licenseNo="99999999", _fetch=_ca_fetch())
        self.assertEqual(rows[0]["sourceStatus"], "not_found")
        self.assertFalse(rows[0]["ok"])
        self.assertFalse(mapping.billable_row(rows[0]))
        self.assertEqual(summary["notFound"], 1)
        self.assertEqual(summary["billed"], 0)
        self.assertEqual(summary["status"], "not_found")

    def test_name_and_trade_filters(self):
        rows, summary = _run(state="CA", name="Northwind Builders LLC", trade="B", _fetch=_ca_fetch())
        self.assertEqual([row["license_no"] for row in rows], ["1000001"])
        roofers, _summary = _run(state="CA", trade="C39", _fetch=_ca_fetch())
        self.assertEqual(roofers[0]["name"], "PACIFIC ROOFING INC")
        self.assertEqual(roofers[0]["status"], "CLEAR / Good standing")
        self.assertEqual(roofers[0]["insurance"], "WC Insurance (STATE FUND)")
        self.assertEqual(summary["found"], 1)

    def test_license_and_other_name_do_not_match(self):
        rows, _summary = _run(
            state="CA",
            licenseNo="1000001",
            name="Pacific Roofing",
            _fetch=_ca_fetch(),
        )
        self.assertEqual(rows[0]["sourceStatus"], "not_found")

    def test_max_results_truncates(self):
        rows, summary = _run(state="CA", name="Northwind", maxResults=1, _fetch=_ca_fetch())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["license_no"], "1000001")
        self.assertTrue(summary["truncated"])
        self.assertEqual(summary["billed"], 1)

    def test_robots_and_request_cap_are_free(self):
        blocked = MapFetch({})
        blocked.pages[ca.CSV_URL] = ("", "text/plain")

        def robots(url):
            return {"status": 0, "text": "", "error": "robots_disallowed", "content_type": ""}

        rows, summary = _run(state="CA", licenseNo="1000001", _fetch=robots)
        self.assertEqual(rows[0]["sourceStatus"], "robots_disallowed")
        self.assertEqual(summary["billed"], 0)

        def capped(url):
            return {"status": 0, "text": "", "error": "request_cap", "content_type": ""}

        rows, summary = _run(state="CA", licenseNo="1000001", _fetch=capped)
        self.assertEqual(rows[0]["sourceStatus"], "error")
        self.assertIn("cap", rows[0]["error"])
        self.assertEqual(summary["billed"], 0)


class TestArizona(unittest.TestCase):
    def test_posting_list_csv_hit(self):
        csv_url = "https://roc.az.gov/sites/default/files/ROC_Posting-List_2026-10-20.csv"
        fetch = MapFetch({
            az.POSTING_URL: (_text("az_posting.html"), "text/html"),
            csv_url: (_text("az_contractors.csv"), "text/csv"),
        })
        rows, summary = _run(state="AZ", name="Desert General", trade="B-1", _fetch=fetch)
        self.assertEqual(fetch.urls, [az.POSTING_URL, csv_url])
        self.assertEqual(rows[0]["sourceStatus"], "found")
        self.assertEqual(rows[0]["license_no"], "301001")
        self.assertEqual(rows[0]["name"], "DESERT GENERAL LLC dba Desert General")
        self.assertEqual(rows[0]["class"], "B-1 General Commercial Contractor")
        self.assertEqual(rows[0]["status"], "Active")
        self.assertEqual(rows[0]["issue_date"], "2020-01-15")
        self.assertEqual(rows[0]["expiry_date"], "2027-06-30")
        self.assertEqual(rows[0]["bond"], "")
        self.assertEqual(rows[0]["insurance"], "")
        self.assertIn("Phoenix", rows[0]["address"])
        self.assertEqual(rows[0]["source_url"], csv_url)
        self.assertTrue(mapping.billable_row(rows[0]))
        self.assertEqual(summary["found"], 1)

    def test_trade_word_and_not_found(self):
        csv_url = "https://roc.az.gov/sites/default/files/ROC_Posting-List_2026-10-20.csv"
        fetch = MapFetch({
            az.POSTING_URL: (_text("az_posting.html"), "text/html"),
            csv_url: (_text("az_contractors.csv"), "text/csv"),
        })
        rows, _summary = _run(state="AZ", trade="Roofing", _fetch=fetch)
        self.assertEqual(rows[0]["license_no"], "301002")
        missed, summary = _run(state="AZ", licenseNo="000000", _fetch=fetch)
        self.assertEqual(missed[0]["sourceStatus"], "not_found")
        self.assertEqual(summary["billed"], 0)

    def test_cloudflare_challenge_does_not_fetch_the_csv(self):
        fetch = MapFetch({
            az.POSTING_URL: (_text("az_cloudflare.html"), "text/html"),
        })
        rows, summary = _run(state="AZ", licenseNo="301001", _fetch=fetch)
        self.assertEqual(fetch.urls, [az.POSTING_URL])
        self.assertEqual(rows[0]["sourceStatus"], "captcha")
        self.assertIn("Cloudflare", rows[0]["error"])
        self.assertFalse(mapping.billable_row(rows[0]))
        self.assertEqual(summary["captcha"], 1)
        self.assertEqual(summary["status"], "captcha")


class TestNewJerseyAndPennsylvania(unittest.TestCase):
    def test_nj_portal_is_unsupported(self):
        fetch = MapFetch({
            nj.BUILDERS_URL: (_text("nj_builders.html"), "text/html"),
        })
        rows, summary = _run(state="NJ", name="Example Builders", _fetch=fetch)
        self.assertEqual(fetch.urls, [nj.BUILDERS_URL])
        self.assertEqual(rows[0]["sourceStatus"], "unsupported")
        self.assertIn("service portal", rows[0]["error"])
        self.assertNotIn("mylicense.com", "".join(fetch.urls))
        self.assertFalse(mapping.billable_row(rows[0]))
        self.assertEqual(summary["unsupported"], 1)

    def test_pa_turnstile_is_captcha_and_the_form_is_not_submitted(self):
        fetch = MapFetch({
            pa.SEARCH_URL: (_text("pa_search.html"), "text/html"),
        })
        rows, summary = _run(state="PA", licenseNo="PA123456", _fetch=fetch)
        self.assertEqual(fetch.urls, [pa.SEARCH_URL])
        self.assertEqual(rows[0]["sourceStatus"], "captcha")
        self.assertIn("Turnstile", rows[0]["error"])
        self.assertEqual(summary["billed"], 0)

    def test_pa_page_without_a_challenge_is_still_not_submitted(self):
        fetch = MapFetch({
            pa.SEARCH_URL: (_text("pa_open_form.html"), "text/html"),
        })
        rows, _summary = _run(state="PA", name="Example", _fetch=fetch)
        self.assertEqual(fetch.urls, [pa.SEARCH_URL])
        self.assertEqual(rows[0]["sourceStatus"], "unsupported")
        self.assertIn("does not submit", rows[0]["error"])

    def test_unknown_state_exits_unsupported(self):
        fetch = MapFetch({})
        rows, summary = _run(state="TX", name="Ace", _fetch=fetch)
        self.assertEqual(fetch.urls, [])
        self.assertEqual(rows[0]["sourceStatus"], "unsupported")
        self.assertIn("TX", rows[0]["error"])
        self.assertEqual(summary["billed"], 0)


class TestDedupeAndPacer(unittest.TestCase):
    def test_same_license_keeps_the_richer_row(self):
        first = {
            "state": "CA",
            "sourceStatus": "found",
            "license_no": "1000001",
            "name": "NORTHWIND",
            "status": "CLEAR",
            "class": "B",
            "issue_date": "",
            "expiry_date": "01/31/2027",
            "bond": "",
            "insurance": "",
            "address": "100 Example St",
            "source_url": "https://example.test/a",
        }
        second = {
            "state": "CA",
            "sourceStatus": "found",
            "license_no": "0001000001",
            "name": "NORTHWIND BUILDERS LLC",
            "status": "CLEAR / Good standing",
            "class": "B",
            "issue_date": "01/10/2015",
            "expiry_date": "",
            "bond": "Contractor: SURETY EXAMPLE 15000",
            "insurance": "Exempt",
            "address": "",
            "source_url": "",
        }
        merged = dedupe.dedupe_licenses([first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "NORTHWIND BUILDERS LLC")
        self.assertEqual(merged[0]["issue_date"], "01/10/2015")
        self.assertEqual(merged[0]["expiry_date"], "01/31/2027")
        self.assertEqual(merged[0]["bond"], "Contractor: SURETY EXAMPLE 15000")
        self.assertEqual(merged[0]["address"], "100 Example St")
        self.assertEqual(merged[0]["source_url"], "https://example.test/a")

    def test_take_match_merges_a_duplicate_license(self):
        query = base.LicenseQuery("CA", "", "Northwind", "", 25)
        first = {
            "state": "CA",
            "sourceStatus": "found",
            "license_no": "1000001",
            "name": "NORTHWIND",
            "status": "CLEAR",
            "class": "B",
            "issue_date": "",
            "expiry_date": "",
            "bond": "",
            "insurance": "",
            "address": "",
            "source_url": "https://example.test/a",
        }
        second = dict(first)
        second["license_no"] = "0001000001"
        second["name"] = "NORTHWIND BUILDERS LLC"
        second["issue_date"] = "01/10/2015"
        found = [first]
        self.assertFalse(base.take_match(found, {"1000001"}, query, second))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], "NORTHWIND BUILDERS LLC")
        self.assertEqual(found[0]["issue_date"], "01/10/2015")
        self.assertEqual(found[0]["source_url"], "https://example.test/a")

    def test_pacer_stops_at_the_cap(self):
        slept = []
        pacer = politeness.Pacer(min_s=2, max_s=2, max_requests=2, sleep=slept.append)
        self.assertTrue(pacer.acquire())
        self.assertTrue(pacer.acquire())
        self.assertFalse(pacer.acquire())
        self.assertEqual(slept, [2])
        self.assertEqual(pacer.made, 2)


class TestStoreContract(unittest.TestCase):
    def test_schemas_and_readme(self):
        actor = json.loads((_ACTOR / ".actor" / "actor.json").read_text(encoding="utf-8"))
        self.assertEqual(actor["defaultRunOptions"]["timeoutSecs"], 600)
        form = json.loads((_ACTOR / ".actor" / "input_schema.json").read_text(encoding="utf-8"))
        state = form["properties"]["state"]
        self.assertEqual(state["editor"], "select")
        self.assertEqual(state["enum"], ["CA", "AZ", "NJ", "PA"])
        pricing = json.loads((_ACTOR / ".actor" / "pay_per_event.json").read_text(encoding="utf-8"))
        event = pricing["actorChargeEvents"]["license"]
        self.assertTrue(event["isPrimaryEvent"])
        self.assertGreater(event["eventPriceUsd"], 0)
        self.assertNotIn("result", pricing["actorChargeEvents"])
        dataset = json.loads((_ACTOR / ".actor" / "dataset_schema.json").read_text(encoding="utf-8"))
        for key in ("license_no", "name", "status", "class", "issue_date", "expiry_date", "bond", "insurance", "address", "source_url"):
            self.assertIn(key, dataset["fields"]["fields"])
        self.assertIn("detail", dataset["views"])
        readme = (_ACTOR / "README.md").read_text(encoding="utf-8")
        for phrase in ("CSLB", "not_found", "captcha", "license", "maxResults", "Turnstile", "service portal"):
            self.assertIn(phrase, readme)
        shared = (_REPO / "scripts" / "apify-scripts" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn("event_name", shared)
        self.assertFalse(base.is_challenge("LicenseNo,BusinessName\n1,Ace\n", "text/csv"))
        self.assertTrue(base.is_challenge(_text("pa_search.html"), "text/html"))
