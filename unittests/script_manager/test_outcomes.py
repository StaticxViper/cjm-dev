"""Run outcomes, trigger context in run.json, conclude, and cancelled runs."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.script_manager import exit_codes, repo_root
from scripts.script_manager.contract import (
    build_contract,
    job_timeout_minutes,
    read_contract,
    resolve_payload,
    write_contract,
)
from scripts.script_manager.registry import bundled_registry_path, load_registry

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"
REPO = repo_root()
GITHUB_ENV = {
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "StaticxViper/cjm-dev",
    "GITHUB_RUN_ID": "4242",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_ACTOR": "StaticxViper",
    "GITHUB_TRIGGERING_ACTOR": "StaticxViper",
}


def run_cli(args, env=None, registry=FIXTURE):
    base = {key: value for key, value in os.environ.items() if not key.startswith(("GITHUB_", "SCRIPT_MANAGER_"))}
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


def _event(tmp, body) -> str:
    path = Path(tmp) / "event.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return str(path)


class OutcomeTests(unittest.TestCase):
    def test_outcome_for(self):
        self.assertEqual(exit_codes.outcome_for(0, None), "success")
        self.assertEqual(exit_codes.outcome_for(64, "unknown_script"), "rejected")
        self.assertEqual(exit_codes.outcome_for(68, "confirmation_required"), "rejected")
        self.assertEqual(exit_codes.outcome_for(2, "bad_args"), "rejected")
        self.assertEqual(exit_codes.outcome_for(67, "not_runnable"), "failed")
        self.assertEqual(exit_codes.outcome_for(67, "not_runnable", rejected=True), "rejected")
        self.assertEqual(exit_codes.outcome_for(66, "missing_env"), "failed")
        self.assertEqual(exit_codes.outcome_for(1, "child_exit"), "failed")
        self.assertEqual(exit_codes.outcome_for(124, "timeout"), "failed")
        self.assertEqual(exit_codes.outcome_for(None, "cancelled"), "cancelled")

    def test_resolve_outcomes(self):
        registry = load_registry(FIXTURE)
        cases = [
            ("missing-script", False, "rejected"),
            ("broken-echo", False, "rejected"),
            ("echo", False, "rejected"),
            ("poster", False, "rejected"),
            ("poster", True, "success"),
        ]
        for name, confirm, expected in cases:
            contract = build_contract(
                {
                    "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                    "SCRIPT_MANAGER_INPUT_SCRIPT": name,
                    "SCRIPT_MANAGER_INPUT_CONFIRM": "true" if confirm else "false",
                    "SCRIPT_MANAGER_INPUT_REQUEST_ID": "req-o",
                    **GITHUB_ENV,
                }
            )
            payload, _ = resolve_payload(REPO, registry, contract)
            self.assertEqual(payload["outcome"], expected, (name, payload))
            self.assertEqual(payload["trigger"]["event"], "workflow_dispatch")
            self.assertEqual(payload["run"]["url"], "https://github.com/StaticxViper/cjm-dev/actions/runs/4242")

    def test_job_timeout_leaves_room_for_setup(self):
        self.assertEqual(job_timeout_minutes(60), 16)
        self.assertEqual(job_timeout_minutes(1800), 45)
        self.assertEqual(job_timeout_minutes(10 * 3600), 360)


class TriggerTests(unittest.TestCase):
    def test_workflow_dispatch_records_actor_caller_and_run(self):
        contract = build_contract(
            {
                "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                "SCRIPT_MANAGER_INPUT_SCRIPT": "ci-ping",
                "SCRIPT_MANAGER_INPUT_CALLER": "grok-bot",
                **GITHUB_ENV,
            }
        )
        context = contract.context()
        self.assertEqual(
            context["trigger"],
            {"event": "workflow_dispatch", "actor": "StaticxViper", "caller": "grok-bot", "schedule": None},
        )
        self.assertEqual(context["run"]["id"], "4242")

    def test_repository_dispatch_caller_comes_from_the_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = build_contract(
                {
                    "SCRIPT_MANAGER_EVENT_NAME": "repository_dispatch",
                    "SCRIPT_MANAGER_EVENT_PATH": _event(
                        tmp, {"client_payload": {"script": "ci-ping", "request_id": "rd-1", "caller": "crm-dashboard"}}
                    ),
                    **GITHUB_ENV,
                }
            )
        self.assertEqual(contract.trigger, "repository_dispatch")
        self.assertEqual(contract.caller, "crm-dashboard")
        self.assertEqual(contract.context()["trigger"]["event"], "repository_dispatch")

    def test_schedule_records_the_cron_that_fired(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = build_contract(
                {
                    "SCRIPT_MANAGER_EVENT_NAME": "schedule",
                    "SCRIPT_MANAGER_EVENT_PATH": _event(tmp, {"schedule": "0 14 * * 1-5"}),
                    "SCRIPT_MANAGER_INPUT_SCRIPT": "stock-analyzer",
                    "SCRIPT_MANAGER_INPUT_CALLER": "script-manager-schedule",
                    **GITHUB_ENV,
                }
            )
        trigger = contract.context()["trigger"]
        self.assertEqual(trigger["event"], "schedule")
        self.assertEqual(trigger["schedule"], "0 14 * * 1-5")
        self.assertEqual(trigger["caller"], "script-manager-schedule")

    def test_bad_caller_is_rejected(self):
        from scripts.script_manager.contract import ContractError

        with self.assertRaises(ContractError):
            build_contract(
                {
                    "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                    "SCRIPT_MANAGER_INPUT_SCRIPT": "ci-ping",
                    "SCRIPT_MANAGER_INPUT_CALLER": "$(whoami)",
                }
            )

    def test_contract_file_round_trips_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.json"
            contract = build_contract(
                {
                    "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                    "SCRIPT_MANAGER_INPUT_SCRIPT": "ci-ping",
                    "SCRIPT_MANAGER_INPUT_CALLER": "grok-bot",
                    **GITHUB_ENV,
                }
            )
            write_contract(path, contract)
            self.assertEqual(read_contract(path).context(), contract.context())

    def test_run_json_has_trigger_run_and_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract_path = Path(tmp) / "contract.json"
            summary = Path(tmp) / "run.json"
            write_contract(
                contract_path,
                build_contract(
                    {
                        "SCRIPT_MANAGER_EVENT_NAME": "repository_dispatch",
                        "SCRIPT_MANAGER_EVENT_PATH": _event(
                            tmp, {"client_payload": {"script": "ci-ping", "args": "hello", "request_id": "rd-2"}}
                        ),
                        **GITHUB_ENV,
                    }
                ),
            )
            proc = run_cli(
                ["run", "--from-contract", str(contract_path), "--summary-json", str(summary), "--no-dotenv"],
                registry=bundled_registry_path(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            body = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(body["outcome"], "success")
        self.assertEqual(body["trigger"]["event"], "repository_dispatch")
        self.assertEqual(body["trigger"]["actor"], "StaticxViper")
        self.assertEqual(body["run"]["url"], "https://github.com/StaticxViper/cjm-dev/actions/runs/4242")
        self.assertEqual(body["data"], {"ok": True, "script": "ci-ping", "args": ["hello"]})


class RejectionTests(unittest.TestCase):
    def test_child_usage_error_is_bad_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "run.json"
            proc = run_cli(
                ["run", "ci-ping", "--ci", "--non-interactive", "--no-dotenv", "--summary-json", str(summary), "--", "--hello", "world"],
                registry=bundled_registry_path(),
            )
            self.assertEqual(proc.returncode, 2, proc.stderr)
            body = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(body["failure_kind"], "bad_args")
        self.assertEqual(body["outcome"], "rejected")

    def test_child_failure_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "run.json"
            proc = run_cli(["run", "exits", "--no-dotenv", "--summary-json", str(summary), "--", "2"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            body = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(body["failure_kind"], "child_exit")
        self.assertEqual(body["outcome"], "failed")

    def test_unknown_script_summary_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "resolve.json"
            run_cli(["resolve", "does-not-exist", "--summary-json", str(summary)])
            body = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(body["outcome"], "rejected")

    def test_contract_failure_summary_is_rejected_with_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "contract-summary.json"
            run_cli(
                ["contract", "--summary-json", str(summary)],
                env={"SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch", "SCRIPT_MANAGER_INPUT_SCRIPT": "", **GITHUB_ENV},
            )
            body = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(body["outcome"], "rejected")
        self.assertEqual(body["trigger"]["event"], "workflow_dispatch")
        self.assertEqual(body["run"]["id"], "4242")

    def test_stage_result_without_a_summary_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "artifact" / "run.json"
            run_cli(["stage-result", "--dest", str(dest), "--summary", str(Path(tmp) / "missing.json")])
            body = json.loads(dest.read_text(encoding="utf-8"))
            concluded = run_cli(["conclude", "--summary", str(dest)])
        self.assertEqual(body["outcome"], "failed")
        self.assertEqual(concluded.returncode, 1)


class ConcludeTests(unittest.TestCase):
    def _conclude(self, summary: dict | None, job_status: str = "success"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            if summary is not None:
                path.write_text(json.dumps(summary), encoding="utf-8")
            step_summary = Path(tmp) / "step.md"
            output = Path(tmp) / "output.txt"
            proc = run_cli(
                ["conclude", "--summary", str(path), "--job-status", job_status, "--github-output"],
                env={"GITHUB_STEP_SUMMARY": str(step_summary), "GITHUB_OUTPUT": str(output)},
            )
            return proc, step_summary.read_text(encoding="utf-8"), output.read_text(encoding="utf-8")

    def test_success_passes(self):
        proc, summary, output = self._conclude({"name": "ci-ping", "exit_code": 0, "failure_kind": None})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("outcome=success", output)
        self.assertIn("outcome: success", summary)

    def test_rejection_passes_with_a_notice(self):
        proc, summary, output = self._conclude(
            {"name": "api-manager-selftest", "exit_code": 68, "failure_kind": "confirmation_required", "message": "needs confirm"}
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::notice title=script-manager api-manager-selftest rejected::confirmation_required", proc.stdout)
        self.assertIn("outcome=rejected", output)

    def test_failure_fails_with_an_error(self):
        proc, _, output = self._conclude({"name": "stock-analyzer", "exit_code": 1, "failure_kind": "child_exit"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("::error title=script-manager stock-analyzer failed::exit_code 1", proc.stdout)
        self.assertIn("outcome=failed", output)

    def test_cancelled_job_without_a_summary(self):
        proc, summary, output = self._conclude(None, job_status="cancelled")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("outcome=cancelled", output)
        self.assertIn("cancelled", summary)


class CancelledSinkTests(unittest.TestCase):
    def test_sinks_report_a_cancelled_run_without_run_json(self):
        from scripts.script_manager.cli import _missing_summary
        from scripts.script_manager.sinks import STAGING_DIR, deliver

        contract = build_contract(
            {
                "SCRIPT_MANAGER_EVENT_NAME": "workflow_dispatch",
                "SCRIPT_MANAGER_INPUT_SCRIPT": "poster",
                "SCRIPT_MANAGER_INPUT_REQUEST_ID": "req-cancel",
                "SCRIPT_MANAGER_INPUT_OUTPUTS": "artifact",
                **GITHUB_ENV,
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "run.json"
            summary = _missing_summary(contract, "cancelled")
            deliver(Path(tmp), load_registry(FIXTURE), summary, contract, summary_path)
            body = json.loads(summary_path.read_text(encoding="utf-8"))
            staged_body = json.loads((Path(tmp) / STAGING_DIR / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(body["outcome"], "cancelled")
        self.assertEqual(body["request_id"], "req-cancel")
        self.assertEqual(body["run"]["id"], "4242")
        self.assertEqual(staged_body["outcome"], "cancelled")
        self.assertTrue(all(item["ok"] for item in body["sinks"]), body["sinks"])


if __name__ == "__main__":
    unittest.main()
