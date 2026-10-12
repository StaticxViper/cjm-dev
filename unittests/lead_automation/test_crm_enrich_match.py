"""
Unit tests for scripts/lead_automation/crm_enrich_match.py

Run from repo root:
    python -m unittest unittests.lead_automation.test_crm_enrich_match
"""
import importlib
import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"


def _load():
    prev = os.getcwd()
    try:
        os.chdir(_LEADGEN_DIR)
        if str(_LEADGEN_DIR) not in sys.path:
            sys.path.insert(0, str(_LEADGEN_DIR))
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        return importlib.import_module("crm_enrich_match")
    finally:
        os.chdir(prev)


match = _load()


STRIKER = {
    "id": "e89bdb1c-22af-4d6f-a529-12e8207abdcb",
    "business_name": "STRIKER CONSTRUCTION SERVICES LLC",
    "address": "NY",
    "phone": "(631) 821-4921",
    "website": "http://cstakerremodeling.com/",
    "business_description": (
        "DOMESTIC LIMITED LIABILITY COMPANY. Formed 2026-10-04 (NY DOS). County: Cattaraugus."
    ),
    "tags": ["ny", "no-email", "new-business"],
}

STAKER = {
    "business_name": "C. Staker Remodeling",
    "phone": "(631) 821-4921",
    "website": "http://cstakerremodeling.com/",
    "address": "100 Main St, Huntington, NY 11743",
    "category": "Remodeler",
    "place_id": "ChIJ___LaZ1n6IkRBv6QRmL-qc4",
}

BASECAMP = {
    "id": "459faa3b-1111-4222-8333-459faa3b0001",
    "business_name": "B&B Basecamp LLC",
    "address": "2079 W 44th Ave, Denver, CO, 80211",
    "phone": "(303) 582-9979",
    "website": "http://www.basecampco.com/",
    "business_description": "DLLC. Formed 2026-10-04 (CO). City: Denver 80211.",
    "tags": ["co", "denver"],
}

GOLDEN = {
    "business_name": "Base Camp at Golden Gate Canyon",
    "phone": "(303) 582-9979",
    "website": "http://www.basecampco.com/",
    "address": "92 Crawford Gulch Rd, Golden, CO 80403",
    "category": "Campground",
}


class TestNormalize(unittest.TestCase):
    def test_suffix_stripping(self):
        self.assertEqual(
            match.normalize_match_name("STRIKER CONSTRUCTION SERVICES LLC"),
            "striker construction services",
        )
        self.assertEqual(match.normalize_match_name("Foo L.L.C."), "foo")
        self.assertEqual(match.normalize_match_name("Foo, Inc."), "foo")
        self.assertEqual(match.display_name("STRIKER CONSTRUCTION SERVICES LLC"), "STRIKER CONSTRUCTION SERVICES")

    def test_dba_split(self):
        parts = match.split_dba_names("Foo LLC DBA Bar Grill")
        self.assertEqual(parts[0].upper().startswith("FOO"), True)
        self.assertIn("Bar Grill", parts[-1])
        self.assertEqual(match.normalize_match_name("Foo LLC DBA Bar Grill"), "bar grill")

    def test_distinctive_tokens_reject_fuzzy_and_allow_compound(self):
        lead = match.normalize_match_name("STRIKER CONSTRUCTION SERVICES LLC")
        bad = match.normalize_match_name("C. Staker Remodeling")
        self.assertTrue(match.distinctive_token_missing(lead, bad))
        self.assertIn("striker", match.distinctive_tokens(lead))
        self.assertNotIn("construction", match.distinctive_tokens(lead))
        base = match.normalize_match_name("B&B Basecamp LLC")
        camp = match.normalize_match_name("Base Camp at Golden Gate Canyon")
        self.assertFalse(match.distinctive_token_missing(base, camp))
        self.assertEqual(base, "b b basecamp")


