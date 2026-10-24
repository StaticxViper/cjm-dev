"""CI contract, resolve gates, and shlex args."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.script_manager import repo_root
from scripts.script_manager.contract import build_contract, read_contract, resolve_payload, write_contract
from scripts.script_manager.registry import load_registry

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"
REPO = repo_root()


def run_cli(args, env=None, registry=FIXTURE):
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


class ContractTests(unittest.TestCase):
    def test_shlex_splits_quoted_args(self):
        contract = build_contract(
            {
                "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                "SCRIPT_MANAGER_INPUT_SCRIPT": "poster",
                "SCRIPT_MANAGER_INPUT_ARGS": '--city "Cherry Hill" --flag',
                "SCRIPT_MANAGER_INPUT_REQUEST_ID": "abc123",
                "SCRIPT_MANAGER_INPUT_CONFIRM": "true",
            }
        )
        self.assertEqual(contract.argv, ["--city", "Cherry Hill", "--flag"])
        self.assertEqual(contract.request_id, "abc123")
        self.assertTrue(contract.confirm)
        self.assertEqual(contract.trigger, "workflow_dispatch")

    def test_repository_dispatch_reads_the_event_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            event.write_text(
                json.dumps(
                    {
                        "client_payload": {
                            "script": "poster",
                            "args": "--dry",
                            "outputs": "artifact,dashboard",
                            "confirm": True,
                            "caller": "grok-bot",
                        }
                    }
                ),
                encoding="utf-8",
            )
            contract = build_contract(
                {
                    "SCRIPT_MANAGER_EVENT_NAME": "repository_dispatch",
                    "SCRIPT_MANAGER_EVENT_PATH": str(event),
                    "SCRIPT_MANAGER_INPUT_SCRIPT": "",
                    "SCRIPT_MANAGER_RUN_ID": "99",
                    "SCRIPT_MANAGER_ACTOR": "StaticxViper",
                    "SCRIPT_MANAGER_RUN_URL": "https://github.com/StaticxViper/cjm-dev/actions/runs/99",
                }
            )
        self.assertEqual(contract.script, "poster")
        self.assertEqual(contract.argv, ["--dry"])
        self.assertEqual(contract.outputs, ["artifact", "dashboard"])
        self.assertEqual(contract.request_id, "99")
        self.assertTrue(contract.confirm)
        self.assertEqual(contract.trigger, "repository_dispatch")
        self.assertEqual(contract.actor, "StaticxViper")
        self.assertEqual(contract.caller, "grok-bot")
        self.assertEqual(contract.run_url, "https://github.com/StaticxViper/cjm-dev/actions/runs/99")

    def test_bad_script_name_is_usage(self):
        proc = run_cli(
            ["contract", "--json"],
            env={
                "SCRIPT_MANAGER_INPUT_SCRIPT": "Not A Script",
                "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
            },
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)

    def test_resolve_exit_codes(self):
        registry = load_registry(FIXTURE)
        cases = [
            ("missing-script", False, False, 64),
            ("broken-echo", False, False, 67),
            ("echo", False, False, 67),
            ("local-tool", False, False, 67),
            ("poster", False, False, 68),
            ("poster", True, False, 0),
            ("poster", False, True, 0),
        ]
        for name, confirm, dry_run, expected in cases:
            contract = build_contract(
                {
                    "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                    "SCRIPT_MANAGER_INPUT_SCRIPT": name,
                    "SCRIPT_MANAGER_INPUT_CONFIRM": "true" if confirm else "false",
                    "SCRIPT_MANAGER_INPUT_DRY_RUN": "true" if dry_run else "false",
                    "SCRIPT_MANAGER_INPUT_REQUEST_ID": "req-1",
                }
            )
            payload, code = resolve_payload(REPO, registry, contract)
            self.assertEqual(code, expected, payload)
            self.assertEqual(payload["request_id"], "req-1")

    def test_cli_resolve_and_run_from_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.json"
            summary = Path(tmp) / "run.json"
            contract = build_contract(
                {
                    "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                    "SCRIPT_MANAGER_INPUT_SCRIPT": "poster",
                    "SCRIPT_MANAGER_INPUT_ARGS": "one",
                    "SCRIPT_MANAGER_INPUT_CONFIRM": "true",
                    "SCRIPT_MANAGER_INPUT_REQUEST_ID": "req-9",
                }
            )
            write_contract(path, contract)
            resolved = run_cli(["resolve", "--from-contract", str(path), "--json"])
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            body = json.loads(resolved.stdout)
            self.assertTrue(body["ok"])
            self.assertFalse(body["needs_playwright"])
            self.assertIn("artifact", body["selected_outputs"])
            ran = run_cli(
                [
                    "run",
                    "--from-contract",
                    str(path),
                    "--summary-json",
                    str(summary),
                    "--no-dotenv",
                ]
            )
            self.assertEqual(ran.returncode, 0, ran.stderr)
            written = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(written["request_id"], "req-9")
            self.assertEqual(written["exit_code"], 0)
            self.assertEqual(written["trigger"]["event"], "workflow_dispatch")
            self.assertIsNotNone(written["trigger"])
            loaded = read_contract(path)
            self.assertEqual(loaded.argv, ["one"])

    def test_rejected_resolve_writes_a_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "resolve.json"
            staged = Path(tmp) / "script-manager-artifact" / "run.json"
            proc = run_cli(
                ["resolve", "no-such-script", "--json", "--summary-json", str(summary)]
            )
            self.assertEqual(proc.returncode, 64, proc.stderr)
            body = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(body["failure_kind"], "unknown_script")
            self.assertEqual(body["request_id"], "resolve")
            self.assertIn("unknown script", body["message"])
            staged_proc = run_cli(
                ["stage-result", "--dest", str(staged), "--summary", str(summary)]
            )
            self.assertEqual(staged_proc.returncode, 0, staged_proc.stderr)
            copied = json.loads(staged.read_text(encoding="utf-8"))
            self.assertEqual(copied["failure_kind"], "unknown_script")
            self.assertEqual(copied["request_id"], "resolve")

    def test_contract_failure_writes_a_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "contract.json"
            output = Path(tmp) / "github-output.txt"
            proc = run_cli(
                ["contract", "--summary-json", str(summary), "--github-output"],
                env={
                    "SCRIPT_MANAGER_EVENT_NAME": "",
                    "SCRIPT_MANAGER_INPUT_SCRIPT": "",
                    "SCRIPT_MANAGER_INPUT_REQUEST_ID": "req-reject",
                    "GITHUB_OUTPUT": str(output),
                },
            )
            self.assertEqual(proc.returncode, 2, proc.stderr)
            body = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(body["failure_kind"], "usage")
            self.assertEqual(body["request_id"], "req-reject")
            self.assertIn("script is required", body["message"])
            self.assertIn("request_id=req-reject", output.read_text(encoding="utf-8"))

    def test_schedule_trigger_records_schedule_as_the_caller(self):
        contract = build_contract(
            {
                "SCRIPT_MANAGER_EVENT_NAME": "workflow_call",
                "SCRIPT_MANAGER_INPUT_TRIGGER": "schedule",
                "SCRIPT_MANAGER_INPUT_SCRIPT": "poster",
                "SCRIPT_MANAGER_ACTOR": "StaticxViper",
                "SCRIPT_MANAGER_CALLER": "StaticxViper",
                "SCRIPT_MANAGER_INPUT_REQUEST_ID": "schedule-poster-1",
                "SCRIPT_MANAGER_RUN_URL": "https://github.com/StaticxViper/cjm-dev/actions/runs/1",
            }
        )
        self.assertEqual(contract.trigger, "schedule")
        self.assertEqual(contract.caller, "schedule")
        self.assertEqual(contract.actor, "StaticxViper")

    def test_expected_rejection_exits_zero_and_keeps_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "resolve.json"
            output = Path(tmp) / "github-output.txt"
            proc = run_cli(
                [
                    "resolve",
                    "no-such-script",
                    "--accept-rejection",
                    "--github-output",
                    "--summary-json",
                    str(summary),
                ],
                env={"GITHUB_OUTPUT": str(output)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            body = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(body["exit_code"], 64)
            self.assertEqual(body["failure_kind"], "unknown_script")
            self.assertIn("rejected=true", output.read_text(encoding="utf-8"))
            child = run_cli(
                ["run", "exits", "--accept-rejection", "--non-interactive", "--no-dotenv", "--", "2"]
            )
            self.assertEqual(child.returncode, 2, child.stderr)

    def test_cancelled_summary_names_the_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "script-manager-artifact" / "run.json"
            proc = run_cli(
                ["stage-cancelled", "--dest", str(dest)],
                env={
                    "SCRIPT_MANAGER_REQUEST_ID": "req-cancel",
                    "SCRIPT_MANAGER_SCRIPT": "ci-ping",
                    "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                    "SCRIPT_MANAGER_ACTOR": "StaticxViper",
                    "SCRIPT_MANAGER_RUN_ID": "42",
                    "SCRIPT_MANAGER_RUN_URL": "https://github.com/StaticxViper/cjm-dev/actions/runs/42",
                },
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            body = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(body["failure_kind"], "cancelled")
            self.assertEqual(body["request_id"], "req-cancel")
            self.assertEqual(body["trigger"]["event"], "workflow_dispatch")
            self.assertEqual(body["run_url"], "https://github.com/StaticxViper/cjm-dev/actions/runs/42")
