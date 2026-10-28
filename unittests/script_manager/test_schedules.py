"""Cron matching, due scripts, and schedule workflow drift."""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.script_manager import repo_root
from scripts.script_manager.registry import bundled_registry_path, load_registry
from scripts.script_manager.schedules import (
    SCHEDULE_WORKFLOW,
    cron_matches,
    due_matrix,
    is_due,
    parse_cron,
    render_schedule_block,
    schedule_block_matches,
)

REPO = repo_root()
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"


class ScheduleTests(unittest.TestCase):
    def test_weekday_cron_matches_tuesday_afternoon_only(self):
        fields = parse_cron("0 14 * * 1-5")
        tuesday = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
        sunday = datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)
        self.assertTrue(cron_matches(fields, tuesday))
        self.assertFalse(cron_matches(fields, sunday))
        self.assertTrue(is_due("0 14 * * 1-5", tuesday.replace(minute=5)))
        self.assertFalse(is_due("0 14 * * 1-5", tuesday.replace(hour=16)))

    def test_due_matrix_confirms_only_when_the_schedule_says_so(self):
        registry = load_registry(FIXTURE)
        moment = datetime(2026, 10, 13, 14, 10, tzinfo=timezone.utc)
        matrix = due_matrix(registry, now=moment)
        self.assertEqual(matrix["include"], [{"script": "poster", "confirm": True, "outputs": ""}])
        later = due_matrix(registry, now=moment.replace(hour=18))
        self.assertEqual(later["include"], [])
        # A late GitHub schedule still names the cron that fired.
        late = due_matrix(registry, now=moment.replace(hour=18), cron="0 14 * * 1-5")
        self.assertEqual(late["include"], [{"script": "poster", "confirm": True, "outputs": ""}])

    def test_real_schedule_workflow_matches_the_registry(self):
        registry = load_registry(bundled_registry_path())
        text = (REPO / SCHEDULE_WORKFLOW).read_text(encoding="utf-8")
        self.assertTrue(schedule_block_matches(text, registry), render_schedule_block(registry))

    def test_check_fails_on_drift_and_write_repairs_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "script_manager_schedule.yml"
            workflow.write_text(
                "on:\n  schedule:\n    # script-manager:schedules:begin\n"
                "    - cron: '0 0 * * *'\n"
                "    # script-manager:schedules:end\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            check = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.script_manager",
                    "--registry",
                    str(bundled_registry_path()),
                    "schedules",
                    "--check",
                    "--workflow",
                    str(workflow),
                ],
                cwd=str(REPO),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(check.returncode, 65, check.stderr)
            write = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.script_manager",
                    "--registry",
                    str(bundled_registry_path()),
                    "schedules",
                    "--write",
                    "--workflow",
                    str(workflow),
                ],
                cwd=str(REPO),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(write.returncode, 0, write.stderr)
            again = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.script_manager",
                    "--registry",
                    str(bundled_registry_path()),
                    "schedules",
                    "--check",
                    "--workflow",
                    str(workflow),
                ],
                cwd=str(REPO),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)

    def test_workflows_queue_by_request_and_schedule_by_cron(self):
        manager = (REPO / ".github/workflows/script_manager.yml").read_text(encoding="utf-8")
        schedule = (REPO / SCHEDULE_WORKFLOW).read_text(encoding="utf-8")
        self.assertIn("group: script-manager-${{ needs.prepare.outputs.request_id || github.run_id }}", manager)
        self.assertNotIn("group: script-manager-${{ inputs.script", manager)
        self.assertIn("--accept-rejection", manager)
        self.assertIn("stage-cancelled", manager)
        self.assertIn("SCRIPT_MANAGER_ACTOR", manager)
        self.assertIn("trigger: schedule", schedule)
        self.assertIn('"$SCRIPT_MANAGER_CRON"', schedule)
        self.assertNotIn("group: script-manager-${{ matrix.script }}", schedule)
