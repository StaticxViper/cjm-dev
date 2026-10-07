"""
Unit tests for scripts/lead_automation/crm_enrich.py

Run from repo root:
    python -m unittest unittests.lead_automation.test_crm_enrich_cli
"""
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LEADGEN_DIR = _REPO_ROOT / "scripts" / "lead_automation"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crm_enrich"

if str(_LEADGEN_DIR) not in sys.path:
    sys.path.insert(0, str(_LEADGEN_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.chdir(_LEADGEN_DIR)

from crm_enrich import (  # noqa: E402
    RunConfig,
    address_is_empty,
    build_update_payload,
    main,
    merge_notes,
    merge_tags,
    parse_args,
    parse_filters,
    render_note,
    run_batch,
)
from crm_enrich_match import load_npa_state, load_zip_county  # noqa: E402
from crm_mcp_client import (  # noqa: E402
    AUTH_MESSAGE,
    NEVER_WRITE_FIELDS,
    UPDATE_LEAD_WRITABLE,
    URL_MESSAGE,
    CrmAuthError,
    CrmClient,
    CrmConfigError,
)
from playwright_discovery import BusinessDiscoverySession, is_google_block_page  # noqa: E402

ROBOTS = (_FIXTURES / "google_robots.txt").read_text(encoding="utf-8")
BATCH = "35404690-180f-42af-b034-dcf567a1628f"
VENTURE = "7370dd04-0865-42a3-966e-09f70a5e8d5a"


def _load(name):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _leads():
    return _load("list_leads_page1.json")["leads"] + _load("list_leads_page2.json")["leads"]


STAKER = {
    "business_name": "C. Staker Remodeling",
    "phone": "(631) 821-4921",
    "website": "http://cstakerremodeling.com/",
    "address": "100 Main St, Huntington, NY 11743",
    "category": "Remodeler",
    "place_id": "ChIJ___LaZ1n6IkRBv6QRmL-qc4",
}
GOLDEN = {
    "business_name": "Base Camp at Golden Gate Canyon",
    "phone": "(303) 582-9979",
    "website": "http://www.basecampco.com/",
    "address": "92 Crawford Gulch Rd, Golden, CO 80403",
    "category": "Campground",
    "place_id": "ChIJgolden",
}
NORTHWIND = {
    "business_name": "Northwind Customs",
    "phone": "(716) 555-0100",
    "website": "https://northwindcustoms.example/",
    "address": "1 Main St, Olean, NY 14760",
    "place_id": "ChIJnorthwind",
    "profile_url": "https://www.google.com/maps/place/?q=place_id:ChIJnorthwind",
    "category": "",
}


class ListingSession:
    google_blocked = False

    def __init__(self):
        self.queries = []

    def search_listings(self, keyword, city, state, max_pages=1, max_results=5, query=None):
        self.queries.append(query)
        text = query or ""
        if "STRIKER" in text:
            return [dict(STAKER)]
        if "Basecamp" in text or "B&B" in text:
            return [dict(GOLDEN)]
        if "NORTHWIND" in text:
            return [dict(NORTHWIND)]
        return []

    def enrich_listing(self, listing):
        return dict(listing)

    def close(self):
        return None


def _server(updates):
    from mcp.server import MCPServer

    mcp = MCPServer("crm-enrich-e2e")
    leads = _leads()

    @mcp.tool()
    def list_ventures() -> dict:
        """List ventures."""
        return _load("list_ventures.json")

    @mcp.tool()
    def list_batches(venture: str) -> dict:
        """List batches."""
        return _load("list_batches.json")

    @mcp.tool()
    def get_batch(batch: str) -> dict:
        """Get a batch."""
        return _load("get_batch.json")

    @mcp.tool()
    def list_leads(
        batch: str = "",
        limit: int = 50,
        offset: int = 0,
        status_name: str = "",
        has_email: bool = False,
    ) -> dict:
        """Page leads."""
        page = leads[offset:offset + limit]
        return {"count": len(page), "offset": offset, "leads": page}

    @mcp.tool()
    def get_lead(lead_id: str) -> dict:
        """Get one lead."""
        for lead in leads:
            if lead["id"] == lead_id:
                return dict(lead)
        raise RuntimeError("missing lead")

    @mcp.tool()
    def update_lead(lead_id: str, fields: dict) -> dict:
        """Record a write."""
        updates.append({"lead_id": lead_id, "fields": dict(fields)})
        return {"ok": True}

    return mcp


def _no_robots(url, timeout=10):
    class Response:
        status_code = 200
        text = "User-agent: *\nAllow: /\n"
    return Response()


def _no_visit(session, url):
    return {"html": "", "emails": [], "final_url": url, "url": url}


class TestFlags(unittest.TestCase):
    def test_filters_grammar(self):
        parsed = parse_filters("status=New Lead;has_email=false;tags=ny,denver;missing=phone,website")
        self.assertEqual(parsed["status"], "New Lead")
        self.assertFalse(parsed["has_email"])
        self.assertEqual(parsed["tags"], ["ny", "denver"])
        self.assertEqual(parsed["missing"], ["phone", "website"])
        with self.assertRaises(CrmConfigError):
            parse_filters("nope")
        args = parse_args([
            "--venture", "web-dev-mv-software-iq3x",
            "--batch", BATCH,
            "--batch", "second",
            "--fields", "email,phone",
            "--dry-run",
            "--min-confidence", "80",
        ])
        self.assertEqual(args.batch, [BATCH, "second"])
        self.assertTrue(args.dry_run)

    def test_noninteractive_never_calls_input(self):
        def boom(*_args, **_kwargs):
            raise AssertionError("input() should not be called")

        class Empty:
            discovery_fallback = False
            writable_fields = set(UPDATE_LEAD_WRITABLE)

            def iter_leads(self, **kwargs):
                return iter(())

            def get_batch(self, batch):
                return _load("get_batch.json")

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            code = main(
                [
                    "--venture", VENTURE,
                    "--batch", BATCH,
                    "--fields", "phone",
                    "--dry-run",
                    "--output-dir", tmp,
                ],
                client_factory=lambda: Empty(),
                session_factory=lambda headless: ListingSession(),
                robots_text=ROBOTS,
                robots_get=_no_robots,
                visit_fn=_no_visit,
                input_fn=boom,
                sleeper=lambda _seconds: None,
            )
        self.assertEqual(code, 0)

    def test_url_required_exits_2(self):
        saved = os.environ.pop("CRM_MCP_URL", None)
        buffer = io.StringIO()
        old = sys.stderr
        sys.stderr = buffer
        try:
            code = main(["--list"], sleeper=lambda _s: None)
        finally:
            sys.stderr = old
            if saved is not None:
                os.environ["CRM_MCP_URL"] = saved
        self.assertEqual(code, 2)
        self.assertIn(URL_MESSAGE, buffer.getvalue())

    def test_auth_failure_exits_3_without_token(self):
        token = "super-secret-token"

        def factory():
            raise CrmAuthError()

        buffer = io.StringIO()
        old = sys.stderr
        sys.stderr = buffer
        try:
            code = main(
                ["--venture", "v", "--batch", "b", "--dry-run", "--mcp-url", "https://crm.example/mcp"],
                client_factory=factory,
            )
        finally:
            sys.stderr = old
        self.assertEqual(code, 3)
        text = buffer.getvalue()
        self.assertIn(AUTH_MESSAGE, text)
        self.assertNotIn(token, text)


class TestFieldMerge(unittest.TestCase):
    def test_state_only_address_is_empty_and_overwrite_keeps_old_in_note(self):
        self.assertTrue(address_is_empty("NY"))
        self.assertTrue(address_is_empty("  "))
        self.assertFalse(address_is_empty("2079 W 44th Ave, Denver, CO, 80211"))
        day = datetime(2026, 10, 6, tzinfo=timezone.utc).date()
        fields = {
            "phone": {
                "old": "(631) 821-4921",
                "new": "(716) 555-0100",
                "confidence": 86,
                "source": "maps_playwright",
                "writable": True,
            },
            "email": {
                "old": None,
                "new": "owner@northwindcustoms.example",
                "confidence": 86,
                "source": "website",
                "writable": True,
            },
        }
        note = render_note(day, "write", {"name": "Northwind Customs", "score": 86, "place_id": "ChIJ1"}, fields)
        self.assertIn("was=(631) 821-4921", note)
        self.assertIn("place_id=ChIJ1", note)
        lead = {
            "notes": "existing note",
            "tags": ["ny", "no-email", "new-business"],
            "phone": "(631) 821-4921",
        }
        preview = {
            "decision": "write",
            "note_preview": note,
            "tags_add": ["enriched"],
            "fields": fields,
        }
        config = RunConfig(overwrite=True, drop_no_email_tag=True)
        payload = build_update_payload(lead, preview, config, set(UPDATE_LEAD_WRITABLE))
        self.assertEqual(payload["phone"], "(716) 555-0100")
        self.assertIn("existing note", payload["notes"])
        self.assertIn(note, payload["notes"])
        self.assertIn("ny", payload["tags"])
        self.assertIn("new-business", payload["tags"])
        self.assertIn("enriched", payload["tags"])
        self.assertNotIn("no-email", payload["tags"])
        self.assertTrue(set(payload).issubset(UPDATE_LEAD_WRITABLE))
        self.assertTrue(NEVER_WRITE_FIELDS.isdisjoint(payload))

    def test_without_overwrite_keeps_filled_phone(self):
        lead = {"notes": "", "tags": ["ny"], "phone": "(631) 821-4921"}
        preview = {
            "decision": "write",
            "note_preview": "[enrich 2026-10-06 crm_enrich] phone=(716) 555-0100 conf=86 src=maps_playwright",
            "tags_add": ["enriched"],
            "fields": {
                "phone": {
                    "old": "(631) 821-4921",
                    "new": "(716) 555-0100",
                    "confidence": 86,
                    "source": "maps_playwright",
                    "writable": True,
                }
            },
        }
        payload = build_update_payload(lead, preview, RunConfig(overwrite=False), set(UPDATE_LEAD_WRITABLE))
        self.assertNotIn("phone", payload)
        self.assertEqual(merge_tags(["ny"], ["enriched"]), ["ny", "enriched"])
        self.assertTrue(merge_notes("existing note", "line").startswith("existing note"))


class TestCheckpoint(unittest.TestCase):
    def test_resume_and_hash_mismatch(self):
        leads = [
            {"id": "one", "business_name": "No State LLC", "address": "", "tags": [], "notes": ""},
            {"id": "two", "business_name": "Also None LLC", "address": "", "tags": [], "notes": ""},
        ]

        class Client:
            writable_fields = set(UPDATE_LEAD_WRITABLE)

            def iter_leads(self, **kwargs):
                return iter(leads)

        class Deps:
            maps = None
            places = None
            enabled = []
            source_status = {"maps_playwright": "ok"}
            writable = set(UPDATE_LEAD_WRITABLE)
            zip_county = {}
            npa_state = {}
            visit_fn = None
            robots_get = None
            counter = {"searches": 0}
            session = None

        moment = datetime(2026, 10, 6, 23, 45, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            config = RunConfig(
                venture=VENTURE,
                batches=[BATCH],
                fields=["phone"],
                dry_run=True,
                output_dir=Path(tmp),
                clock=lambda: moment,
                resume=False,
            )
            code, previews, _summary, _run_dir = run_batch(
                config, Client(), BATCH, VENTURE, Deps(), lambda _s: None, write_now=False,
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(previews), 2)
            path = Path(tmp) / BATCH / "checkpoint.dry-run.json"
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(saved["processed"]), {"one", "two"})
            self.assertNotEqual(path.name, "checkpoint.json")

            config.resume = True
            code, again, _summary, _run_dir = run_batch(
                config, Client(), BATCH, VENTURE, Deps(), lambda _s: None, write_now=False,
            )
            self.assertEqual(again, [])
            config.min_confidence = 90
            with self.assertRaises(CrmConfigError):
                run_batch(config, Client(), BATCH, VENTURE, Deps(), lambda _s: None, write_now=False)
            config.force_resume = True
            run_batch(config, Client(), BATCH, VENTURE, Deps(), lambda _s: None, write_now=False)


class TestEndToEnd(unittest.TestCase):
    def _run(self, dry_run, audit=False):
        updates = []
        mcp = _server(updates)
        client = CrmClient(server=mcp)
        client.connect(sleeper=lambda _s: None)
        self.addCleanup(client.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        args = [
            "--venture", "web-dev-mv-software-iq3x",
            "--batch", BATCH,
            "--fields", "email,phone,website,address,google_maps_uri,rating",
            "--filters", "status=New Lead;has_email=false",
            "--min-confidence", "80",
            "--output-dir", tmp.name,
            "--non-interactive",
        ]
        if dry_run:
            args.append("--dry-run")
        if audit:
            args.append("--audit-existing")

        def boom(*_a, **_k):
            raise AssertionError("input() should not be called")

        code = main(
            args,
            client_factory=lambda: client,
            session_factory=lambda headless: ListingSession(),
            robots_text=ROBOTS,
            robots_get=_no_robots,
            visit_fn=_no_visit,
            input_fn=boom,
            sleeper=lambda _s: None,
        )
        previews = list(Path(tmp.name).glob(f"{BATCH}/*/preview.json"))
        self.assertEqual(len(previews), 1)
        rows = json.loads(previews[0].read_text(encoding="utf-8"))
        return code, rows, updates

    def test_dry_run_matches_preview_and_does_not_write(self):
        code, rows, updates = self._run(dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(updates, [])
        by_id = {row["lead_id"]: row for row in rows}
        striker = by_id["e89bdb1c-22af-4d6f-a529-12e8207abdcb"]
        self.assertEqual(striker["decision"], "no_match")
        self.assertEqual(striker["candidates"][0]["breakdown"], {
            "name": 17, "location": 10, "category": 5, "corroboration": 0,
        })
        self.assertEqual(striker["candidates"][0]["score"], 32)
        self.assertIn("distinctive_token_missing", striker["candidates"][0]["hard_rejects"])
        self.assertIn("no confident match; best=C. Staker Remodeling conf=32", striker["note_preview"])
        self.assertEqual(striker["tags_add"], ["enrich_no_match"])
        self.assertEqual(striker["query"], "STRIKER CONSTRUCTION SERVICES Cattaraugus County NY")
        base = by_id["459faa3b-1111-4222-8333-459faa3b0001"]
        self.assertEqual(base["decision"], "no_match")
        self.assertIn("address_mismatch", base["candidates"][0]["hard_rejects"])
        good = by_id["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"]
        self.assertEqual(good["decision"], "write")
        self.assertEqual(good["fields"]["phone"]["new"], "(716) 555-0100")
        self.assertTrue(good["fields"]["phone"]["writable"])
        self.assertIn("google_maps_uri", good["fields"])
        self.assertFalse(good["fields"]["google_maps_uri"]["writable"])
        self.assertIn("(note-only)", good["note_preview"])

    def test_live_update_uses_allowed_keys_only(self):
        code, _rows, updates = self._run(dry_run=False)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(updates), 1)
        allowed = set(UPDATE_LEAD_WRITABLE)
        for call in updates:
            self.assertTrue(set(call["fields"]).issubset(allowed))
            self.assertTrue(NEVER_WRITE_FIELDS.isdisjoint(call["fields"]))
        by_id = {call["lead_id"]: call["fields"] for call in updates}
        striker = by_id["e89bdb1c-22af-4d6f-a529-12e8207abdcb"]
        self.assertNotIn("phone", striker)
        self.assertNotIn("website", striker)
        self.assertIn("enrich_no_match", striker["tags"])
        self.assertIn("ny", striker["tags"])
        good = by_id["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"]
        self.assertEqual(good["phone"], "(716) 555-0100")
        self.assertIn("enriched", good["tags"])
        self.assertNotIn("score", good)
        self.assertNotIn("google_maps_uri", good)

    def test_audit_flags_both_false_matches(self):
        code, rows, updates = self._run(dry_run=True, audit=True)
        self.assertEqual(code, 0)
        self.assertEqual(updates, [])
        by_id = {row["lead_id"]: row for row in rows}
        for lead_id in (
            "e89bdb1c-22af-4d6f-a529-12e8207abdcb",
            "459faa3b-1111-4222-8333-459faa3b0001",
        ):
            self.assertEqual(by_id[lead_id]["tags_add"], ["enrich_suspect"])
            self.assertEqual(by_id[lead_id]["fields"], {})


class TestFixturesAndLaunch(unittest.TestCase):
    def test_block_page_and_launch_args(self):
        block = (_FIXTURES / "maps_block.html").read_text(encoding="utf-8")
        consent = (_FIXTURES / "maps_consent.html").read_text(encoding="utf-8")
        search = (_FIXTURES / "maps_search.html").read_text(encoding="utf-8")
        self.assertTrue(is_google_block_page(block, "https://www.google.com/sorry/index"))
        self.assertFalse(is_google_block_page(consent, "https://www.google.com/maps"))
        self.assertEqual(search.count("/maps/place/"), 3)
        default = BusinessDiscoverySession()
        self.assertIn("--disable-blink-features=AutomationControlled", default._launch_args)
        bare = BusinessDiscoverySession(launch_args=[])
        self.assertEqual(bare._launch_args, [])
        default.close()
        bare.close()

    def test_sources_do_not_request_google_web_search(self):
        text = (_LEADGEN_DIR / "crm_enrich_sources.py").read_text(encoding="utf-8")
        self.assertNotIn("google.com/search", text)
        self.assertNotIn("EmailDiscoverySession", text)


if __name__ == "__main__":
    unittest.main()
