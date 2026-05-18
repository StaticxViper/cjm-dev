# Setup

One-time configuration before running lead generation or automation.

## Step 1: Open the lead automation folder

All scripts read `keywords.json`, `coords.json`, and default CSV paths from this directory.

```powershell
cd E:\REPOS\cjm-dev\scripts\lead_automation
```

## Step 2: Set environment variables

Add these to the repo `.env` file at `E:\REPOS\cjm-dev\.env` (or export them in your shell). Scripts call `load_dotenv()` automatically.

| Variable | Used by | Purpose |
|----------|---------|---------|
| `GOOGLE_API_KEY` | `leadgen.py` | Google Places Nearby Search and Place Details |
| `LEADS_API_KEY` | `lead_automation.py`, `leads_api.py` | `x-api-key` header for `/functions/v1/leads-ingest` |

Example:

```env
GOOGLE_API_KEY=your-google-key
LEADS_API_KEY=your-leads-ingest-key
```

If `LEADS_API_KEY` is missing, automation stops with: `LEADS_API_KEY environment variable is not set`.

## Step 3: Configure search targets

Edit files in `scripts/lead_automation/`:

**`coords.json`** — cities and lat/lng coordinates to search around.

**`keywords.json`** — niche keys mapped to API category tags, for example:

```json
{
  "landscaping": "landscaping-leads",
  "plumbing": "plumbing-leads"
}
```

## Step 4: (Optional) Install Python dependencies

From the repo root, install project requirements if you have not already:

```powershell
cd E:\REPOS\cjm-dev
pip install -r requirements/requirements.txt
```

## Step 5: Verify tests (optional)

From the repo root:

```powershell
python -m unittest unittests.lead_automation.test_leadfilter unittests.lead_automation.test_leads_api -v
```

## Next steps

- [Pipeline A: Add new leads](pipeline-a-add-leads.md)
- [Pipeline B: Update existing leads](pipeline-b-update-leads.md)
