"""
Unit tests for scripts/lead_automation/leads_api.py
"""
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEAD_DIR = _REPO_ROOT / "scripts" / "lead_automation"


def _import_leads_api():
    if str(_LEAD_DIR) not in sys.path:
        sys.path.insert(0, str(_LEAD_DIR))
    return importlib.import_module("leads_api")


API = _import_leads_api()


class TestParseLeadsResponse(unittest.TestCase):
    def test_top_level_array(self):
        self.assertEqual(API.parse_leads_response([{"id": 1}]), [{"id": 1}])

    def test_wrapped_leads(self):
        body = {"leads": [{"email": "a@b.com"}]}
        self.assertEqual(len(API.parse_leads_response(body)), 1)

    def test_wrapped_data(self):
        body = {"data": [{"email": "x@y.com"}]}
        self.assertEqual(len(API.parse_leads_response(body)), 1)

    def test_unknown_returns_empty(self):
        self.assertEqual(API.parse_leads_response({"foo": 1}), [])


class TestClassifyResponse(unittest.TestCase):
    def test_created(self):
        self.assertEqual(API.classify_response({"status": "created"}), "created")

    def test_updated(self):
        self.assertEqual(
            API.classify_response({"status": "updated", "matched_on": "email"}),
            "updated",
        )

    def test_skipped_unknown(self):
        self.assertEqual(API.classify_response({}), "skipped")


class TestCountBatchResults(unittest.TestCase):
    def test_list_of_results(self):
        resp = [{"status": "created"}, {"status": "updated"}, {}]
        counts = API.count_batch_results(resp, submitted=3)
        self.assertEqual(counts["created"], 1)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(counts["skipped"], 1)


class TestRequestWithRetry(unittest.TestCase):
    @patch.object(API, "LEADS_API_KEY", "test-key")
    @patch("leads_api.time.sleep", return_value=None)
    @patch("leads_api.httpx.Client")
    def test_retries_on_429_then_succeeds(self, mock_client_cls, _sleep):
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b'{"status":"created"}'
        ok.json.return_value = {"status": "created"}

        rate_limited = MagicMock()
        rate_limited.status_code = 429

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.request.side_effect = [rate_limited, ok]
        mock_client_cls.return_value = mock_client

        result = API.request_with_retry("POST", json_body={"email": "a@b.com"})
        self.assertEqual(result["status"], "created")
        self.assertEqual(mock_client.request.call_count, 2)

    @patch.object(API, "LEADS_API_KEY", "test-key")
    @patch("leads_api.httpx.Client")
    def test_fetch_parses_wrapped_leads(self, mock_client_cls):
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b'{"leads":[{"email":"a@b.com"}]}'
        ok.json.return_value = {"leads": [{"email": "a@b.com"}]}

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.request.return_value = ok
        mock_client_cls.return_value = mock_client

        leads = API.fetch_existing_leads()
        self.assertEqual(len(leads), 1)


if __name__ == "__main__":
    unittest.main()
