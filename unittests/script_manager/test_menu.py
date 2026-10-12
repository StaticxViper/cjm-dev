"""Interactive menu and queue."""

import unittest
from pathlib import Path

from scripts.script_manager import repo_root
from scripts.script_manager.menus.leadgen import configure as configure_leadgen
from scripts.script_manager.menus.session import menu_scripts, run_session
from scripts.script_manager.registry import bundled_registry_path, load_registry
from scripts.script_manager.runner import run_script

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"


def _reader(answers):
    items = iter(answers)

    def reader(_prompt=""):
        return next(items)

    return reader


class MenuTests(unittest.TestCase):
    def test_queue_runs_two_scripts_in_order(self):
        registry = load_registry(FIXTURE)
        registry.get("echo").menu = "flags"
        registry.get("echo").prompts = [
            {"arg": "--city", "prompt": "City", "kind": "str", "optional": True, "choices": [], "split": False}
        ]
        registry.get("echo-defaults").menu = "confirm"
        answers = [
            "1",
            "1",
            "Cherry Hill",
            "",
            "y",
            "1",
            "2",
            "y",
            "4",
            "5",
        ]
        ran = []

        def runner(repo, script, options):
            summary = run_script(repo, script, options)
            ran.append(summary["argv"])
            return summary

        code = run_session(
            registry,
            reader=_reader(answers),
            writer=lambda *_args, **_kwargs: None,
            repo=repo_root(),
            runner=runner,
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(ran), 2)
        self.assertIn("--city", ran[0])
        city_at = ran[0].index("--city")
        self.assertEqual(ran[0][city_at + 1], "Cherry Hill")
        self.assertIn("--from-default", ran[1])

    def test_leadgen_run_returns_args_without_starting(self):
        answers = ["1", "1", "1", "y"]
        args = configure_leadgen(
            reader=_reader(answers),
            writer=lambda *_args, **_kwargs: None,
            repo=repo_root(),
        )
        self.assertIsNotNone(args)
        self.assertIn("--defaults", args)
        self.assertIn("--leadgen-type", args)

    def test_real_registry_menu_names(self):
        registry = load_registry(bundled_registry_path())
        names = {script.name for script in menu_scripts(registry)}
        self.assertIn("leadgen", names)
        self.assertIn("grocery-cli", names)
        self.assertIn("opp-finder-v2", names)
        self.assertNotIn("leadgen-new-business", names)
        self.assertNotIn("grocery-sync", names)
        self.assertNotIn("webhook-manager", names)
        self.assertNotIn("api-manager-selftest", names)
        self.assertIsNone(registry.get("leadgen-new-business").menu)
