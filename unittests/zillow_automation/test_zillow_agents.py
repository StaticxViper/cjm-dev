"""
Unit tests for the in-house Zillow agent pipeline.

Fixtures only. No live Zillow, Google, or brokerage requests.

Run from repo root:
    python -m unittest unittests.zillow_automation.test_zillow_agents
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIR = _REPO_ROOT / "scripts" / "zillow_automation"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
for _entry in (
    _REPO_ROOT,
    _REPO_ROOT / "scripts",
    _REPO_ROOT / "scripts" / "lead_automation",
    _SCRIPT_DIR,
):
    _text = str(_entry)
    if _text not in sys.path:
        sys.path.insert(0, _text)

import zillow_agents
import zillow_enrich
import zillow_parse
from email_discovery import extract_emails_from_html, extract_phones_from_html


def _read(name):
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _criteria(**overrides):
    data = {
        "zipCodes": ["08002"],
        "priceMin": 100000,
        "priceMax": 500000,
        "bedsMin": 3,
        "forSaleByAgent": True,
        "forSaleByOwner": False,
        "forRent": False,
        "sold": False,
        "resultsLimit": 10,
        "homeTypes": ["house"],
    }
    data.update(overrides)
    return zillow_parse.normalize_criteria(data)


class FakeSession:
    def __init__(self, results):
        self.results = results
        self.google_blocked = False
        self.persistent = {}
        self.cache = {}
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        if self.google_blocked:
            return []
        return self.results

    def persistent_result(self, lead):
        key = f"id:{(lead or {}).get('lead_id')}"
        if key not in self.persistent:
            return None
        return self.persistent[key].get("result") or {}

    def remember_result(self, lead):
        self.persistent[f"id:{lead.get('lead_id')}"] = {"result": dict(lead)}


def _inspect_file(name):
    html = _read(name)

    def inspect(url):
        soup = BeautifulSoup(html, "html.parser")
        return {
            "page_url": url,
            "page_text": soup.get_text(" ", strip=True),
            "emails": extract_emails_from_html(html),
            "phones": extract_phones_from_html(html),
            "html": html,
        }

    return inspect


def _blank_agent():
    return {
        "agent_name": "Jane Smith",
        "brokerage": "Compass",
        "phone": "",
        "email": "",
        "license": "",
        "profile_url": "",
        "enrichment_source": "",
        "enrichment_source_url": "",
        "confidence": "",
        "listing_ids": ["111"],
        "listing_addresses": ["1 Main St, Cherry Hill, NJ 08002"],
        "area": "Cherry Hill, NJ",
    }


SERP = [
    {
        "title": "Jane Smith | Compass",
        "url": "https://jane.smithhomes.com/about",
        "snippet": "Jane Smith is a Compass agent in Cherry Hill NJ",
    }
]


class TestCriteriaAndUrls(unittest.TestCase):
    def test_areas_can_replace_zip_codes(self):
        criteria = zillow_parse.normalize_criteria({"areas": ["Cherry Hill, NJ"]})
        self.assertEqual(zillow_parse.search_areas(criteria), ["Cherry Hill, NJ"])

    def test_search_url_encodes_filters(self):
        criteria = _criteria()
        url = zillow_parse.build_search_url("08002", criteria, page=2)
        self.assertIn("/homes/08002_rb/", url)
        state = json.loads(unquote(url.split("searchQueryState=", 1)[1]))
        filters = state["filterState"]
        self.assertEqual(filters["price"]["min"], 100000)
        self.assertEqual(filters["price"]["max"], 500000)
        self.assertEqual(filters["beds"]["min"], 3)
        self.assertTrue(filters["fsba"]["value"])
        self.assertFalse(filters["fsbo"]["value"])
        self.assertFalse(filters["fr"]["value"])
        self.assertFalse(filters["con"]["value"])
        self.assertNotIn("sf", filters)
        self.assertEqual(state["pagination"]["currentPage"], 2)
        self.assertNotIn("pagination", json.loads(unquote(
            zillow_parse.build_search_url("08002", criteria, page=1).split("searchQueryState=", 1)[1]
        )))

    def test_output_names_use_date_and_area(self):
        self.assertEqual(zillow_parse.area_file_slug(["08002"]), "08002")
        self.assertEqual(
            zillow_parse.area_file_slug(["08002", "08057", "08021"]),
            "08002_08021",
        )
        self.assertEqual(zillow_parse.area_file_slug(["a", "b", "c", "d"]), "4areas")
        agents, listings = zillow_parse.output_stems("2026-10-22", ["08002"])
        self.assertEqual(agents, "zillow_agents_2026-10-22_08002")
        self.assertEqual(listings, "zillow_listings_2026-10-22_08002")


class TestParsers(unittest.TestCase):
    def test_search_json_lists_urls_and_next_page(self):
        parsed = zillow_parse.parse_search_page(_read("search_results.html"))
        self.assertEqual(
            [item["listing_id"] for item in parsed["listings"]],
            ["111", "222"],
        )
        self.assertIn("/111_zpid/", parsed["listings"][0]["url"])
        self.assertTrue(parsed["has_next"])

    def test_search_html_links_when_json_is_missing(self):
        parsed = zillow_parse.parse_search_page(_read("search_links.html"))
        self.assertEqual(
            [item["listing_id"] for item in parsed["listings"]],
            ["111", "222"],
        )
        self.assertTrue(parsed["has_next"])

    def test_listing_agent_inside_client_cache(self):
        import json

        cache = json.dumps({
            "property": {
                "zpid": 111,
                "attributionInfo": {
                    "agentName": "Gianna Furia",
                    "brokerName": "Opus Elite",
                    "agentPhoneNumber": "267-592-8629",
                },
            },
        })
        outer = {"props": {"pageProps": {"gdpClientCache": cache}}}
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(outer)
            + "</script>"
        )
        url = "https://www.zillow.com/homedetails/1-Main-St/111_zpid/"
        listing = zillow_parse.parse_listing_page(html, url)
        self.assertEqual(listing["agent_name"], "Gianna Furia")
        self.assertEqual(listing["brokerage"], "Opus Elite")
        self.assertEqual(listing["phone"], "(267) 592-8629")

    def test_listing_json_beats_visible_markup(self):
        url = "https://www.zillow.com/homedetails/1-Main-St-Cherry-Hill-NJ-08002/111_zpid/"
        listing = zillow_parse.parse_listing_page(_read("listing_detail.html"), url)
        self.assertEqual(listing["listing_id"], "111")
        self.assertEqual(listing["address"], "1 Main St, Cherry Hill, NJ 08002")
        self.assertEqual(listing["price"], 325000)
        self.assertEqual(listing["status"], "FOR_SALE")
        self.assertEqual(listing["beds"], 3)
        self.assertEqual(listing["baths"], 2)
        self.assertEqual(listing["sqft"], 1500)
        self.assertEqual(listing["agent_name"], "Jane Smith")
        self.assertEqual(listing["brokerage"], "Compass")
        self.assertEqual(listing["phone"], "(856) 555-0101")
        self.assertEqual(listing["email"], "jane.smith@compass.com")
        self.assertEqual(listing["license"], "NJ-12345")
        self.assertIn("/profile/jane-smith", listing["profile_url"])

    def test_listing_html_fallback(self):
        url = "https://www.zillow.com/homedetails/9-Oak-Ave-Cherry-Hill-NJ-08002/333_zpid/"
        listing = zillow_parse.parse_listing_page(_read("listing_html_only.html"), url)
        self.assertEqual(listing["listing_id"], "333")
        self.assertEqual(listing["address"], "9 Oak Ave, Cherry Hill, NJ 08002")
        self.assertEqual(listing["price"], 410000)
        self.assertEqual(listing["beds"], 3)
        self.assertEqual(listing["baths"], 2)
        self.assertEqual(listing["sqft"], 1800)
        self.assertEqual(listing["agent_name"], "Jane Smith")
        self.assertEqual(listing["email"], "jane.smith@smithhomes.com")
        self.assertEqual(listing["phone"], "(856) 555-0199")


class TestDedupe(unittest.TestCase):
    def test_same_id_or_address_collapses_and_agent_keeps_listings(self):
        collection = zillow_parse.Collection()
        first = {
            "listing_id": "111",
            "address": "1 Main St, Cherry Hill, NJ 08002",
            "url": "https://www.zillow.com/homedetails/1-Main-St/111_zpid/",
            "agent_name": "Jane Smith",
            "brokerage": "Compass",
            "phone": "(856) 555-0101",
            "email": "",
            "area": "08002",
        }
        again = dict(first)
        again["url"] = first["url"] + "?extra=1"
        same_house = dict(first)
        same_house["listing_id"] = "999"
        same_house["address"] = "1 Main St Cherry Hill NJ 08002"
        second = dict(first)
        second["listing_id"] = "222"
        second["address"] = "2 Oak Ave, Cherry Hill, NJ 08002"
        second["url"] = "https://www.zillow.com/homedetails/2-Oak-Ave/222_zpid/"
        second["email"] = "jane.smith@compass.com"
        self.assertEqual(collection.add(first), "added")
        self.assertEqual(collection.add(again), "duplicate")
        self.assertEqual(collection.add(same_house), "duplicate")
        self.assertEqual(collection.add(second), "added")
        self.assertEqual(len(collection.listings), 2)
        self.assertEqual(len(collection.agents), 1)
        agent = collection.agents[0]
        self.assertEqual(agent["listing_ids"], ["111", "222"])
        self.assertEqual(len(agent["listing_addresses"]), 2)
        self.assertEqual(agent["email"], "jane.smith@compass.com")


class TestEnrichment(unittest.TestCase):
    def test_matching_page_fills_email_phone_source_and_score(self):
        session = FakeSession(SERP)
        agent = _blank_agent()
        zillow_enrich.enrich_agent(
            agent,
            "Cherry Hill, NJ",
            session,
            inspect=_inspect_file("agent_site.html"),
        )
        self.assertEqual(agent["email"], "jane.smith@smithhomes.com")
        self.assertIn("555-0133", agent["phone"])
        self.assertEqual(agent["enrichment_source"], "website")
        self.assertEqual(agent["enrichment_source_url"], "https://jane.smithhomes.com/about")
        self.assertEqual(agent["confidence"], 100)
        self.assertTrue(session.queries)

    def test_wrong_person_stays_blank(self):
        session = FakeSession(SERP)
        agent = _blank_agent()
        zillow_enrich.enrich_agent(
            agent,
            "Cherry Hill, NJ",
            session,
            inspect=_inspect_file("agent_site_wrong.html"),
        )
        self.assertEqual(agent["email"], "")
        self.assertEqual(agent["phone"], "")
        self.assertEqual(agent["confidence"], "")

    def test_name_and_area_without_brokerage_scores_80(self):
        agent = _blank_agent()
        score = zillow_enrich.contact_confidence(
            agent,
            "Cherry Hill, NJ",
            "Jane Smith helps buyers in Cherry Hill",
        )
        self.assertEqual(score, 80)
        rejected = zillow_enrich.contact_confidence(
            agent,
            "Cherry Hill, NJ",
            "Jane Smith at Coldwell Banker in Philadelphia",
        )
        self.assertEqual(rejected, 0)

    def test_cache_skips_a_second_search(self):
        session = FakeSession(SERP)
        inspect = _inspect_file("agent_site.html")
        zillow_enrich.enrich_agent(_blank_agent(), "Cherry Hill, NJ", session, inspect=inspect)
        self.assertTrue(session.queries)
        session.queries.clear()
        again = _blank_agent()
        zillow_enrich.enrich_agent(again, "Cherry Hill, NJ", session, inspect=inspect)
        self.assertEqual(session.queries, [])
        self.assertEqual(again["email"], "jane.smith@smithhomes.com")

    def test_google_block_does_not_search(self):
        session = FakeSession(SERP)
        session.google_blocked = True
        agent = _blank_agent()
        zillow_enrich.enrich_agent(agent, "Cherry Hill, NJ", session, inspect=_inspect_file("agent_site.html"))
        self.assertEqual(session.queries, [])
        self.assertEqual(agent["email"], "")


class TestPipeline(unittest.TestCase):
    def _run(self, fetch, root, **kwargs):
        criteria = kwargs.pop("criteria", None) or _criteria(resultsLimit=5)
        return zillow_agents.run_pipeline(
            criteria,
            fetch=fetch,
            output_dir=root,
            checkpoint_path=Path(root) / "checkpoint.json",
            seen_path=Path(root) / "seen.json",
            resume=kwargs.pop("resume", True),
            enrich=False,
            run_date="2026-10-22",
            **kwargs,
        )

    def test_resume_skips_finished_area_and_seen_skips_detail(self):
        search = _read("search_done.html")
        detail = _read("listing_detail.html")
        requested = []

        def fetch(url):
            requested.append(url)
            if "homedetails" in url:
                return zillow_agents.FetchResult(url=url, html=detail, status=200)
            return zillow_agents.FetchResult(url=url, html=search, status=200)

        with tempfile.TemporaryDirectory() as tmp:
            first = self._run(fetch, tmp, criteria=_criteria(zipCodes=["08002", "08057"], resultsLimit=5))
            self.assertTrue(any("/homes/08002_rb/" in url for url in requested))
            self.assertTrue(any("/homes/08057_rb/" in url for url in requested))
            self.assertEqual(sum("homedetails" in url for url in requested), 1)
            self.assertEqual(first["areas"]["08002"]["status"], "done")
            self.assertEqual(first["areas"]["08057"]["status"], "done")
            self.assertTrue(str(first["paths"]["agents_csv"]).endswith(
                "zillow_agents_2026-10-22_08002_08057.csv"
            ))
            saved = json.loads(Path(first["paths"]["agents_json"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["agents"][0]["agent_name"], "Jane Smith")
            self.assertIn("listings_found", saved["run"])
            seen = json.loads((Path(tmp) / "seen.json").read_text(encoding="utf-8"))
            self.assertIn("111", seen["ids"])

            requested.clear()
            second = self._run(fetch, tmp, criteria=_criteria(zipCodes=["08002", "08057"], resultsLimit=5))
            self.assertEqual(requested, [])
            self.assertEqual(second["stats"]["listings_found"], 1)

            requested.clear()
            fresh = self._run(
                fetch,
                tmp,
                criteria=_criteria(zipCodes=["08002"], resultsLimit=5),
                resume=False,
            )
            self.assertTrue(any("/homes/08002_rb/" in url for url in requested))
            self.assertFalse(any("homedetails" in url for url in requested))
            self.assertGreaterEqual(fresh["stats"]["duplicates_skipped"], 1)

    def test_block_page_stops_the_area(self):
        block = _read("block_page.html")
        requested = []

        def fetch(url):
            requested.append(url)
            return zillow_agents.FetchResult(url=url, html=block, status=200)

        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(fetch, tmp)
            self.assertEqual(len(requested), 1)
            self.assertNotIn("currentPage", requested[0])
            self.assertEqual(result["areas"]["08002"]["status"], "blocked")
            self.assertGreaterEqual(result["stats"]["blocked_pages"], 1)
            self.assertEqual(result["stats"]["areas_blocked"], 1)
            self.assertTrue(result["paths"]["agents_json"].is_file())


if __name__ == "__main__":
    unittest.main()
