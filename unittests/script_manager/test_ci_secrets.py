"""The workflow secrets block must name every env var a CI script declares."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.script_manager import repo_root
from scripts.script_manager.ci_secrets import ci_secret_errors
from scripts.script_manager.registry import bundled_registry_path, load_registry

REPO = repo_root()


class CiSecretTests(unittest.TestCase):
    def test_real_workflow_lists_every_declared_name(self):
        registry = load_registry(bundled_registry_path())
        errors = ci_secret_errors(registry, REPO / ".github/workflows/script_manager.yml")
        self.assertEqual(errors, [], errors)

    def test_missing_name_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / "workflow.yml"
            workflow.write_text(
                "env:\n  # script-manager:secrets:begin\n"
                "  PRESENT: ${{ secrets.PRESENT }}\n"
                "  # script-manager:secrets:end\n",
                encoding="utf-8",
            )
            registry_path = root / "registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "scripts": [
                            {
                                "name": "needs-secret",
                                "description": "Needs a secret",
                                "status": "active",
                                "entry": {"type": "path", "path": "missing.py"},
                                "cwd": ".",
                                "needs_playwright": False,
                                "ci_allowed": True,
                                "env": {"required": ["MISSING_SECRET"]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            registry = load_registry(registry_path)
            errors = ci_secret_errors(registry, workflow)
        self.assertTrue(any("MISSING_SECRET" in error for error in errors), errors)

    def test_ci_allowed_and_local_only_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / "workflow.yml"
            workflow.write_text(
                "# script-manager:secrets:begin\n# script-manager:secrets:end\n",
                encoding="utf-8",
            )
            registry_path = root / "registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "scripts": [
                            {
                                "name": "desk",
                                "description": "Stays on this machine",
                                "status": "active",
                                "entry": {"type": "path", "path": "missing.py"},
                                "cwd": ".",
                                "needs_playwright": False,
                                "ci_allowed": True,
                                "local_only": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            errors = ci_secret_errors(load_registry(registry_path), workflow)
        self.assertTrue(any("local_only" in error for error in errors), errors)
