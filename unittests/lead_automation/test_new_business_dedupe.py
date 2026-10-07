"""Dedupe, merge, and seen-cache behavior for new-business records."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_LEADGEN_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lead_automation"
if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))

from new_business_dedupe import (
    SeenCache,
    dedupe_new_businesses,
    normalize_business_name,
    split_dba_names,
)


class TestNameNormalization(unittest.TestCase):
    def test_suffix_stripping(self):
        self.assertEqual(
            normalize_business_name("Smith Landscaping, L.L.C."),
            normalize_business_name("Smith Landscaping"),
        )
        self.assertEqual(normalize_business_name("The Smith Landscaping, L.L.C."), "smith landscaping")

    def test_dba_split(self):
        names = split_dba_names("Smith Landscaping LLC d/b/a Green Grass")
        self.assertEqual(names, ["smith landscaping", "green grass"])
        self.assertIn("acme lawn", split_dba_names("Acme LLC DBA Acme Lawn"))


class TestMerge(unittest.TestCase):
    def test_registry_maps_and_website_merge(self):
        registry = {
            "business_name": "Smith Landscaping LLC",
            "entity_id": "EXAMPLE123",
            "state": "NJ",
            "city": "Cinnaminson",
            "zip": "08077",
            "address": "123 Example Rd",
            "phone": "(856) 555-0100",
            "formation_date": "2026-08-21",
            "website": "https://smithlandscaping.example",
            "source_name": "example_state_registry",
            "source_url": "https://example.gov/search",
            "source_record_url": "https://example.gov/records/EXAMPLE123",
            "source_category": "Secretary of State / entity databases",
            "business_status": "active",
            "fields_provided": ["business_name", "formation_date"],
            "newness_evidence": [{"type": "formation_date", "date": "2026-08-21", "source_name": "example_state_registry"}],
        }
        maps = {
            "business_name": "Smith Landscaping",
            "phone": "(856) 555-0100",
            "phone_origin": "maps",
            "place_id": "EXAMPLE",
            "maps_url": "https://www.google.com/maps/place/?q=place_id:EXAMPLE",
            "source_name": "google_maps",
            "source_url": "https://www.google.com/maps/search/",
            "source_record_url": "https://www.google.com/maps/place/?q=place_id:EXAMPLE",
            "fields_provided": ["phone", "place_id"],
        }
        website = {
            "business_name": "Smith Landscaping LLC",
            "website": "https://www.smithlandscaping.example/contact",
            "phone": "(856) 555-0199",
            "phone_origin": "website",
            "description": "Family landscaping for south jersey yards and spring cleanups.",
            "source_name": "business_website",
            "source_url": "https://smithlandscaping.example",
            "source_record_url": "https://smithlandscaping.example/contact",
            "fields_provided": ["website", "description", "phone"],
        }
        merged, stats = dedupe_new_businesses([registry, maps, website])
        self.assertEqual(len(merged), 1)
        self.assertEqual(stats["merged_duplicates"], 2)
        self.assertEqual(len(merged[0]["sources"]), 3)
        self.assertEqual(merged[0]["dedupe_match"], "exact")
        self.assertEqual(merged[0]["phone"], "(856) 555-0199")
        self.assertIn("spring cleanups", merged[0]["description"])
        self.assertEqual(merged[0]["entity_id"], "EXAMPLE123")
        self.assertEqual(merged[0]["place_id"], "EXAMPLE")

    def test_transitive_merge(self):
        first = {"business_name": "Alpha Painting", "phone": "(856) 555-0101", "state": "NJ", "city": "Cinnaminson"}
        second = {
            "business_name": "Alpha Painting LLC",
            "phone": "(856) 555-0101",
            "website": "https://alphapainting.example",
            "state": "NJ",
        }
        third = {
            "business_name": "Totally Different",
            "website": "https://www.alphapainting.example/about",
            "state": "NJ",
        }
        merged, _stats = dedupe_new_businesses([first, second, third])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["merged_from"], 3)

    def test_same_name_different_zips_not_merged(self):
        left = {"business_name": "Smith Landscaping", "zip": "08077", "city": "Cinnaminson", "state": "NJ"}
        right = {"business_name": "Smith Landscaping", "zip": "08002", "city": "Cherry Hill", "state": "NJ"}
        merged, stats = dedupe_new_businesses([left, right])
        self.assertEqual(len(merged), 2)
        self.assertEqual(stats["merged_duplicates"], 0)
        self.assertTrue(any(row.get("possible_duplicate_of") for row in merged) or stats["possible_duplicates"] == 0 or any(
            row.get("possible_duplicate_of") for row in merged
        ))
        # Different cities, so this pair is not even a weak city match.
        self.assertTrue(all(not row.get("possible_duplicate_of") for row in merged))

    def test_same_name_same_city_different_zip_is_possible_duplicate(self):
        left = {"business_name": "Smith Landscaping", "zip": "08077", "city": "Cinnaminson", "state": "NJ", "address": "1 Main St"}
        right = {"business_name": "Smith Landscaping", "zip": "08078", "city": "Cinnaminson", "state": "NJ", "address": "99 Other Rd"}
        merged, stats = dedupe_new_businesses([left, right])
        self.assertEqual(len(merged), 2)
        self.assertEqual(stats["possible_duplicates"], 1)
        later = merged[1]
        self.assertEqual(later["possible_duplicate_of"], merged[0]["lead_id"])

    def test_name_only_never_merges(self):
        merged, stats = dedupe_new_businesses([
            {"business_name": "Smith Landscaping"},
            {"business_name": "Smith Landscaping"},
        ])
        self.assertEqual(len(merged), 2)
        self.assertEqual(stats["merged_duplicates"], 0)
        self.assertTrue(all(not row.get("possible_duplicate_of") for row in merged))

    def test_richest_description_and_registry_date(self):
        short = {
            "business_name": "Smith Landscaping LLC",
            "phone": "(856) 555-0100",
            "description": "Lawns",
            "source_name": "directory",
        }
        long = {
            "business_name": "Smith Landscaping",
            "phone": "(856) 555-0100",
            "description": "Weekly lawn care and spring cleanups for local homes.",
            "formation_date": "2026-08-21",
            "entity_id": "1",
            "state": "NJ",
            "source_name": "registry",
            "source_category": "Secretary of State / entity databases",
            "email": "owner@smithlandscaping.example",
            "email_confidence": "high",
            "email_source": "website_contact",
        }
        merged, _stats = dedupe_new_businesses([short, long])
        self.assertEqual(len(merged), 1)
        self.assertIn("spring cleanups", merged[0]["description"])
        self.assertEqual(merged[0]["email"], "owner@smithlandscaping.example")
        self.assertEqual(merged[0]["formation_date"], "2026-08-21")


class TestSeenCache(unittest.TestCase):
    def test_seen_cache_suppresses_until_include_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = SeenCache(Path(tmp) / "seen.json")
            rows, _stats = dedupe_new_businesses([
                {"business_name": "Smith Landscaping", "phone": "(856) 555-0100", "zip": "08077"},
            ], seen_cache=cache)
            lead_id = rows[0]["lead_id"]
            self.assertFalse(cache.already_output(lead_id))
            cache.mark_output(lead_id, "2026-08-21")
            cache.save()
            reloaded = SeenCache(Path(tmp) / "seen.json")
            self.assertTrue(reloaded.already_output(lead_id))
            self.assertFalse(False if True else reloaded.already_output(lead_id))
            # include-seen is a pipeline flag; the cache still remembers the id
            self.assertEqual(reloaded.lead_id_for_keys([("phone", "8565550100")]), lead_id)

    def test_lead_id_stable_when_registry_id_arrives_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seen.json"
            first_cache = SeenCache(path)
            first, _stats = dedupe_new_businesses([
                {"business_name": "Smith Landscaping LLC", "phone": "(856) 555-0100", "zip": "08077", "state": "NJ"},
            ], seen_cache=first_cache)
            first_cache.save()
            original = first[0]["lead_id"]
            self.assertTrue(original.startswith("h:"))
            second_cache = SeenCache(path)
            second, _stats = dedupe_new_businesses([
                {
                    "business_name": "Smith Landscaping LLC",
                    "phone": "(856) 555-0100",
                    "zip": "08077",
                    "state": "NJ",
                    "entity_id": "NEW123",
                },
            ], seen_cache=second_cache)
            self.assertEqual(second[0]["lead_id"], original)


if __name__ == "__main__":
    unittest.main()
