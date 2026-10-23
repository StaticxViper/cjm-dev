"""Callback, dashboard, and email sinks against local endpoints.

The HTTP sinks post over real HTTPS to a local server with a throwaway
certificate. The email sink talks real SMTP with STARTTLS to a local server.
Nothing leaves the machine.
"""
import base64
import json
import os
import shutil
import socketserver
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from scripts.script_manager.contract import Contract
from scripts.script_manager.registry import load_registry
from scripts.script_manager.sinks import STAGING_DIR, SinkError, deliver
from scripts.script_manager.sinks.http import post_json, signature

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry.json"
SECRET = "callback-secret"
TOKEN = "dashboard-token"
SMTP_PASSWORD = "smtp-password"


def _make_cert(directory: Path) -> tuple[Path, Path]:
    cert = directory / "cert.pem"
    key = directory / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


class _HttpHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.server.received.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "https://localhost/elsewhere")
        elif self.path.startswith("/fail"):
            self.send_response(500)
        else:
            self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Just enough SMTP for smtplib: EHLO, STARTTLS, AUTH PLAIN, MAIL, RCPT, DATA, QUIT."""

    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode("ascii"))
        self.wfile.flush()

    def finish(self):
        super().finish()
        if self.connection is not self.request:
            self.connection.close()

    def handle(self):
        server = self.server
        record = {"tls": False, "auth": None, "mail_from": None, "rcpt": [], "data": b""}
        server.received.append(record)
        self._send("220 localhost ESMTP test")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("ascii", "replace").rstrip("\r\n")
            verb = line.split(" ", 1)[0].upper()
            if verb in {"EHLO", "HELO"}:
                if record["tls"]:
                    self._send("250-localhost")
                    self._send("250 AUTH PLAIN")
                else:
                    self._send("250-localhost")
                    self._send("250 STARTTLS")
            elif verb == "STARTTLS":
                self._send("220 ready")
                tls = server.ssl_context.wrap_socket(self.connection, server_side=True)
                self.connection = tls
                self.rfile = tls.makefile("rb")
                self.wfile = tls.makefile("wb")
                record["tls"] = True
            elif verb == "AUTH":
                parts = line.split(" ")
                decoded = base64.b64decode(parts[2]).split(b"\0") if len(parts) > 2 else []
                record["auth"] = [item.decode("utf-8") for item in decoded]
                self._send("235 ok")
            elif verb == "MAIL":
                record["mail_from"] = line
                self._send("250 ok")
            elif verb == "RCPT":
                record["rcpt"].append(line)
                self._send("250 ok")
            elif verb == "DATA":
                self._send("354 go")
                chunks = []
                while True:
                    data = self.rfile.readline()
                    if not data or data == b".\r\n":
                        break
                    chunks.append(data)
                record["data"] = b"".join(chunks)
                self._send("250 queued")
            elif verb == "QUIT":
                self._send("221 bye")
                return
            else:
                self._send("250 ok")


@unittest.skipUnless(shutil.which("openssl"), "openssl is needed for the local TLS endpoints")
class SinkEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cert, key = _make_cert(Path(cls.tmp.name))
        cls.cert = cert
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))

        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), _HttpHandler)
        cls.http.received = []
        cls.http.socket = context.wrap_socket(cls.http.socket, server_side=True)
        cls.http_port = cls.http.server_address[1]
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        cls.smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SmtpHandler)
        cls.smtp.daemon_threads = True
        cls.smtp.received = []
        cls.smtp.ssl_context = context
        cls.smtp_port = cls.smtp.server_address[1]
        threading.Thread(target=cls.smtp.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.smtp.shutdown()
        cls.http.server_close()
        cls.smtp.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.http.received.clear()
        self.smtp.received.clear()

    def _url(self, path: str) -> str:
        return f"https://localhost:{self.http_port}{path}"

    def _env(self, **extra) -> dict:
        env = {
            "SSL_CERT_FILE": str(self.cert),
            "SCRIPT_MANAGER_CALLBACK_HOSTS": "localhost",
            "SCRIPT_MANAGER_CALLBACK_SECRET": SECRET,
            "SCRIPT_MANAGER_DASHBOARD_URL": self._url("/dashboard"),
            "CRM_MCP_MV_LLC": TOKEN,
            "SMTP_HOST": "localhost",
            "SMTP_PORT": str(self.smtp_port),
            "SMTP_USERNAME": "bot@example.com",
            "SMTP_PASSWORD": SMTP_PASSWORD,
            "SCRIPT_MANAGER_EMAIL_FROM": "bot@example.com",
            "SCRIPT_MANAGER_EMAIL_TO": "cj@example.com, ops@example.com",
        }
        env.update(extra)
        return env

    def _contract(self, outputs, callback_path="/callback"):
        return Contract(
            script="poster",
            args="",
            argv=[],
            request_id="req-e2e",
            outputs=outputs,
            confirm=True,
            dry_run=False,
            callback_url=self._url(callback_path),
            trigger="repository_dispatch",
            caller="crm-dashboard",
            run_id="4242",
            run_url="https://github.com/StaticxViper/cjm-dev/actions/runs/4242",
        )

    def _summary(self, contract):
        return {
            "name": "poster",
            "request_id": "req-e2e",
            "exit_code": 0,
            "failure_kind": None,
            "outcome": "success",
            "duration_s": 1.0,
            "dry_run": False,
            "outputs": [],
            "data": {"ok": True},
            **contract.context(),
        }

    def _deliver(self, contract, env):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            summary = self._summary(contract)
            path.write_text(json.dumps(summary), encoding="utf-8")
            with mock.patch.dict(os.environ, env, clear=False):
                deliver(Path(tmp), load_registry(FIXTURE), summary, contract, path)
            written = json.loads(path.read_text(encoding="utf-8"))
            staged = json.loads((Path(tmp) / STAGING_DIR / "run.json").read_text(encoding="utf-8"))
        return written, staged

    def test_callback_dashboard_and_email_end_to_end(self):
        contract = self._contract(["callback", "dashboard", "email"])
        written, staged = self._deliver(contract, self._env())
        results = {item["name"]: item for item in written["sinks"]}
        self.assertEqual(set(results), {"callback", "dashboard", "email", "artifact"})
        self.assertTrue(all(item["ok"] for item in results.values()), results)
        self.assertEqual(staged["sinks"], written["sinks"])

        by_path = {item["path"]: item for item in self.http.received}
        callback = by_path["/callback"]
        self.assertEqual(callback["headers"]["X-Script-Manager-Signature"], signature(SECRET, callback["body"]))
        callback_body = json.loads(callback["body"])
        self.assertEqual(callback_body["request_id"], "req-e2e")
        self.assertEqual(callback_body["run"]["url"], "https://github.com/StaticxViper/cjm-dev/actions/runs/4242")
        self.assertEqual(callback_body["trigger"]["caller"], "crm-dashboard")

        dashboard = by_path["/dashboard"]
        self.assertEqual(dashboard["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(json.loads(dashboard["body"])["outcome"], "success")

        self.assertEqual(len(self.smtp.received), 1)
        mail = self.smtp.received[0]
        self.assertTrue(mail["tls"], "the email sink must STARTTLS before AUTH")
        self.assertEqual(mail["auth"], ["", "bot@example.com", SMTP_PASSWORD])
        self.assertEqual(len(mail["rcpt"]), 2)
        text = mail["data"].decode("utf-8")
        self.assertIn("Subject: script-manager poster success req-e2e", text)
        self.assertIn("run_url: https://github.com/StaticxViper/cjm-dev/actions/runs/4242", text)
        self.assertIn("caller: crm-dashboard", text)
        self.assertNotIn(SMTP_PASSWORD, text)
        self.assertNotIn(TOKEN, text)

    def test_endpoint_errors_are_recorded_per_sink(self):
        contract = self._contract(["callback", "dashboard"], callback_path="/fail")
        env = self._env(SCRIPT_MANAGER_DASHBOARD_URL=self._url("/redirect"))
        written, _ = self._deliver(contract, env)
        results = {item["name"]: item for item in written["sinks"]}
        self.assertEqual(results["callback"]["error"], "callback HTTP 500")
        self.assertEqual(results["dashboard"]["error"], "callback HTTP 302")
        self.assertTrue(results["artifact"]["ok"])
        self.assertEqual(written["exit_code"], 0)

    def test_untrusted_certificate_is_refused(self):
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": ""}, clear=False):
            with self.assertRaises(Exception):
                post_json(self._url("/ok"), b"{}", {"Content-Type": "application/json"})
        self.assertEqual(self.http.received, [])

    def test_missing_configuration_is_a_sink_error(self):
        from scripts.script_manager.sinks import dashboard, email

        with self.assertRaises(SinkError):
            dashboard.send({}, {"env": self._env(CRM_MCP_MV_LLC="")})
        with self.assertRaises(SinkError):
            dashboard.send({}, {"env": self._env(SCRIPT_MANAGER_DASHBOARD_URL="")})
        with self.assertRaises(SinkError):
            email.send({}, {"env": self._env(SMTP_HOST="")})
        with self.assertRaises(SinkError):
            email.send({}, {"env": self._env(SMTP_PORT="not-a-port")})
        self.assertEqual(self.http.received, [])
        self.assertEqual(self.smtp.received, [])


if __name__ == "__main__":
    unittest.main()
