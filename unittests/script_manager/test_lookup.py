"""Lookup by request_id without calling GitHub."""
import json
import unittest

from scripts.script_manager.lookup import artifact_name, lookup, matching_runs


class LookupTests(unittest.TestCase):
    def test_matches_the_run_name_token_and_artifact(self):
        payload = {
            "workflow_runs": [
                {
                    "id": 1,
                    "html_url": "https://github.com/StaticxViper/cjm-dev/actions/runs/1",
                    "status": "completed",
                    "conclusion": "success",
                    "event": "repository_dispatch",
                    "display_title": "script-manager ci-ping abc123",
                    "created_at": "2026-10-23T01:42:00Z",
                },
                {
                    "id": 2,
                    "display_title": "script-manager ci-ping abc1234",
                    "html_url": "https://example.test/2",
                    "status": "completed",
                    "conclusion": "success",
                    "event": "workflow_dispatch",
                },
            ]
        }
        self.assertEqual([item["id"] for item in matching_runs(payload, "abc123")], [1])

        calls = []

        def opener(url, token):
            calls.append((url, token))
            if "artifacts" in url:
                return {
                    "artifacts": [
                        {
                            "id": 9,
                            "name": artifact_name("abc123"),
                            "expired": False,
                            "size_in_bytes": 10,
                            "workflow_run": {"id": 1},
                        }
                    ]
                }
            return payload

        result = lookup("abc123", repo="StaticxViper/cjm-dev", token="secret", opener=opener)
        self.assertEqual(result["runs"][0]["url"], "https://github.com/StaticxViper/cjm-dev/actions/runs/1")
        self.assertEqual(result["artifacts"][0]["workflow_run_id"], 1)
        self.assertIn("script-manager-abc123", result["commands"]["artifact"])
        self.assertEqual(calls[0][1], "secret")
        self.assertIsNone(result["api_error"])

    def test_cli_prints_commands_without_a_repo(self):
        import os
        import subprocess
        import sys

        from scripts.script_manager import repo_root

        env = os.environ.copy()
        env.pop("GITHUB_REPOSITORY", None)
        env.pop("GH_TOKEN", None)
        env.pop("GITHUB_TOKEN", None)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.script_manager", "lookup", "--request-id", "abc123"],
            cwd=str(repo_root()),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = json.loads(proc.stdout)
        self.assertEqual(body["artifact"], "script-manager-abc123")
        self.assertIn("abc123", body["commands"]["runs"])
        self.assertIsNotNone(body["api_error"])
