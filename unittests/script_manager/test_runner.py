"""Runner tests: passthrough, cwd, timeout, dry-run."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.script_manager import repo_root

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"
REPO = repo_root()


def run_cli(args, env=None):
    base = os.environ.copy()
    base.pop("CI", None)
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


def echo_payload(stdout):
    for line in stdout.splitlines():
        if line.startswith("ECHO "):
            return json.loads(line[len("ECHO "):])
    return None


def summary_line(stdout):
    for line in reversed(stdout.splitlines()):
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise AssertionError(f"no summary in stdout: {stdout!r}")


def pid_alive(pid):
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunnerTests(unittest.TestCase):
    def test_passthrough_is_unchanged(self):
        proc = run_cli(["run", "echo", "--", "--city", "Cherry Hill", "--city", "Newark", "--output=both", "-x"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = echo_payload(proc.stdout)
        self.assertEqual(
            payload["argv"],
            ["--city", "Cherry Hill", "--city", "Newark", "--output=both", "-x"],
        )

    def test_default_args_and_no_defaults(self):
        with_defaults = run_cli(["run", "echo-defaults", "--", "--city", "X"])
        self.assertEqual(echo_payload(with_defaults.stdout)["argv"], ["--from-default", "--city", "X"])
        without = run_cli(["run", "echo-defaults", "--no-defaults", "--", "--city", "X"])
        self.assertEqual(echo_payload(without.stdout)["argv"], ["--city", "X"])

    def test_cwd_and_pythonpath(self):
        proc = run_cli(["run", "echo"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = echo_payload(proc.stdout)
        self.assertEqual(Path(payload["cwd"]).resolve(), (REPO / "unittests/script_manager/fixtures").resolve())
        self.assertIn(str(REPO), payload["pythonpath"])

    def test_child_exit_code_is_propagated(self):
        proc = run_cli(["run", "exits", "--", "7"])
        self.assertEqual(proc.returncode, 7, proc.stderr)
        summary = summary_line(proc.stdout)
        self.assertEqual(summary["exit_code"], 7)
        self.assertEqual(summary["failure_kind"], "child_exit")

    def test_timeout_kills_the_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "child.pid"
            proc = run_cli(
                ["run", "sleeper", "--timeout", "2", "--", "30", "--child-pid-file", str(pid_file)]
            )
            self.assertEqual(proc.returncode, 124, proc.stderr)
            summary = summary_line(proc.stdout)
            self.assertTrue(summary["timed_out"])
            self.assertEqual(summary["failure_kind"], "timeout")
            self.assertTrue(pid_file.is_file(), "grandchild pid file was not written")
            grandchild = int(pid_file.read_text(encoding="utf-8").strip())
            self.assertFalse(pid_alive(grandchild), f"grandchild {grandchild} is still running")

    def test_dry_run_does_not_start_the_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            touch = Path(tmp) / "touched.txt"
            proc = run_cli(["run", "echo", "--dry-run", "--", "--touch", str(touch)])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIsNone(echo_payload(proc.stdout))
            self.assertFalse(touch.exists())
            summary = summary_line(proc.stdout)
            self.assertTrue(summary["dry_run"])
            self.assertIn("--touch", summary["argv"])


if __name__ == "__main__":
    unittest.main()
