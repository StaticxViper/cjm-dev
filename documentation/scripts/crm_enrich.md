# CRM batch enrichment

**Source:** `scripts/lead_automation/crm_enrich.py`

Fills empty CRM lead fields from a Google Maps business search in Chromium, then checks the matched site for a real email. Confident values are written back through the CRM pipeline MCP server. A dry run writes a preview and does not call `update_lead`.

The first intended batch is "New Businesses, Pulled Oct 6, 2026" (`35404690-180f-42af-b034-dcf567a1628f`) on venture "Web Dev - MV Software" (`7370dd04-0865-42a3-966e-09f70a5e8d5a`, slug `web-dev-mv-software-iq3x`). Those rows are state registrations: usually a legal name plus a state, sometimes a county or city. Pass `--venture` and `--batch` yourself; the script has no built-in batch.

## Setup

From the repo root:

```bash
pip install -r requirements/requirements.txt
playwright install chromium
```

`mcp` 2.3.x (Python 3.10+) is the client. It installs its own `httpx2`, `starlette`, `uvicorn`, and `pydantic` packages beside the `httpx` already used by other scripts.

In the repo-root `.env`:

```env
CRM_MCP_URL=
CRM_MCP_TOKEN=
```

`CRM_MCP_TOKEN` is optional in code. When it is unset the client sends `CRM_MCP_MV_LLC` as `Authorization: Bearer`. There is no default URL. If neither `--mcp-url` nor `CRM_MCP_URL` is set, the process exits 2 with `Set CRM_MCP_URL or pass --mcp-url`. The token is never printed. Query strings on the MCP URL are redacted in logs.

`GOOGLE_API_KEY` is required only for `--sources places_api`. `MVLLC_LOGS_KEY` is the usual logger upload key.

## Interactive

```bash
cd scripts/lead_automation
python crm_enrich.py
```

The menu lists ventures (`# | name | batches | leads`), then batches (`# | name | imported | total | email % | phone %`). Choosing a batch loads `get_batch` and prints email, phone, and website coverage plus status counts. Several batches can be entered as `1,3-4`; each batch gets its own checkpoint.

Optional filters: status, tags (ANY), `has_email`, score range, text search. Missing phone or website is applied after the page is fetched, because `list_leads` has no phone/website filter.

Each field is shown as `field | missing in N of M | writable via update_lead?`. Dry-run defaults to yes. After the preview, a live run asks `Write N field updates to M leads? [y/N]` and writes only on `y`.

## Non-interactive

```bash
python crm_enrich.py --venture web-dev-mv-software-iq3x \
  --batch 35404690-180f-42af-b034-dcf567a1628f \
  --fields email,phone,website,address --limit 50 \
  --filters "status=New Lead;has_email=false;tags=ny" \
  --min-confidence 80 --dry-run
```

`--venture` plus `--batch`, `--non-interactive`, or a non-TTY stdin skips every prompt. That is the form to use in CI.

| Flag | Meaning |
|------|---------|
| `--mcp-url` | Overrides `CRM_MCP_URL` |
| `--mcp-transport {streamable-http,sse}` | Default `streamable-http`. `sse` is a fallback only |
| `--venture` | Id, slug, or name |
| `--batch` | Repeatable. Id, slug, or name |
| `--fields` | `email,phone,website,address,google_maps_uri,rating,business_status,contact_name` |
| `--filters` | `status`, `tags` (comma, ANY), `has_email`, `min_score`, `max_score`, `search`, `missing` |
| `--limit` | Max leads to attempt this run |
| `--dry-run` | Preview only. No `update_lead` |
| `--resume` / `--force-resume` | Continue a checkpoint. A different config hash stops unless `--force-resume` |
| `--min-confidence` | Default 80 (0–100) |
| `--low-confidence-floor` | Default 60 |
| `--overwrite` | Replace non-empty fields. The old value is kept in the note |
| `--headful` | Show Chromium. Default is headless, and this tool launches Chromium with no extra automation flag |
| `--sources` | Default `maps_playwright,website`. Add `places_api` to use the official Places API |
| `--max-searches` | Maps (or Places) searches per run. Default 200 |
| `--write-delay` | Seconds between `update_lead` calls. Default 0.5 |
| `--output-dir` | Default `scripts/lead_automation/output/crm_enrich/` |
| `--audit-existing` | Re-score leads that already have a phone or website. Tags `enrich_suspect`. Does not clear or fill fields |
| `--drop-no-email-tag` | Remove `no-email` when an email is written |
| `--tag-enriched`, `--tag-low-confidence`, `--tag-no-match`, `--tag-suspect` | Tag names. Defaults use underscores |
| `--list` | Print ventures and batches with coverage |

