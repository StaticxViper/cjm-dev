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
                }
            )
        self.assertEqual(contract.script, "poster")
        self.assertEqual(contract.argv, ["--dry"])
        self.assertEqual(contract.outputs, ["artifact", "dashboard"])
        self.assertEqual(contract.request_id, "99")
        self.assertTrue(contract.confirm)

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
            loaded = read_contract(path)
            self.assertEqual(loaded.argv, ["one"])
