"""Env checks: missing names, conditionals, dotenv precedence, declared scope."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.script_manager import repo_root
from scripts.script_manager.envcheck import args_match

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"
REPO = repo_root()
SENTINEL = "hunter2-secret-value"
FILE_SENTINEL = "hunter2-file-secret"


def run_cli(args, env=None):
    base = os.environ.copy()
    base.pop("CI", None)
    for key in ("REQUIRE_ME", "DASH_KEY", "OPT_KEY", "FOO", "UNDECLARED", "LEAK_ME", "LEAK_FILE"):
        base.pop(key, None)
    base["PYTHONIOENCODING"] = "utf-8"
    base["PYTHONUTF8"] = "1"
    if env:
        base.update(env)
    return subprocess.run(
        [sys.executable, "-m", "scripts.script_manager", "--registry", str(FIXTURE), *args],
        cwd=str(REPO),
        env=base,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        check=False,
    )


class EnvCheckTests(unittest.TestCase):
    def test_token_matching(self):
        self.assertTrue(args_match("--output=dashboard", ["--output", "dashboard"]))
        self.assertTrue(args_match("--output=dashboard", ["--output=dashboard"]))
        self.assertFalse(args_match("--output=dashboard", ["--output", "json"]))
        self.assertTrue(args_match("--leadgen-type=playwright", ["--leadgen-type", "playwright"]))
        self.assertTrue(args_match("--from-crm", ["--from-crm"]))
        self.assertFalse(args_match("--from-crm", ["--dashboard"]))

    def test_missing_required_lists_names_and_hides_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(f"LEAK_FILE={FILE_SENTINEL}\n", encoding="utf-8")
            proc = run_cli(
                ["run", "env-required", "--env-file", str(env_file), "--summary-json", str(Path(tmp) / "summary.json")],
                env={"LEAK_ME": SENTINEL},
            )
            combined = proc.stdout + proc.stderr + (Path(tmp) / "summary.json").read_text(encoding="utf-8")
            self.assertEqual(proc.returncode, 66, combined)
            self.assertIn("REQUIRE_ME", proc.stderr)
            self.assertNotIn(SENTINEL, combined)
            self.assertNotIn(FILE_SENTINEL, combined)

    def test_conditional_env_matches_only_explicit_args(self):
        plain = run_cli(["run", "env-conditional", "--", "OPT_KEY"])
        self.assertEqual(plain.returncode, 0, plain.stderr)
        dashed = run_cli(["run", "env-conditional", "--", "--output=dashboard"])
        self.assertEqual(dashed.returncode, 66, dashed.stderr)
        self.assertIn("DASH_KEY", dashed.stderr)
        split = run_cli(["run", "env-conditional", "--", "--output", "dashboard"])
        self.assertEqual(split.returncode, 66, split.stderr)
        other = run_cli(["run", "env-conditional", "--", "--output", "json"])
        self.assertEqual(other.returncode, 0, other.stderr)

    def test_process_env_beats_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(f"FOO=from-file\nLEAK_FILE={FILE_SENTINEL}\n", encoding="utf-8")
            proc = run_cli(
                ["run", "env-foo", "--env-file", str(env_file), "--", "--check-foo"],
                env={"FOO": "from-process"},
            )
            combined = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, combined)
            self.assertNotIn("from-file", combined)
            self.assertNotIn(FILE_SENTINEL, combined)
            self.assertNotIn("from-process", combined)

    def test_no_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(f"REQUIRE_ME={SENTINEL}\n", encoding="utf-8")
            proc = run_cli(["run", "env-required", "--env-file", str(env_file), "--no-dotenv"])
            combined = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 66, combined)
            self.assertIn("REQUIRE_ME", proc.stderr)
            self.assertNotIn(SENTINEL, combined)

    def test_declared_scope_hides_undeclared_names(self):
        proc = run_cli(
            ["run", "env-scope", "--env-scope", "declared", "--", "OPT_KEY", "UNDECLARED"],
            env={"OPT_KEY": "1", "UNDECLARED": SENTINEL},
        )
        combined = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, combined)
        set_line = next(line for line in proc.stdout.splitlines() if line.startswith("SET "))
        self.assertIn("OPT_KEY", set_line)
        self.assertNotIn("UNDECLARED", set_line)
        self.assertNotIn(SENTINEL, combined)


if __name__ == "__main__":
    unittest.main()