`--list` is read-only.

## Fields

| Field | Where it goes |
|-------|----------------|
| `email`, `phone`, `website`, `address` | `update_lead` when empty (or with `--overwrite`) |
| `contact_name` | `contact_first_name` / `contact_last_name`, only from JSON-LD `Person` / founder data on the matched site |
| `google_maps_uri`, `rating` (and review count), `business_status` | Note only, until `update_lead` lists them as allowed keys |

`address` counts as empty when it is blank or only a two-letter state code such as `NY`. City and county have no CRM columns, so a fuller address is the writable city signal and the rest stays in the note.

Score, status (`column_id`), and outreach fields are never changed. The tool calls only `list_ventures`, `list_batches`, `get_batch`, `list_leads`, `get_lead`, and `update_lead`.

## Confidence

Each Maps candidate is scored 0–100. There is no "use the first result" fallback.

| Component | Points |
|-----------|--------|
| Name | 0–50. `round(50 × similarity)` after suffix stripping. At least one distinctive token must match exactly (compound words and simple plurals count; `striker` does not match `staker`) |
| Location | State +10 (required). County or city +25, using the bundled Census ZCTA→county table |
| Category | +10 compatible, +5 partial (construction ~ remodeling), 0 unknown, −15 contradiction (construction vs campground) |
| Corroboration | 0–5 when a distinctive token is in the website domain, or an existing phone/website equals the candidate, and the distinctive-token check already passed |

Hard rejects (never written): `state_mismatch`, `county_mismatch`, `address_mismatch`, `distinctive_token_missing`, `area_code_state_mismatch`, `permanently_closed`, `website_is_directory`.

| Score | Result |
|-------|--------|
| ≥ `--min-confidence` (80) and no hard reject | `write` |
| Floor (60) ≤ score < minimum, no hard reject | `low_confidence` (tag only) |
| Below the floor, or any hard reject | `no_match` (tag only) |

An exact distinctive name plus state and county is 85 and is written. The same name with no county or city is at most 75 and stays low confidence.

Worked false matches from the Oct 6 batch:

- STRIKER CONSTRUCTION SERVICES LLC (Cattaraugus County, NY) vs "C. Staker Remodeling" scores 17 + 10 + 5 + 0 = 32, with `distinctive_token_missing` and `county_mismatch`. Area code 631 is still New York, so `area_code_state_mismatch` does not fire.
- B&B Basecamp LLC (2079 W 44th Ave, Denver 80211) vs "Base Camp at Golden Gate Canyon" is `address_mismatch` (and a different county).

`--audit-existing` flags both as `enrich_suspect` and does not clear the stored phone or website.

Email is taken only from pages of the matched site after `validate_email`. HIGH confidence keeps the match score. MEDIUM is accepted only when the email domain matches the site, at match score − 10. Addresses are never guessed.

## Preview, checkpoint, summary

```text
<output-dir>/<batch_id>/<run_id>/preview.json
<output-dir>/<batch_id>/<run_id>/preview.csv
<output-dir>/<batch_id>/<run_id>/summary.json
<output-dir>/<batch_id>/checkpoint.json
<output-dir>/<batch_id>/checkpoint.dry-run.json
```

`preview.json` is one object per lead: location, query, candidates (score, breakdown, hard rejects), decision, fields (`old`, `new`, `confidence`, `source`, `writable`), tags, and the note line. Decisions: `write`, `low_confidence`, `no_match`, `skipped_already_filled`, `skipped_no_state`, `blocked`, `error`.

The checkpoint is rewritten atomically after every lead. `--resume` skips ids already in `processed`, except `error` and `blocked`. Dry-run and live runs do not share a checkpoint file. `config_hash` covers fields, filters, min confidence, sources, and overwrite.

The printed summary, also stored as `summary.json`, includes leads attempted, fills per field, written leads, no-match, low-confidence, already filled, blocked sources, robots-disallowed sources, errors, searches used, duration, and the dry-run flag.

A live note looks like:

```text
[enrich 2026-10-06 crm_enrich] phone=(716) 555-0100 conf=86 src=maps_playwright place_id=ChIJ... | website=https://example.com conf=86 src=maps_playwright | maps_uri=... rating=4.6 (12) (note-only)
```

`update_lead` replaces `tags`, so the client sends the existing tags plus `enriched`, `enrich_low_confidence`, `enrich_no_match`, or `enrich_suspect`.

## Robots and Terms of Service

