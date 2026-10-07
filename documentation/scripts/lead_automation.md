# Lead Automation (ingest)

**Source:** `scripts/lead_automation/lead_automation.py`

## Purpose

Reads leads from `leads_output.csv` (produced by [leadgen](leadgen.md)) and creates them in the CRM through the MCP server (`create_lead`). `--individual` and `--bulk` both use that path. Filters junk emails containing `sentry` or `wixpress`.

## Prerequisites

- Python 3.12+
- `CRM_MCP_MV_LLC` in repo-root `.env`
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
5. Create each lead with the CRM MCP `create_lead` tool (`CRM_MCP_MV_LLC` as a bearer token). `--individual` and `--bulk` use the same call.

## Related scripts

- [leadgen.md](leadgen.md) — generates the CSV. `--mode new-business` writes `new_business_leads.json` and `new_business_leads.csv` and does not go through this ingest.
- [new_business_sources.md](new_business_sources.md) — sources used by new-business discovery
- [webhook_manager.md](webhook_manager.md) — optional Make.com email trigger (separate flow)
