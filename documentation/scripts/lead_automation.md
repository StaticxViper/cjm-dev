# Lead Automation (ingest)

**Source:** `scripts/lead_automation/lead_automation.py`

## Purpose

Reads leads from `leads_output.csv` (produced by [leadgen](leadgen.md)) and sends them to Supabase edge functions for storage. Supports individual POSTs or a single bulk ingest. Filters junk emails containing `sentry` or `wixpress`.

## Prerequisites

- Python 3.12+
- `LEAD_INGEST_KEY` in repo-root `.env`
- Existing `leads_output.csv` in `scripts/lead_automation/`

## Configuration

| File | Description |
|------|-------------|
| `keywords.json` | Maps niche keys to category labels for ingest payload |
| `leads_output.csv` | Input from leadgen |

## How to run

From `scripts/lead_automation/`:

```bash
# One POST per lead
python lead_automation.py -i
python lead_automation.py --individual

# Single bulk POST
python lead_automation.py -b
python lead_automation.py --bulk
```

One mode (`-i` or `-b`) is required.

## How it works

1. Parse CLI flags (`-i` / `-b`).
2. Read `leads_output.csv` row by row.
3. Extract a clean email via `extract_real_email()`.
4. Map niche from `keywords.json` to a category label.
5. **Individual:** POST each lead to `/leads-ingest`.
6. **Bulk:** Collect all leads and POST once to `/leads-ingest-bulk`.

Both endpoints use `LEAD_INGEST_KEY` via `APIManager`.

## Related scripts

- [leadgen.md](leadgen.md) — generates the CSV
- [webhook_manager.md](webhook_manager.md) — optional Make.com email trigger (separate flow)
