"""Sink delivery, signatures, and the host allowlist."""
import json
import os
import smtplib
import socketserver
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

    def test_loopback_http_is_allowed_when_listed(self):
        hosts = {"127.0.0.1"}
        self.assertEqual(
            require_allowed_url("http://127.0.0.1:9/hook", hosts),
            "http://127.0.0.1:9/hook",
        )
        with self.assertRaises(Exception):
            require_allowed_url("http://127.0.0.1:9/hook", {"hooks.example.com"})

    def test_callback_posts_to_a_local_server(self):
        from scripts.script_manager.sinks import callback as callback_sink

        server = _HttpCapture()
        try:
            url = f"http://127.0.0.1:{server.port}/callback"
            summary = {
                "name": "poster",
                "request_id": "req-callback",
                "exit_code": 0,
                "run_url": "https://github.com/StaticxViper/cjm-dev/actions/runs/7",
                "trigger": {"event": "repository_dispatch", "actor": "StaticxViper", "caller": "grok-bot"},
            }
            config = {
                "contract": _contract(callback_url=url),
                "env": {
                    "SCRIPT_MANAGER_CALLBACK_HOSTS": "127.0.0.1",
                    "SCRIPT_MANAGER_CALLBACK_SECRET": "top-secret",
                },
            }
            callback_sink.send(summary, config)
            self.assertEqual(len(server.requests), 1)
            posted = server.requests[0]
            self.assertEqual(posted["path"], "/callback")
            self.assertEqual(
                posted["headers"]["X-Script-Manager-Signature"],
                signature("top-secret", posted["body"]),
            )
            body = json.loads(posted["body"])
            self.assertEqual(body["request_id"], "req-callback")
            self.assertIn("actions/runs/7", body["run_url"])
            self.assertEqual(body["trigger"]["event"], "repository_dispatch")
        finally:
            server.close()

    def test_dashboard_posts_to_a_local_server(self):
        from scripts.script_manager.sinks import dashboard as dashboard_sink

        server = _HttpCapture()
        try:
            url = f"http://127.0.0.1:{server.port}/dashboard"
            summary = {"name": "poster", "request_id": "req-dash", "exit_code": 0, "run_url": "https://example.test/run"}
            config = {
                "contract": _contract(),
                "env": {
                    "SCRIPT_MANAGER_CALLBACK_HOSTS": "127.0.0.1",
                    "SCRIPT_MANAGER_DASHBOARD_URL": url,
                    "CRM_MCP_MV_LLC": "dashboard-token",
                },
            }
            dashboard_sink.send(summary, config)
            posted = server.requests[0]
            self.assertEqual(posted["headers"]["Authorization"], "Bearer dashboard-token")
            self.assertEqual(json.loads(posted["body"])["request_id"], "req-dash")
            self.assertNotIn("dashboard-token", posted["body"].decode("utf-8"))
        finally:
            server.close()

    def test_dashboard_error_does_not_include_the_token(self):
        from scripts.script_manager.sinks import dashboard as dashboard_sink

        server = _HttpCapture(status=500)
        try:
            url = f"http://127.0.0.1:{server.port}/dashboard"
            config = {
                "contract": _contract(),
                "env": {
                    "SCRIPT_MANAGER_CALLBACK_HOSTS": "127.0.0.1",
                    "SCRIPT_MANAGER_DASHBOARD_URL": url,
                    "CRM_MCP_MV_LLC": "dashboard-token",
                },
            }
            with self.assertRaises(Exception) as caught:
                dashboard_sink.send({"name": "poster", "request_id": "req-dash"}, config)
            self.assertNotIn("dashboard-token", str(caught.exception))
            self.assertIn("500", str(caught.exception))
        finally:
            server.close()

    def test_email_sends_through_a_local_smtp_server(self):
        from scripts.script_manager.sinks import email as email_sink

        server = _SmtpCapture()
        try:
            summary = {
                "name": "ci-ping",
                "request_id": "req-mail",
                "exit_code": 0,
                "failure_kind": None,
                "duration_s": 1,
                "dry_run": False,
                "run_url": "https://github.com/StaticxViper/cjm-dev/actions/runs/8",
                "trigger": {"event": "workflow_dispatch", "actor": "StaticxViper", "caller": "StaticxViper"},
            }
            config = {
                "contract": _contract(outputs=["email"]),
                "env": {
                    "SMTP_HOST": "127.0.0.1",
                    "SMTP_PORT": str(server.port),
                    "SMTP_USERNAME": "bot@example.com",
                    "SMTP_PASSWORD": "smtp-secret",
                    "SCRIPT_MANAGER_EMAIL_FROM": "bot@example.com",
                    "SCRIPT_MANAGER_EMAIL_TO": "cj@example.com",
                },
            }

            def plain_starttls(smtp, *args, **kwargs):
                return None

            with mock.patch.object(smtplib.SMTP, "starttls", plain_starttls):
                email_sink.send(summary, config)
            self.assertEqual(len(server.messages), 1)
            text = server.messages[0].decode("utf-8", errors="replace")
            self.assertIn("req-mail", text)
            self.assertIn("ci-ping", text)
            self.assertIn("actions/runs/8", text)
            self.assertNotIn("smtp-secret", text)
        finally:
            server.close()


class _HttpCapture:
    def __init__(self, status=204):
        self.requests = []
        status_code = status

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                outer.requests.append(
                    {
                        "path": self.path,
                        "body": body,
                        "headers": {key: value for key, value in self.headers.items()},
                    }
                )
                self.send_response(status_code)
                self.end_headers()

            def log_message(self, fmt, *args):
                return

        outer = self
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()


class _SmtpCapture:
    def __init__(self):
        outer = self
        self.messages = []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.wfile.write(b"220 localhost\r\n")
                while True:
                    line = self.rfile.readline()
                    if not line:
                        break
                    upper = line.strip().upper()
                    if upper.startswith(b"EHLO") or upper.startswith(b"HELO"):
                        self.wfile.write(b"250-localhost\r\n250 AUTH LOGIN\r\n")
                    elif upper.startswith(b"AUTH"):
                        if b" " not in line.strip():
                            self.wfile.write(b"334 VXNlcm5hbWU6\r\n")
                            self.rfile.readline()
                        self.wfile.write(b"334 UGFzc3dvcmQ6\r\n")
                        self.rfile.readline()
                        self.wfile.write(b"235 ok\r\n")
                    elif upper.startswith(b"DATA"):
                        self.wfile.write(b"354 end with dot\r\n")
                        chunks = []
                        while True:
                            data_line = self.rfile.readline()
                            if data_line in (b".\r\n", b".\n", b""):
                                break
                            chunks.append(data_line)
                        outer.messages.append(b"".join(chunks))
                        self.wfile.write(b"250 queued\r\n")
                    elif upper.startswith(b"QUIT"):
                        self.wfile.write(b"221 bye\r\n")
                        break
                    else:
                        self.wfile.write(b"250 ok\r\n")

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()
