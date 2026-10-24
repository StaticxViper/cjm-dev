"""Free-text niche parsing, slugs, and output filenames."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.lead_automation.search_input import (
    EMPTY_NICHE_MESSAGE,
    EmptySearchInput,
    allocate_output_paths,
    build_search_queries,
    lead_type_slug,
    output_basename,
    parse_term_list,
    queries_for_location,
    require_niches,
    slugify_lead_type,
)


class ParseTermTests(unittest.TestCase):
    def test_trims_dedupes_and_splits_commas(self):
        terms = parse_term_list("  Pressure Washing, window cleaning, pressure washing ")
        self.assertEqual(terms, ["Pressure Washing", "window cleaning"])

    def test_keeps_city_comma_state_together(self):
        terms = parse_term_list(
            "pressure washing near Cherry Hill, NJ, window cleaning near Cherry Hill, NJ"
        )
        self.assertEqual(
            terms,
            [
                "pressure washing near Cherry Hill, NJ",
                "window cleaning near Cherry Hill, NJ",
            ],
        )

    def test_list_input_and_blank_pieces(self):
        self.assertEqual(parse_term_list([" mobile dog grooming ", "", "mobile dog grooming"]), ["mobile dog grooming"])
        self.assertEqual(parse_term_list(" , , "), [])

    def test_require_niches_rejects_empty(self):
        with self.assertRaises(EmptySearchInput) as caught:
            require_niches("   ")
        self.assertEqual(str(caught.exception), EMPTY_NICHE_MESSAGE)


class SlugTests(unittest.TestCase):
    def test_slug_is_lowercase_hyphenated(self):
        self.assertEqual(slugify_lead_type("Mobile Dog Grooming!"), "mobile-dog-grooming")
        self.assertEqual(slugify_lead_type("dog & cat / grooming"), "dog-cat-grooming")

    def test_joins_a_few_niches_then_uses_multi_niche(self):
        self.assertEqual(lead_type_slug(["pressure washing"]), "pressure-washing")
        self.assertEqual(
            lead_type_slug(["pressure washing", "window cleaning"]),
            "pressure-washing-window-cleaning",
        )
        self.assertEqual(
            lead_type_slug(["a", "b", "c", "d"]),
            "multi-niche",
        )


class QueryTests(unittest.TestCase):
    def test_blank_keywords_are_built_from_niche_and_location(self):
        locations = [("NJ", "Cherry Hill", "39.9,-75.0")]
        queries = build_search_queries(["mobile dog grooming"], [], locations)
        self.assertEqual(queries, ["mobile dog grooming near Cherry Hill, NJ"])

    def test_typed_keywords_stay_exact(self):
        locations = [("NJ", "Cherry Hill", "39.9,-75.0"), ("PA", "Philadelphia", "39.9,-75.1")]
        typed = ["pressure washing near Cherry Hill NJ"]
        queries = build_search_queries(["pressure washing"], typed, locations)
        self.assertEqual(queries, typed)
        self.assertEqual(
            queries_for_location(queries, "Cherry Hill", "NJ", locations),
            typed,
        )
        self.assertEqual(
            queries_for_location(queries, "Philadelphia", "PA", locations),
            [],
        )


class OutputNameTests(unittest.TestCase):
    def test_basename_uses_the_given_day_and_slug(self):
        name = output_basename(["pressure washing"], today=date(2026, 10, 21))
        self.assertEqual(name, "leads_2026-10-21_pressure-washing")

    def test_collision_adds_a_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first_csv, first_json = allocate_output_paths(
                directory,
                ["pressure washing"],
                today=date(2026, 10, 21),
            )
            self.assertEqual(first_csv.name, "leads_2026-10-21_pressure-washing.csv")
            self.assertEqual(first_json.name, "leads_2026-10-21_pressure-washing.json")
            first_json.write_text("[]", encoding="utf-8")
            second_csv, second_json = allocate_output_paths(
                directory,
                ["pressure washing"],
                today=date(2026, 10, 21),
            )
            self.assertEqual(second_csv.name, "leads_2026-10-21_pressure-washing_2.csv")
            self.assertEqual(second_json.name, "leads_2026-10-21_pressure-washing_2.json")
            self.assertFalse(second_csv.exists())
            self.assertFalse(second_json.exists())

    def test_csv_collision_also_moves_the_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "leads_2026-10-21_multi-niche.csv").write_text("x", encoding="utf-8")
            csv_path, json_path = allocate_output_paths(
                directory,
                ["a", "b", "c", "d"],
                today=date(2026, 10, 21),
            )
            self.assertEqual(csv_path.name, "leads_2026-10-21_multi-niche_2.csv")
            self.assertEqual(json_path.name, "leads_2026-10-21_multi-niche_2.json")


if __name__ == "__main__":
    unittest.main()
