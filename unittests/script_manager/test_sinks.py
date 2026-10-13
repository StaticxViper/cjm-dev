"""Sink delivery, signatures, and the host allowlist."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.script_manager.contract import Contract
from scripts.script_manager.registry import load_registry
from scripts.script_manager.sinks import deliver
from scripts.script_manager.sinks.http import require_allowed_url, signature

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"


def _contract(**overrides):
    base = dict(
        script="poster",
        args="",
        argv=[],
        request_id="req-sink",
        outputs=["callback"],
        confirm=True,
        dry_run=False,
        callback_url="https://hooks.example.com/done",
        trigger="workflow_dispatch",
    )
    base.update(overrides)
    return Contract(**base)


class SinkTests(unittest.TestCase):
    def test_signature_and_allowlist(self):
        body = b'{"request_id":"req-sink"}'
        digest = signature("top-secret", body)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, signature("top-secret", body))
        self.assertNotEqual(digest, signature("other", body))
        hosts = {"hooks.example.com"}
        self.assertEqual(
            require_allowed_url("https://hooks.example.com/done", hosts),
            "https://hooks.example.com/done",
        )
        with self.assertRaises(Exception):
            require_allowed_url("http://hooks.example.com/done", hosts)
        with self.assertRaises(Exception):
            require_allowed_url("https://evil.example/done", hosts)
        with self.assertRaises(Exception):
            require_allowed_url("https://user:pass@hooks.example.com/done", hosts)

    def test_sink_failure_is_recorded_and_does_not_raise(self):
        registry = load_registry(FIXTURE)
        summary = {
            "name": "poster",
            "exit_code": 0,
            "failure_kind": None,
            "request_id": "req-sink",
            "outputs": [],
            "dry_run": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            path.write_text(json.dumps(summary), encoding="utf-8")
            env = {
                "SCRIPT_MANAGER_CALLBACK_HOSTS": "hooks.example.com",
                "SCRIPT_MANAGER_CALLBACK_SECRET": "",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                deliver(Path(tmp), registry, summary, _contract(), path)
            written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written["exit_code"], 0)
        by_name = {item["name"]: item for item in written["sinks"]}
        self.assertIn("callback", by_name)
        self.assertFalse(by_name["callback"]["ok"])
        self.assertIn("SECRET", by_name["callback"]["error"])
        self.assertTrue(by_name["artifact"]["ok"])

    def test_callback_posts_the_signature(self):
        from scripts.script_manager.sinks import callback as callback_sink

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return 204

        summary = {"name": "poster", "request_id": "req-sink", "exit_code": 3}
        config = {
            "contract": _contract(),
            "env": {
                "SCRIPT_MANAGER_CALLBACK_HOSTS": "hooks.example.com",
                "SCRIPT_MANAGER_CALLBACK_SECRET": "top-secret",
            },
        }
        with mock.patch("scripts.script_manager.sinks.callback.post_json", fake_post):
            callback_sink.send(summary, config)
        self.assertEqual(captured["url"], "https://hooks.example.com/done")
        self.assertEqual(
            captured["headers"]["X-Script-Manager-Signature"],
            signature("top-secret", captured["body"]),
        )
        self.assertIn(b"req-sink", captured["body"])
