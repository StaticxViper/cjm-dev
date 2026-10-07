"""Presets, skill toggles, and the search menu."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from opp_finder_v2.cli import main  # noqa: E402
from opp_finder_v2.config import PACKAGE_DIR, load_criteria  # noqa: E402
from opp_finder_v2.menu import configure_search, load_skills, run_menu  # noqa: E402
from opp_finder_v2.menu import _toggle_skills  # noqa: E402
from opp_finder_v2.presets import (  # noqa: E402
    delete_preset,
    find_preset,
    load_presets,
    save_presets,
    setup_from_preset,
    upsert_preset,
)
from opp_finder_v2.search_setup import SearchSetup, apply_setup  # noqa: E402


def _reader(answers):
    items = iter(answers)

    def reader(_prompt=""):
        return next(items)

    return reader


class TestPresetsAndMenu(unittest.TestCase):
    def test_shipped_presets_apply(self):
        presets = load_presets()
        names = {preset["name"] for preset in presets}
        self.assertIn("Part-time remote data entry", names)
        self.assertIn("Part-time IT", names)
        self.assertIn("Remote anything", names)
        criteria = load_criteria()
        setup = setup_from_preset(find_preset(presets, "part time remote data entry"))
        apply_setup(criteria, setup, load_skills())
        self.assertEqual(criteria.keywords_any, ["data entry"])
        self.assertEqual(criteria.employment_types, ["part_time"])
        self.assertTrue(criteria.remote_only)
        self.assertIsNone(criteria.min_rate_hourly)
        self.assertEqual(criteria.min_relevance, 15)

        anything = setup_from_preset(find_preset(presets, "remote_anything"))
        apply_setup(criteria, anything, load_skills())
        self.assertEqual(criteria.keywords_any, [])
        self.assertFalse(criteria.remote_only is False)
        self.assertIn("full_time", criteria.employment_types)
        self.assertIn("part_time", criteria.employment_types)

    def test_save_and_delete_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presets.json"
            save_presets([], path)
            setup = SearchSetup(
                name="Weekend SQL",
                employment="part_time",
                remote_only=True,
                keyword_mode="custom",
                keywords=["sql"],
                skill_ids=[],
            )
            presets = load_presets(path)
            upsert_preset(presets, setup)
            save_presets(presets, path)
            loaded = load_presets(path)
            self.assertEqual(loaded[0]["id"], "weekend_sql")
            upsert_preset(loaded, SearchSetup(name="Weekend SQL", employment="full_time", keyword_mode="custom", keywords=["sql"]))
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["employment"], "full_time")
            delete_preset(loaded, "weekend sql")
            self.assertEqual(loaded, [])

    def test_configure_search_and_skill_toggle(self):
        skills = load_skills()
        setup = configure_search(
            _reader(["1", "1", "2", "data entry", "", "n"]),
            lambda *_args, **_kwargs: None,
            skills,
        )
        self.assertEqual(setup.employment, "part_time")
        self.assertTrue(setup.remote_only)
        self.assertEqual(setup.keyword_mode, "custom")
        self.assertEqual(setup.keywords, ["data entry"])
        self.assertFalse(setup.upload_crm)
        self.assertTrue(setup.clear_rates)
        self.assertEqual(setup.min_relevance, 15)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "skills.json"
            path.write_text((PACKAGE_DIR / "skills.json").read_text(encoding="utf-8"), encoding="utf-8")
            copied = load_skills(path)
            self.assertFalse(copied["groups"][5]["enabled"])
            _toggle_skills(_reader(["6"]), lambda *_a, **_k: None, copied, path)
            self.assertTrue(load_skills(path)["groups"][5]["enabled"])

    def test_menu_exit(self):
        self.assertIsNone(run_menu(reader=_reader(["4"]), writer=lambda *_a, **_k: None))

    def test_preset_dry_run_and_unknown_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            code = main(
                [
                    "--preset",
                    "Part-time remote data entry",
                    "--dry-run",
                    "--sites",
                    "remotive",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            document = json.loads(out.read_text(encoding="utf-8"))
            criteria = document["run"]["criteria"]
            self.assertEqual(criteria["keywords"]["any"], ["data entry"])
            self.assertEqual(criteria["employment_types"], ["part_time"])
            self.assertTrue(criteria["remote_only"])
            self.assertIsNone(criteria["min_rate"]["hourly_usd"])
        self.assertEqual(main(["--preset", "not-a-preset", "--dry-run"]), 2)

    def test_any_keyword_clears_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            code = main(
                [
                    "--any-keyword",
                    "--dry-run",
                    "--sites",
                    "remotive",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            criteria = json.loads(out.read_text(encoding="utf-8"))["run"]["criteria"]
            self.assertEqual(criteria["keywords"]["any"], [])
            self.assertEqual(criteria["min_relevance"], 15)