class TestLocationParse(unittest.TestCase):
    def test_both_description_formats(self):
        prose = match.parse_lead_location(STRIKER, {})
        self.assertEqual(prose["state"], "NY")
        self.assertEqual(prose["county"], "Cattaraugus")
        self.assertIsNone(prose["city"])
        self.assertIsNone(prose["street"])

        kv = match.parse_lead_location({
            "address": "NY",
            "business_description": (
                "category=DOMESTIC LIMITED LIABILITY COMPANY; formation_date=2026-10-05; "
                "state=NY; county=Westchester; city=; status=active;"
            ),
            "tags": ["ny"],
        }, {})
        self.assertEqual(kv["state"], "NY")
        self.assertEqual(kv["county"], "Westchester")
        self.assertIsNone(kv["city"])

        denver = match.parse_lead_location(BASECAMP, match.load_zip_county())
        self.assertEqual(denver["state"], "CO")
        self.assertEqual(denver["city"], "Denver")
        self.assertEqual(denver["zip"], "80211")
        self.assertEqual(denver["street"], "2079 W 44th Ave")
        self.assertEqual(denver["county"], "Denver")

    def test_state_from_address_code(self):
        loc = match.parse_lead_location({"address": "NY", "business_description": "", "tags": []}, {})
        self.assertEqual(loc["state"], "NY")
        self.assertTrue(match.address_is_empty("NY"))
        self.assertFalse(match.address_is_empty("2079 W 44th Ave, Denver, CO, 80211"))

    def test_county_zip_agreement(self):
        table = match.load_zip_county()
        self.assertEqual(table["80211"]["county"], "Denver")
        self.assertEqual(table["11743"]["county"], "Suffolk")
        self.assertEqual(table["14760"]["county"], "Cattaraugus")


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.zips = match.load_zip_county()
        self.npas = match.load_npa_state()

    def test_area_code_and_category(self):
        scored = match.score_candidate(STRIKER, STAKER, self.zips, self.npas)
        self.assertNotIn("area_code_state_mismatch", scored["hard_rejects"])
        self.assertEqual(scored["breakdown"]["category"], 5)
        other = dict(STAKER)
        other["phone"] = "(310) 555-0100"
        other["address"] = "100 Main St, Huntington, NY 11743"
        scored_ca = match.score_candidate(STRIKER, other, self.zips, self.npas)
        self.assertIn("area_code_state_mismatch", scored_ca["hard_rejects"])

    def test_striker_is_no_match_32(self):
        selection = match.select_match([STAKER], STRIKER, self.zips, self.npas)
        best = selection["best"]
        self.assertEqual(best["breakdown"], {"name": 17, "location": 10, "category": 5, "corroboration": 0})
        self.assertEqual(best["score"], 32)
        self.assertIn("distinctive_token_missing", best["hard_rejects"])
        self.assertIn("county_mismatch", best["hard_rejects"])
        self.assertEqual(selection["decision"], "no_match")
        self.assertIsNone(selection["winner"])

    def test_basecamp_address_mismatch(self):
        selection = match.select_match([GOLDEN], BASECAMP, self.zips, self.npas)
        self.assertEqual(selection["decision"], "no_match")
        self.assertIn("address_mismatch", selection["best"]["hard_rejects"])
        self.assertIsNone(selection["winner"])

    def test_exact_county_match_writes(self):
        lead = {
            "business_name": "NORTHWIND CUSTOMS LLC",
            "address": "NY",
            "business_description": "state=NY; county=Cattaraugus; city=;",
            "tags": ["ny"],
        }
        candidate = {
            "business_name": "Northwind Customs",
            "address": "1 Main St, Olean, NY 14760",
            "phone": "(716) 555-0100",
            "category": "",
        }
        selection = match.select_match([candidate], lead, self.zips, self.npas)
        self.assertEqual(selection["decision"], "write")
        self.assertEqual(selection["best"]["score"], 85)
        self.assertEqual(selection["winner"]["name"], "Northwind Customs")

    def test_no_county_is_low_confidence(self):
        lead = {
            "business_name": "NORTHWIND CUSTOMS LLC",
            "address": "NY",
            "business_description": "Formed 2026-10-04 (NY DOS).",
            "tags": ["ny"],
        }
        candidate = {
            "business_name": "Northwind Customs",
            "address": "1 Main St, Buffalo, NY",
            "phone": "(716) 555-0100",
        }
        selection = match.select_match([candidate], lead, self.zips, self.npas)
        self.assertEqual(selection["decision"], "low_confidence")
        self.assertLessEqual(selection["best"]["score"], 75)
        self.assertGreaterEqual(selection["best"]["score"], 60)
        self.assertIsNone(selection["winner"])

    def test_never_first_result_fallback(self):
        good_lead = {
            "business_name": "NORTHWIND CUSTOMS LLC",
            "address": "NY",
            "business_description": "state=NY; county=Cattaraugus;",
            "tags": ["ny"],
        }
        good = {
            "business_name": "Northwind Customs",
            "address": "1 Main St, Olean, NY 14760",
            "phone": "(716) 555-0100",
        }
        selection = match.select_match([STAKER, good], good_lead, self.zips, self.npas)
        self.assertEqual(selection["decision"], "write")
        self.assertEqual(selection["winner"]["name"], "Northwind Customs")
        only_bad = match.select_match([STAKER], STRIKER, self.zips, self.npas)
        self.assertIsNone(only_bad["winner"])
        self.assertNotEqual(only_bad["decision"], "write")

    def test_query_uses_county_not_near(self):
        queries = match.build_search_queries(STRIKER, match.parse_lead_location(STRIKER, {}))
        self.assertEqual(queries[0], "STRIKER CONSTRUCTION SERVICES Cattaraugus County NY")
        self.assertNotIn("near", queries[0])


if __name__ == "__main__":
    unittest.main()
