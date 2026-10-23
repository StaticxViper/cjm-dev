"""Finding a workflow run from a request_id."""
import io
import json
import unittest
import zipfile

from scripts.script_manager.lookup import lookup, run_name_matches, wait_for

REPO = "StaticxViper/cjm-dev"
RUN_URL = "https://github.com/StaticxViper/cjm-dev/actions/runs/{}"


def _run(run_id, title, status="completed", conclusion="success", event="workflow_dispatch"):
    return {
        "id": run_id,
        "display_title": title,
        "html_url": RUN_URL.format(run_id),
        "status": status,
        "conclusion": conclusion,
        "event": event,
        "created_at": "2026-10-23T01:39:15Z",
    }


def _zip(payload: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("run.json", json.dumps(payload))
    return buffer.getvalue()


class FakeGitHub:
    def __init__(self, runs, artifacts=None, by_id=None, archive=b""):
        self.repo = REPO
        self.runs = runs
        self.artifacts = artifacts or {}
        self.by_id = by_id or {}
        self.archive = archive
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append(path)
        if path.endswith("/workflows/script_manager.yml/runs"):
            return {"workflow_runs": self.runs}
        if path.endswith("/artifacts"):
            run_id = int(path.split("/")[-2])
            return {"artifacts": self.artifacts.get(run_id, [])}
        run_id = int(path.rsplit("/", 1)[-1])
        return self.by_id.get(run_id, {})

    def get_bytes(self, url):
        return self.archive


class LookupTests(unittest.TestCase):
    def test_run_name_must_end_with_the_request_id(self):
        self.assertTrue(run_name_matches("script-manager ci-ping t2-rd", "t2-rd"))
        self.assertFalse(run_name_matches("script-manager ci-ping t2-rd2", "t2-rd"))
        self.assertFalse(run_name_matches("Script Manager Schedules", "t2-rd"))

    def test_finds_a_run_and_its_result(self):
        artifact = {"id": 77, "name": "script-manager-t2-real2", "archive_download_url": "https://api/zip", "expired": False}
        client = FakeGitHub(
            runs=[_run(2, "script-manager ci-ping t2-rd2"), _run(1, "script-manager api-manager-selftest t2-real2")],
            artifacts={1: [artifact]},
            archive=_zip({"request_id": "t2-real2", "outcome": "success", "exit_code": 0}),
        )
        report = lookup(client, "t2-real2", fetch_result=True)
        self.assertTrue(report["found"])
        self.assertEqual(report["run_url"], RUN_URL.format(1))
        self.assertEqual(report["artifact_url"], RUN_URL.format(1) + "/artifacts/77")
        self.assertEqual(report["outcome"], "success")
        self.assertEqual(report["result"]["exit_code"], 0)

    def test_cancelled_run_reports_cancelled_without_an_artifact(self):
        client = FakeGitHub(runs=[_run(5, "script-manager api-manager-selftest t2-real", conclusion="cancelled")])
        report = lookup(client, "t2-real")
        self.assertTrue(report["found"])
        self.assertEqual(report["conclusion"], "cancelled")
        self.assertEqual(report["outcome"], "cancelled")
        self.assertIsNone(report["artifact_url"])

    def test_schedule_request_id_reads_the_run_id(self):
        client = FakeGitHub(runs=[], by_id={991: _run(991, "Script Manager Schedules", event="schedule")})
        report = lookup(client, "schedule-stock-analyzer-991")
        self.assertTrue(report["found"])
        self.assertEqual(report["event"], "schedule")
        self.assertNotIn(f"/repos/{REPO}/actions/workflows/script_manager.yml/runs", client.calls)

    def test_not_found(self):
        report = lookup(FakeGitHub(runs=[_run(1, "script-manager ci-ping other")]), "missing")
        self.assertFalse(report["found"])
        self.assertEqual(report["artifact"], "script-manager-missing")

    def test_wait_polls_until_complete(self):
        client = FakeGitHub(runs=[_run(3, "script-manager ci-ping w1", status="in_progress", conclusion=None)])
        ticks = iter([0, 1, 2, 3])

        def sleep(_):
            client.runs = [_run(3, "script-manager ci-ping w1")]

        report = wait_for(client, "w1", timeout_s=60, sleep=sleep, clock=lambda: next(ticks))
        self.assertEqual(report["status"], "completed")


if __name__ == "__main__":
    unittest.main()
