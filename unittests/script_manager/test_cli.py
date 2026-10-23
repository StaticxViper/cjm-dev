"""CLI shapes and exit codes."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.script_manager import repo_root
from scripts.script_manager.registry import bundled_registry_path, load_registry
from scripts.script_manager.runner import smoke_import

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"
REPO = repo_root()
INFO_KEYS = {
    "name",
    "status",
    "entry",
    "cwd",
    "command",
    "needs_playwright_resolved",
    "env",
    "timeout_seconds",
    "outputs",
    "default_outputs",
    "ci_allowed",
    "schedule",
}


def run_cli(args, registry=FIXTURE, env=None):
    base = os.environ.copy()
    base.pop("CI", None)
    base["PYTHONIOENCODING"] = "utf-8"
    base["PYTHONUTF8"] = "1"
    if env:
        base.update(env)
    return subprocess.run(
        [sys.executable, "-m", "scripts.script_manager", "--registry", str(registry), *args],
        cwd=str(REPO),
        env=base,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        check=False,
    )


class CliTests(unittest.TestCase):
    def test_list_and_info_json_shapes(self):
        listed = run_cli(["list", "--json"])
        self.assertEqual(listed.returncode, 0, listed.stderr)
        rows = json.loads(listed.stdout)
        self.assertTrue(rows)
        self.assertTrue({"name", "status", "needs_playwright", "ci_allowed", "tags", "description"} <= set(rows[0]))
        info = run_cli(["info", "--json", "echo"])
        self.assertEqual(info.returncode, 0, info.stderr)
        payload = json.loads(info.stdout)
        self.assertEqual(set(payload), INFO_KEYS)
        self.assertIsInstance(payload["command"], list)
        self.assertIsInstance(payload["needs_playwright_resolved"], bool)
        self.assertEqual(set(payload["env"]), {"required_missing", "optional_missing", "conditional_missing"})

    def test_real_list_ci_and_info(self):
        listed = run_cli(["list", "--ci", "--json"], registry=bundled_registry_path())
        self.assertEqual(listed.returncode, 0, listed.stderr)
        names = {row["name"] for row in json.loads(listed.stdout)}
        self.assertIn("stock-analyzer", names)
        self.assertIn("leadgen", names)
        self.assertIn("ci-ping", names)
        self.assertNotIn("webhook-manager", names)
        self.assertNotIn("clip-generator", names)
        self.assertNotIn("opp-finder-v2", names)
        info = run_cli(["info", "--json", "stock-analyzer"], registry=bundled_registry_path())
        self.assertEqual(info.returncode, 0, info.stderr)
        payload = json.loads(info.stdout)
        self.assertEqual(set(payload), INFO_KEYS)
        self.assertFalse(payload["needs_playwright_resolved"])
        self.assertTrue(payload["ci_allowed"])
        self.assertEqual(payload["schedule"]["cron"], "0 14 * * 1-5")
        ping = run_cli(["info", "ci-ping", "--ci", "--json"], registry=bundled_registry_path())
        self.assertEqual(ping.returncode, 0, ping.stderr)
        ping_body = json.loads(ping.stdout)
        self.assertTrue(ping_body["ok"])
        self.assertEqual(ping_body["exit_code"], 0)
        clip = run_cli(["info", "clip-generator", "--ci", "--json"], registry=bundled_registry_path())
        self.assertEqual(clip.returncode, 67, clip.stderr)
        self.assertEqual(json.loads(clip.stdout)["failure_kind"], "not_runnable")

    def test_info_ci_does_not_require_confirm(self):
        allowed = run_cli(["info", "poster", "--ci", "--json"])
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertTrue(json.loads(allowed.stdout)["ok"])
        local = run_cli(["info", "local-tool", "--ci", "--json"])
        self.assertEqual(local.returncode, 67, local.stderr)
        self.assertEqual(json.loads(local.stdout)["failure_kind"], "not_runnable")
        plain = run_cli(["info", "--json", "echo"])
        self.assertEqual(set(json.loads(plain.stdout)), INFO_KEYS)

    def test_ci_ping_summary_includes_stdout_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "run.json"
            proc = run_cli(
                [
                    "run",
                    "ci-ping",
                    "--non-interactive",
                    "--no-dotenv",
                    "--summary-json",
                    str(summary),
                    "--",
                    "hello",
                ],
                registry=bundled_registry_path(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            written = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(written["data"], {"ok": True, "script": "ci-ping", "args": ["hello"]})
            self.assertIsNone(written["failure_kind"])
            self.assertIn("hello", written["stdout_tail"])

    def test_unknown_script_suggests_a_close_name(self):
        proc = run_cli(["run", "ecko"])
        self.assertEqual(proc.returncode, 64, proc.stderr)
        self.assertIn("echo", proc.stderr)
        summary = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(summary["failure_kind"], "unknown_script")

    def test_broken_confirm_and_interactive_exits(self):
        broken = run_cli(["run", "broken-echo"])
        self.assertEqual(broken.returncode, 67, broken.stderr)
        self.assertEqual(json.loads(broken.stdout)["failure_kind"], "not_runnable")
        confirm = run_cli(["run", "needs-yes"])
        self.assertEqual(confirm.returncode, 68, confirm.stderr)
        self.assertEqual(json.loads(confirm.stdout)["failure_kind"], "confirmation_required")
        prompted = run_cli(["run", "prompter", "--non-interactive"])
        self.assertEqual(prompted.returncode, 69, prompted.stderr)
        self.assertEqual(json.loads(prompted.stdout)["failure_kind"], "would_prompt")

    def test_validate_strict_promotes_warnings(self):
        loose = run_cli(["validate"])
        self.assertEqual(loose.returncode, 0, loose.stderr)
        self.assertIn("unregistered script:", loose.stdout)
        strict = run_cli(["validate", "--strict"])
        self.assertEqual(strict.returncode, 65, strict.stdout + strict.stderr)
        self.assertIn("unregistered script:", strict.stdout)

    def test_real_registry_validates(self):
        plain = run_cli(["validate"], registry=bundled_registry_path())
        self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
        strict = run_cli(["validate", "--strict"], registry=bundled_registry_path())
        self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)

    def test_smoke_reports_logger_import_failure(self):
        registry = load_registry(bundled_registry_path())
        for name in (
            "blog-automation",
            "webhook-manager",
            "json-formatter",
            "lead-ingest",
            "lovable-automation",
        ):
            code, detail = smoke_import(repo_root(), registry.get(name))
            self.assertNotEqual(code, 0, detail)
            self.assertIn("setup_logger", detail)

    def test_summary_json_and_github_summary(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            step = Path(tmp) / "step.md"
            env = os.environ.copy()
            env["GITHUB_STEP_SUMMARY"] = str(step)
            env.pop("CI", None)
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.script_manager",
                    "--registry",
                    str(FIXTURE),
                    "run",
                    "echo",
                    "--summary-json",
                    str(summary_path),
                    "--github-summary",
                ],
                cwd=str(REPO),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            written = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(written["name"], "echo")
            self.assertEqual(written["exit_code"], 0)
            self.assertIsNone(written["failure_kind"])
            body = step.read_text(encoding="utf-8")
            self.assertIn("script-manager: echo", body)
            self.assertIn("exit_code: 0", body)

    def test_manage_py_from_another_directory(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(REPO / "manage.py"), "list", "--json"],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            names = {row["name"] for row in json.loads(proc.stdout)}
            self.assertIn("leadgen", names)


if __name__ == "__main__":
    unittest.main()
