"""Registry schema and convention-scan tests."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.script_manager.cli import validate_inventory
from scripts.script_manager.discovery import unregistered_scripts
from scripts.script_manager.registry import RegistryError, bundled_registry_path, load_registry, parse_registry
from scripts.script_manager import repo_root

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"


def _script(**overrides):
    base = {
        "name": "echo",
        "description": "echo",
        "status": "active",
        "entry": {"type": "path", "path": "unittests/script_manager/fixtures/echo_args.py"},
        "cwd": "unittests/script_manager/fixtures",
        "needs_playwright": False,
    }
    base.update(overrides)
    return base


def _dump(data):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, handle)
    handle.close()
    return Path(handle.name)


class RegistryTests(unittest.TestCase):
    def test_fixture_and_real_registry_load(self):
        fixture = load_registry(FIXTURE)
        self.assertIn("echo", fixture.scripts)
        real = load_registry(bundled_registry_path())
        self.assertIn("leadgen", real.scripts)
        self.assertEqual(real.scripts["leadgen-new-business"].alias_of, "leadgen")
        self.assertEqual(
            real.scripts["leadgen-new-business"].default_args[:2],
            ["--mode", "new-business"],
        )
        self.assertEqual(real.scripts["opp-finder"].status, "planned")
        self.assertEqual(real.scripts["opp-finder-v2"].status, "planned")
        self.assertEqual(real.scripts["webhook-manager"].status, "broken")

    def test_duplicate_name(self):
        data = {"version": 1, "scripts": [_script(), _script()]}
        with self.assertRaises(RegistryError) as caught:
            parse_registry(data)
        self.assertTrue(any("duplicate" in err for err in caught.exception.errors))

    def test_bad_name(self):
        with self.assertRaises(RegistryError) as caught:
            parse_registry({"version": 1, "scripts": [_script(name="Lead Gen")]})
        self.assertTrue(any("name must match" in err for err in caught.exception.errors))

    def test_unknown_status(self):
        with self.assertRaises(RegistryError) as caught:
            parse_registry({"version": 1, "scripts": [_script(status="nope")]})
        self.assertTrue(any("status must be" in err for err in caught.exception.errors))

    def test_missing_entry(self):
        raw = _script()
        del raw["entry"]
        with self.assertRaises(RegistryError) as caught:
            parse_registry({"version": 1, "scripts": [raw]})
        self.assertTrue(any("entry is required" in err for err in caught.exception.errors))

    def test_alias_target_missing(self):
        raw = {
            "name": "alias",
            "description": "alias",
            "status": "planned",
            "status_reason": "later",
            "alias_of": "missing",
            "needs_playwright": False,
        }
        with self.assertRaises(RegistryError) as caught:
            parse_registry({"version": 1, "scripts": [raw]})
        self.assertTrue(any("does not exist" in err for err in caught.exception.errors))

    def test_planned_missing_path_is_allowed_and_active_is_not(self):
        planned = _script(
            name="soon",
            status="planned",
            status_reason="not on main yet",
            entry={"type": "path", "path": "scripts/opp_finder/main.py"},
            cwd="scripts/opp_finder",
        )
        registry = parse_registry({"version": 1, "ignore_paths": [], "scripts": [planned]})
        errors, _, _ = validate_inventory(
            repo_root(),
            registry,
            smoke=False,
            check_unregistered=False,
            check_env_docs=False,
        )
        self.assertEqual(errors, [])

        active = _script(
            name="gone",
            entry={"type": "path", "path": "scripts/does-not-exist.py"},
        )
        path = _dump({"version": 1, "ignore_paths": [], "scripts": [active]})
        try:
            loaded = load_registry(path)
        finally:
            path.unlink(missing_ok=True)
        errors, _, _ = validate_inventory(
            repo_root(),
            loaded,
            smoke=False,
            check_unregistered=False,
            check_env_docs=False,
        )
        self.assertTrue(any("does-not-exist.py" in err for err in errors))

    def test_convention_scan_flags_unregistered_and_honors_ignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "orphan.py").write_text("if __name__ == '__main__':\n    pass\n", encoding="utf-8")
            (scripts / "kept.py").write_text('if __name__ == "__main__":\n    pass\n', encoding="utf-8")
            (scripts / "library.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
            deprecated = scripts / "video_editing" / "deprecated"
            deprecated.mkdir(parents=True)
            (deprecated / "old.py").write_text("if __name__ == '__main__':\n    pass\n", encoding="utf-8")
            found = unregistered_scripts(
                root,
                ["scripts/video_editing/deprecated/**"],
                {(scripts / "kept.py").resolve()},
            )
            rels = {path.relative_to(root).as_posix() for path in found}
            self.assertEqual(rels, {"scripts/orphan.py"})


if __name__ == "__main__":
    unittest.main()
