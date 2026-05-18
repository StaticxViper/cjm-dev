# Lead automation reference

## Scripts and modules

| File | Role |
|------|------|
| `scripts/lead_automation/leadgen.py` | Google Places scrape → `leads_output.csv` |
| `scripts/lead_automation/leadfilter.py` | Score filter, API dedupe, CSV matching |
| `scripts/lead_automation/lead_automation.py` | CLI orchestration (`add` / `update`) |
| `scripts/lead_automation/leads_api.py` | HTTP client: GET/POST, 429 retry, response parsing |
| `scripts/lead_automation/keywords.json` | `niche_key` → API `category` |
| `scripts/lead_automation/coords.json` | Cities and coordinates to search |

## CLI reference

### leadgen.py

```text
python leadgen.py --group <pipeline-group-name>
```

| Flag | Required | Description |
|------|----------|-------------|
| `--group` | Yes | Stored on each row as `pipeline_group` |

### lead_automation.py

```text
python lead_automation.py add   [--csv PATH]
python lead_automation.py update [--csv PATH] [--group NAME]
```

| Subcommand | Description |
|------------|-------------|
| `add` | Pipeline A: score filter, dedupe, batch POST new leads |
| `update` | Pipeline B: match existing leads to CSV, POST each update |

| Flag | Default | Description |
|------|---------|-------------|
| `--csv` | `leads_output.csv` | Input CSV path |
| `--group` | (none) | **update only** — passed as `?group=` on GET |

## API behavior

**Base URL:** `https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1`  
**Endpoint:** `/leads-ingest`  
**Auth:** header `x-api-key: <LEADS_API_KEY>`

| Method | Pipeline | Body |
|--------|----------|------|
| GET | A (dedupe), B (fetch) | — ; optional `?group=` on B |
| POST (array) | A | JSON array of lead objects |
| POST (object) | B | One lead object per request |

**Typical responses**

- Create: `{ "success": true, "status": "created" }`
- Update: `{ "status": "updated", "matched_on": "email" }` (or `"phone"`)

## Score threshold

Defined in `leadfilter.py`:

```python
SCORE_THRESHOLD = 60
```

Pipeline A keeps rows where **`lead_score >= SCORE_THRESHOLD`**.

Lead scoring (in `leadgen.py`): higher score means weaker digital presence (no site, no HTTPS, etc.). Adjust the constant and re-run `add` to change who gets ingested.

## Payload fields (POST)

Built by `row_to_ingest_payload` in `lead_automation.py`:

| Field | Add | Update |
|-------|-----|--------|
| `business_name`, `address`, `phone`, `email`, `website` | Yes | Yes |
| `rating`, `user_ratings_total`, `category`, `tags`, `score` | Yes | Yes |
| `pipeline_group` | Yes (from CSV) | No |
| `pipeline`, `position` | No | Explicitly omitted |
| `id` | If present on row | If present from GET match |

`category` comes from `keywords.json` via CSV `niche_key`.

## leadfilter.py functions

| Function | Used in |
|----------|---------|
| `load_existing_place_ids` / `is_new_place` | leadgen (local CSV dedupe) |
| `filter_by_score` | Pipeline A |
| `dedupe_against_existing` | Pipeline A |
| `match_leads_to_csv` | Pipeline B |
| `normalize_email` / `normalize_phone` | Dedupe and match |

## leads_api.py functions

| Function | Purpose |
|----------|---------|
| `fetch_existing_leads(group=None)` | GET and parse lead list |
| `post_leads_batch(leads)` | Pipeline A batch create |
| `post_lead(lead)` | Pipeline B single update |
| `request_with_retry` | 429 exponential backoff (max 5 attempts) |
| `count_batch_results` | Tally created/updated/skipped from batch response |

GET response parsing accepts:

- Top-level JSON array
- `{ "leads": [...] }`
- `{ "data": [...] }`

## Tests

From repo root:

```powershell
python -m unittest unittests.lead_automation.test_leadfilter unittests.lead_automation.test_leads_api -v
```

## Removed (legacy)

Do not use:

- `python lead_automation.py -individual`
- `python lead_automation.py -bulk`
- Endpoint `/leads-ingest-bulk`
- Env var `LEAD_INGEST_KEY` for new flows (use `LEADS_API_KEY`)

## Common issues

| Symptom | Likely cause |
|---------|----------------|
| Import / logger errors when testing leadgen | Run tests from repo root; leadgen needs `helper_scripts` on path |
| All leads skipped on `add` | Scores below 60 or already in API |
| `update` matches nothing | Phone/email format mismatch; verify normalized 10-digit US phones |
| 401 / 403 | Wrong or missing `LEADS_API_KEY` |
