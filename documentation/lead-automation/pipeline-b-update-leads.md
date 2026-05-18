# Pipeline B: Update existing leads

Use this pipeline when leads **already exist in the API** and you have newer data in a CSV (re-scored, corrected phone, etc.).

## What this pipeline does

1. **GET** existing leads from `/leads-ingest` (optionally filtered by `?group=`)
2. **Match** each API lead to a CSV row (email first, phone second)
3. **POST** one update per match — payload **excludes** `pipeline` and `position`

## Prerequisites

- [Setup](setup.md) completed (`LEADS_API_KEY`)
- A CSV with columns compatible with leadgen output (see [Reference](reference.md))
- Shell current directory: `scripts/lead_automation`

## Step 1: Prepare your CSV

Default input is `leads_output.csv`. You can use any path with `--csv`.

Useful columns for matching and updates:

- `email` (semicolon-separated values are supported; first valid email is used)
- `phone_google` and/or `phone_website`
- `business_name`, `address`, `website`, `rating`, `user_ratings_total`, `lead_score`, `niche_key`

Matching rules:

1. Normalize email and compare to API lead email
2. If no email match, compare normalized 10-digit phone

## Step 2: Choose whether to filter by group

**Update only leads in one pipeline group** (recommended when groups are separate campaigns):

```powershell
python lead_automation.py update --group landscaping-q2
```

**Update against all leads returned by GET** (no group filter):

```powershell
python lead_automation.py update
```

## Step 3: Run the update pipeline

```powershell
cd E:\REPOS\cjm-dev\scripts\lead_automation
python lead_automation.py update --group landscaping-q2 --csv leads_output.csv
```

**What happens automatically**

| Step | Action |
|------|--------|
| GET | `GET /leads-ingest` or `GET /leads-ingest?group=landscaping-q2` |
| Match | For each API lead, find CSV row by email, else phone |
| Build payload | Merge CSV fields onto existing record; strip `pipeline` / `position` |
| POST | One request per matched lead |
| Summary | `created`, `updated`, `skipped` counts |

## Step 4: Read the run summary

```text
Run complete — created: 0, updated: 35, skipped: 12
```

- **updated** — API returned `status: "updated"`
- **created** — rare; API may create if no match server-side
- **skipped** — API leads with no CSV match, failed POSTs, or unrecognized responses

## When to use Pipeline B vs A

| Situation | Pipeline |
|-----------|----------|
| New businesses not in the API | **A** — `leadgen` then `add` |
| Refresh scores or fields for known leads | **B** — `update` |
| Mix of new and existing | Run **A** first (dedupes new only), then **B** for updates if needed |

## Troubleshooting

| Issue | Check |
|-------|--------|
| 0 updated, high skipped | CSV emails/phones must match API normalization (see `leadfilter.py`) |
| Wrong leads updated | Use `--group` to narrow GET results |
| POST errors in log | `LEADS_API_KEY`, network, API validation on payload fields |

See [Reference](reference.md) for file-level detail.
