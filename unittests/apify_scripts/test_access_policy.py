"""
Unit tests for the shared Apify proxy and CAPTCHA ladder.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_access_policy

No live network and no Apify platform call.
"""
import asyncio
import contextvars
import importlib.util
import json
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

_REPO = Path(__file__).resolve().parents[2]
_ACCESS = _REPO / "scripts" / "apify-scripts" / "access.py"


def _load_access():
    spec = importlib.util.spec_from_file_location("cjm_access_policy_under_test", _ACCESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


access = _load_access()


def _policy(**raw):
    settings = access.read_access_settings(raw)
    return access.AccessPolicy(settings, solver=raw.get("solver"))


class _Actor:
    def __init__(self):
        self.calls = []

    async def create_proxy_configuration(self, actor_proxy_input=None):
        self.calls.append(actor_proxy_input)
        return _Config()


class _Config:
    def __init__(self):
        self.asked = 0

    async def new_url(self):
        self.asked += 1
        return "http://groups-DATACENTER:secret@proxy.apify.com:8000"


class TestSpendAndProxyInput(unittest.TestCase):
    def test_caps_clamp_and_defaults(self):
        settings = access.read_access_settings({})
        self.assertEqual(settings["max_spend_usd"], 5.0)
        self.assertEqual(settings["max_proxy_usd"], 0.5)
        self.assertFalse(settings["allow_captcha"])
        self.assertEqual(settings["proxy_groups"], [])
        clamped = access.read_access_settings({"maxSpendUsd": 1, "maxProxyCostUsd": 9})
        self.assertEqual(clamped["max_proxy_usd"], 1.0)
        groups = access.read_access_settings({
            "proxyConfiguration": {"useApifyProxy": False, "apifyProxyGroups": ["RESIDENTIAL"]},
        })
        self.assertEqual(groups["proxy_groups"], ["RESIDENTIAL"])

    def test_escalate_builds_datacenter_configuration(self):
        settings = access.read_access_settings({"proxyGroups": ["SHADER"]})
        self.assertIsNone(access.build_proxy_input(settings, escalate=False))
        payload = access.build_proxy_input(access.read_access_settings({}), escalate=True)
        self.assertTrue(payload["useApifyProxy"])
        self.assertEqual(payload["apifyProxyGroups"], ["DATACENTER"])
        chosen = access.build_proxy_input(settings, escalate=True)
        self.assertEqual(chosen["apifyProxyGroups"], ["SHADER"])

    def test_env_url_and_playwright_dict(self):
        with patch.dict(os.environ, {
            "APIFY_PROXY_PASSWORD": "secret",
            "APIFY_PROXY_HOSTNAME": "proxy.apify.com",
            "APIFY_PROXY_PORT": "8000",
        }):
            url = access.proxy_url_from_env(["RESIDENTIAL"], session="abc")
        self.assertIn("groups-RESIDENTIAL", unquote(url))
        proxy = access.playwright_proxy(url)
        self.assertEqual(proxy["server"], "http://proxy.apify.com:8000")
        self.assertEqual(proxy["password"], "secret")
        self.assertIsNone(access.playwright_proxy(""))

    def test_template_schema_records_the_policy_fields(self):
        form = json.loads(
            (_REPO / "scripts" / "apify-scripts" / "_template" / ".actor" / "input_schema.json").read_text(encoding="utf-8")
        )
        for key in ("maxSpendUsd", "maxProxyCostUsd", "allowCaptcha", "proxyConfiguration", "proxyGroups"):
            self.assertIn(key, form["properties"])
        self.assertEqual(form["properties"]["proxyConfiguration"]["editor"], "proxy")
        self.assertFalse(form["properties"]["proxyConfiguration"]["default"]["useApifyProxy"])
        self.assertFalse(form["properties"]["allowCaptcha"]["default"])
        pricing = json.loads(
            (_REPO / "scripts" / "apify-scripts" / "_template" / ".actor" / "pay_per_event.json").read_text(encoding="utf-8")
        )
        events = pricing["actorChargeEvents"]
        self.assertEqual(events["proxy"]["eventPriceUsd"], access.DEFAULT_PRICES_USD["proxy"])
        self.assertEqual(events["captcha"]["eventPriceUsd"], access.DEFAULT_PRICES_USD["captcha"])
        self.assertTrue(events["result"]["isPrimaryEvent"])
        text = (_REPO / "scripts" / "apify-scripts" / "_template" / "src" / "main.py").read_text(encoding="utf-8")
        self.assertIn("access_summary", text)
        self.assertIn("build_proxy_input", text)


class TestCreateProxyConfiguration(unittest.IsolatedAsyncioTestCase):
    async def test_off_until_escalate_then_new_url(self):
        actor = _Actor()
        settings = access.read_access_settings({})
        skipped = await access.create_proxy_configuration(settings, escalate=False, actor=actor)
        self.assertIsNone(skipped)
        self.assertEqual(actor.calls, [])
        opened = await access.create_proxy_configuration(settings, escalate=True, actor=actor)
        self.assertEqual(actor.calls[0]["useApifyProxy"], True)
        self.assertEqual(actor.calls[0]["apifyProxyGroups"], ["DATACENTER"])
        self.assertEqual(
            await access.new_proxy_url(opened),
            "http://groups-DATACENTER:secret@proxy.apify.com:8000",
        )


class TestProxyUrlOnActorLoop(unittest.TestCase):
    def test_worker_keeps_the_caller_context(self):
        marker = contextvars.ContextVar("proxy_test_marker", default="")

        async def fake_async(settings):
            del settings
            return marker.get()

        marker.set("from-main")
        context = contextvars.copy_context()
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            with patch.object(access, "_proxy_url_async", fake_async):
                found = access.blocking_proxy_url({}, loop, context)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()
        self.assertEqual(found, "from-main")


class TestEscalate(unittest.TestCase):
    def _proxy_recorder(self, response):
        calls = []

        def proxy(url, token=None):
            calls.append((url, token))
            return dict(response)

        return calls, proxy

    def test_direct_success_does_not_use_proxy(self):
        policy = _policy()
        calls, proxy = self._proxy_recorder({"status": 500, "text": "unused"})
        result, stop = access.escalate(
            policy,
            "https://example.test/city",
            {"status": 200, "text": "<html>ok</html>", "error": None},
            proxy,
        )
        self.assertIsNone(stop)
        self.assertEqual(result["status"], 200)
        self.assertEqual(calls, [])
        self.assertEqual(policy.ledger.counts["proxy"], 0)
        self.assertEqual(policy.ledger.counts["captcha"], 0)

    def test_block_escalates_to_proxy_once(self):
        policy = _policy(allowCaptcha=False)
        calls, proxy = self._proxy_recorder({
            "status": 200,
            "text": "<html>ok</html>",
            "error": None,
            "content_type": "text/html",
        })
        result, stop = access.escalate(
            policy,
            "https://example.test/city",
            {"status": 403, "text": "unusual traffic", "error": None},
            proxy,
        )
        self.assertIsNone(stop)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["via"], "proxy")
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0][1])
        self.assertEqual(policy.ledger.counts["proxy"], 1)
        self.assertEqual(policy.ledger.counts["captcha"], 0)

    def test_cap_hit_stops_without_calling_proxy(self):
        policy = _policy(maxProxyCostUsd=0, allowCaptcha=True)
        calls, proxy = self._proxy_recorder({"status": 200, "text": "nope"})
        result, stop = access.escalate(
            policy,
            "https://example.test/city",
            {"status": 403, "text": "unusual traffic", "error": None},
            proxy,
        )
        self.assertEqual(stop, "budget")
        self.assertEqual(result["stop"], "budget")
        self.assertEqual(calls, [])
        self.assertIn("spend cap", access.stop_message(stop).lower())
        self.assertEqual(policy.ledger.counts["proxy"], 0)
        self.assertEqual(policy.ledger.counts["captcha"], 0)
        self.assertEqual(policy.ledger.spend_usd, 0)

    def test_captcha_disabled_stops_without_a_solve_charge(self):
        policy = _policy(allowCaptcha=False, solver=lambda url, html: "token-1")
        calls, proxy = self._proxy_recorder({
            "status": 403,
            "text": "<div class='g-recaptcha' data-sitekey='x'>",
            "error": None,
            "content_type": "text/html",
        })
        _result, stop = access.escalate(
            policy,
            "https://example.test/city",
            {"status": 403, "text": "unusual traffic", "error": None},
            proxy,
        )
        self.assertEqual(stop, "captcha_disabled")
        self.assertEqual(len(calls), 1)
        self.assertEqual(policy.ledger.counts["proxy"], 1)
        self.assertEqual(policy.ledger.counts["captcha"], 0)

    def test_solve_is_charged_only_when_a_token_comes_back(self):
        def solver(url, html):
            return "token-1"

        policy = _policy(allowCaptcha=True, solver=solver)
        calls = []

        def proxy(url, token=None):
            calls.append(token)
            if token:
                return {"status": 200, "text": "<html>ok</html>", "error": None, "content_type": "text/html"}
            return {
                "status": 403,
                "text": "<div class='g-recaptcha'>",
                "error": None,
                "content_type": "text/html",
            }

        result, stop = access.escalate(
            policy,
            "https://example.test/city",
            {"status": 429, "text": "attention required", "error": None},
            proxy,
        )
        self.assertIsNone(stop)
        self.assertEqual(result["status"], 200)
        self.assertEqual(calls, [None, "token-1"])
        self.assertEqual(policy.ledger.counts["captcha"], 1)
        self.assertEqual(policy.ledger.counts["proxy"], 1)

        empty = _policy(allowCaptcha=True, solver=lambda url, html: None)
        _result, stop = access.escalate(
            empty,
            "https://example.test/city",
            {"status": 403, "text": "unusual traffic", "error": None},
            lambda url, token=None: {
                "status": 403,
                "text": "g-recaptcha",
                "error": None,
                "content_type": "text/html",
            },
        )
        self.assertEqual(stop, "captcha_unavailable")
        self.assertEqual(empty.ledger.counts["captcha"], 0)

    def test_robots_error_is_not_retried(self):
        policy = _policy()
        calls, proxy = self._proxy_recorder({"status": 200, "text": "nope"})
        _result, stop = access.escalate(
            policy,
            "https://example.test/city",
            {"status": 0, "text": "", "error": "robots_disallowed"},
            proxy,
        )
        self.assertIsNone(stop)
        self.assertEqual(calls, [])
        self.assertEqual(policy.ledger.counts["proxy"], 0)

    def test_summary_reports_zero_spend_until_a_commit(self):
        settings = access.read_access_settings({"allowCaptcha": False})
        ledger = access.SpendLedger(settings["max_spend_usd"], settings["max_proxy_usd"], settings["prices_usd"])
        summary = access.access_summary(settings, ledger)
        self.assertEqual(summary["spendUsd"], 0)
        self.assertEqual(summary["proxySpendUsd"], 0)
        self.assertEqual(summary["proxyGroups"], ["DATACENTER"])
        self.assertFalse(summary["allowCaptcha"])


if __name__ == "__main__":
    unittest.main()