Google's `robots.txt` for `User-agent: *` contains `Disallow: /maps/` and also `Allow: /maps/search/` and `Allow: /maps/place/`. Under RFC 9309 the longest match wins, so Maps search and place URLs are allowed and `/search` is not. Python's `urllib.robotparser` walks rules in file order and reports `/maps/search/` as disallowed; this tool does not use that parser.

`robots.txt` is not permission. The [Google Terms of Service](https://policies.google.com/terms), the [Google Maps terms](https://www.google.com/intl/en_us/help/terms_maps/), and the [Google Maps Platform Terms](https://cloud.google.com/maps-platform/terms) restrict automated access to and extraction of Maps content outside the official API. Automated Maps browsing is a Terms of Service risk accepted for low-volume personal lead research. The script does not solve CAPTCHAs, rotate proxies or user agents, or add stealth plugins. Chromium is launched without `--disable-blink-features=AutomationControlled` (leadgen's default is unchanged).

On the first Google block page the Maps source stops, the checkpoint is saved, and the run can be continued later with `--resume`. If every discovery source is blocked or disallowed the exit code is 4.

This tool does not open Google web search result pages. Website fetches obey that site's `robots.txt` (same longest-match evaluator) and the existing contact-page path list.

The optional `places_api` source uses the official legacy Find Place and Place Details endpoints (`GOOGLE_API_KEY`, same family as `leadgen.get_place_details`). It is never required. Before a run the CLI prints a worst-case estimate using published list prices of about $17 per 1,000 Find Place calls and $17 per 1,000 Place Details calls (up to two details per lead). Confirm the SKUs enabled on the key; prices change.

Maps searches wait 2.0–4.5 seconds apart and detail pages 1.2–2.8 seconds, one browser at a time, capped by `--max-searches` (default 200). A 789-lead batch takes several runs. That is what the checkpoint is for.

ZIP → county rows for NY, PA, CO, and NJ come from the Census Bureau 2020 ZCTA–county relationship file (`tab20_zcta520_county20_natl.txt`, public domain), keeping the county with the largest land-area overlap. Area codes in `data/npa_state.json` are NANPA assignments for those states plus other states used to detect out-of-state numbers.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Finished |
| 1 | Unexpected error |
| 2 | Usage or config (`CRM_MCP_URL` missing, bad flags, checkpoint hash mismatch) |
| 3 | MCP connection, auth, or missing tools. Auth prints `CRM MCP auth failed; check CRM_MCP_TOKEN` and does not include the token |
| 4 | Every enabled discovery source was blocked or disallowed. Checkpoint saved |
| 130 | Interrupted. Checkpoint saved |

Connection failures retry three times (1s, 2s, 4s). A disconnect mid-run reconnects once, then saves the checkpoint and exits 3.

## Script Manager

When the Script Manager registry lands, register:

```json
{
  "name": "crm-enrich",
  "description": "Interactive CRM batch enrichment over MCP (Playwright Maps + site validation)",
  "status": "active",
  "entry": {"type": "path", "path": "scripts/lead_automation/crm_enrich.py"},
  "cwd": "scripts/lead_automation",
  "interactive": true,
  "help_supported": true,
  "env": {
    "required": ["CRM_MCP_URL"],
    "optional": ["CRM_MCP_TOKEN", "CRM_MCP_MV_LLC", "GOOGLE_API_KEY", "MVLLC_LOGS_KEY"],
    "conditional": [{"when_args_any": ["--sources=places_api"], "require": ["GOOGLE_API_KEY"]}]
  },
  "needs_playwright": true,
  "timeout_seconds": 14400,
  "outputs": ["scripts/lead_automation/output/crm_enrich/**", "logs/**"],
  "side_effects": ["external_api", "external_post"],
  "ci_allowed": true,
  "tags": ["leads", "crm"],
  "docs": "documentation/scripts/crm_enrich.md"
}
```

In CI, pass `--venture` and `--batch`. Interactive with no flags is not a CI run. Playwright Maps from a GitHub-hosted datacenter IP is likely to hit a block page; prefer `--dry-run` or `--sources places_api` there, and run live Playwright locally. Add `CRM_MCP_URL` and `CRM_MCP_TOKEN` as workflow secrets when scripts are launched through Script Manager.

## Tests

```bash
python -m unittest unittests.lead_automation.test_crm_enrich_match
python -m unittest unittests.lead_automation.test_crm_enrich_robots
python -m unittest unittests.lead_automation.test_crm_mcp_client
python -m unittest unittests.lead_automation.test_crm_enrich_cli
```

Fixtures live in `unittests/lead_automation/fixtures/crm_enrich/`. The dry-run test uses an in-process MCP server and a fake Maps session. It does not call the network.
