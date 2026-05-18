# Pipeline A: Add new leads

Use this pipeline to discover businesses, write them to a CSV, and **create** only leads that are not already in the API.

## What this pipeline does

1. **leadgen** — Google Places search, website analysis, scoring, local CSV dedupe by `place_id`
2. **lead_automation add** — score filter → fetch all API leads → dedupe by email/phone → **one batch POST**

## Prerequisites

- [Setup](setup.md) completed (`GOOGLE_API_KEY`, `LEADS_API_KEY`, `coords.json`, `keywords.json`)
- Shell current directory: `scripts/lead_automation`

## Step 1: Choose a pipeline group name

Pick a stable label for this batch (stored on every row as `pipeline_group` and sent to the API on create).

Examples: `landscaping-q2`, `plumbing-nj-2026`

## Step 2: Generate leads

```powershell
cd E:\REPOS\cjm-dev\scripts\lead_automation
python leadgen.py --group landscaping-q2
```

**What to expect**

- Logs per city/keyword from `coords.json`
- Output appended to `leads_output.csv`
- New column `pipeline_group` set to your `--group` value
- Rows include `lead_score` (higher = weaker digital presence)

**Optional:** `contacted.txt` in the same folder skips leads whose emails were already contacted.

## Step 3: Review the CSV (recommended)

Open `leads_output.csv` and spot-check:

- `email`, `phone_google`, `business_name`
- `lead_score` — only rows at or above the threshold are ingested (default **60**)
- `pipeline_group` matches your run
- `niche_key` matches a key in `keywords.json`

## Step 4: Ingest new leads to the API

```powershell
python lead_automation.py add
```

Or specify another file:

```powershell
python lead_automation.py add --csv leads_output.csv
```

**What happens automatically**

| Step | Action |
|------|--------|
| Score filter | Keeps rows with `lead_score >= 60` (see [Reference](reference.md) to change threshold) |
| GET | Downloads all existing leads from `/leads-ingest` |
| Dedupe | Drops CSV rows whose normalized **email** or **phone** already exists in the API |
| POST | Sends remaining leads as a **JSON array** in one request |
| Summary | Logs `Run complete — created: X, updated: Y, skipped: Z` |

**Skipped** includes: low score, already in API, and any leads the API did not accept.

## Step 5: Read the run summary

Example log line:

```text
Run complete — created: 42, updated: 0, skipped: 118
```

- **created** — new leads accepted by the API
- **updated** — unusual on `add`; may appear if the API updates on conflict
- **skipped** — filtered out before or during ingest

## Re-running safely

- **leadgen** skips duplicate `place_id`s already in `leads_output.csv`
- **add** skips leads already in the API by email/phone

You can run `leadgen` again with the same or different `--group`, then `add` again without creating duplicates.

## Troubleshooting

| Issue | Check |
|-------|--------|
| `LEADS_API_KEY` error | `.env` in repo root; restart shell |
| 429 / rate limit | Client retries with backoff; wait and re-run `add` |
| 0 created, high skipped | Lower `SCORE_THRESHOLD` or inspect CSV scores |
| Missing category on ingest | `niche_key` in CSV must exist in `keywords.json` |

See [Reference](reference.md) for file-level detail.
