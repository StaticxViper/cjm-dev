# Job Automation Opportunity Finder

CLI research tool that finds **multi-location** (South Jersey, Philly metro, Delaware, North Jersey) and **remote U.S.** job listings where employers appear to be hiring for repetitive digital/administrative workflows that could potentially be improved with software automation.

By default it **prioritizes remote roles** in both search order and lead ranking.

This tool does **not** send outreach, bypass CAPTCHAs, or fabricate contacts. It writes CSV files you can import elsewhere.

## Installation

From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements/requirements.txt
# or: pip install -r scripts/opp_finder/requirements.txt
python -m playwright install chromium
```

## Environment variables

None required for core search/analysis.

Optional (repo logger upload only):

| Variable | Purpose |
|----------|---------|
| `MVLLC_LOGS_KEY` | Upload run logs via the shared logger (optional) |

## Configuration

Edit [`config.yaml`](config.yaml):

- `locations` regions (enable/disable South Jersey, Philly metro, Delaware, North Jersey, etc.)
- `prioritize_remote` / `include_remote`
- Keyword groups
- Source enable/disable
- Search limits and qualification thresholds
- Browser pacing / headless defaults
- Output CSV paths

## Commands

Run from `scripts/opp_finder/`:

```bash
cd scripts/opp_finder
# Default: all enabled locations, remote-first
python main.py search --limit 100
python main.py search --locations south_jersey,philadelphia_metro,delaware --limit 100
python main.py search --remote --limit 50
python main.py search --south-nj --limit 50
python main.py search --keyword "property research" --limit 25
python main.py search --no-prioritize-remote --limit 50
python main.py search --refresh --verbose
```

Flags:

| Flag | Meaning |
|------|---------|
| *(default)* | All enabled `locations` in config + remote included, remote prioritized |
| `--locations a,b` | Restrict to named regions from `config.yaml` |
| `--south-nj` | Limit local targeting to the `south_jersey` region |
| `--remote` | Remote U.S. roles only |
| `--prioritize-remote` / `--no-prioritize-remote` | Force remote-first on/off |
| `--keyword` | Use one keyword instead of the full configured list |
| `--limit` | Cap total jobs collected |
| `--headless` / `--headed` | Browser mode override |
| `--refresh` | Reprocess jobs already present in CSV |
| `--verbose` | Debug logging |
| `--no-remote` | Exclude remote roles for this run |

## Output files

Written under `scripts/opp_finder/output/` (gitignored via `*output/`):

| File | Contents |
|------|----------|
| `all_jobs.csv` | All discovered/deduped jobs after Stage 1 analysis |
| `qualified_opportunities.csv` | Jobs meeting score thresholds after Stage 2 enrichment |
| `search_history.csv` | Per-source run metadata |

## How qualification works

Two-stage pipeline:

1. **Stage 1 (cheap):** discover listings → dedupe → geo/remote filter → extract `workflow_tasks` → score automation signals.
2. **Stage 2 (deep):** only for scores above `qualification.minimum_automation_score` / `minimum_opportunity_score` → public company/contact research → outreach draft + demo concept.

Component scores (0–100):

- `automation_score`
- `business_value_score`
- `contactability_score`
- `urgency_score`
- `implementation_fit_score`

Combined into explainable `opportunity_score`. Language stays tentative (“potentially automatable”). Contacts are marked `verified_public` only when found on a public page; emails are never guessed.

## GitHub Action (API-callable)

Workflow: [`.github/workflows/opp_finder.yml`](../../.github/workflows/opp_finder.yml)

Triggers:

- `workflow_dispatch` (Actions UI or REST API)
- `repository_dispatch` with `event_type: opp-finder-search`

Outputs:

- Job outputs: `all_jobs_count`, `qualified_count`, `truncated`, `results_json` (CSV-derived JSON)
- Artifact `opp-finder-results`: `all_jobs.csv`, `qualified_opportunities.csv`, `search_history.csv`, `api_results.json`

### Trigger via API (`workflow_dispatch`)

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/opp_finder.yml/dispatches \
  -d '{
    "ref": "main",
    "inputs": {
      "keyword": "data entry",
      "limit": "25",
      "mode": "south-nj",
      "refresh": "false"
    }
  }'
```

### Trigger via API (`repository_dispatch`)

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/OWNER/REPO/dispatches \
  -d '{
    "event_type": "opp-finder-search",
    "client_payload": {
      "keyword": "property research",
      "limit": 25,
      "mode": "south-nj",
      "refresh": false
    }
  }'
```

### Fetch CSV info after the run

1. Find the run id:
   ```bash
   gh run list --workflow=opp_finder.yml --limit 1
   ```
2. Download the artifact (full CSVs + JSON):
   ```bash
   gh run download <RUN_ID> --name opp-finder-results
   ```
3. Or read job outputs (`results_json`) from the completed run in the Actions UI / `gh run view <RUN_ID>`.

Locally build the same API payload from existing CSVs:

```bash
cd scripts/opp_finder
python export_api_results.py
# writes output/api_results.json
```

## Known limitations

- Google, Indeed, and ZipRecruiter frequently present CAPTCHAs / bot blocks (especially from datacenter IPs). The tool logs `[BLOCKED]` and continues with other sources such as Craigslist — it does not bypass protections.
- Workflow and automation scores are heuristic (keyword/signal based), not guarantees.
- Company contact coverage depends on publicly crawlable websites.
- Detail extraction quality varies by host HTML structure.
- Large keyword × location runs are query-budgeted; use `--keyword` / `--limit` for focused research.
- Outreach drafts are never sent automatically.

## Project layout

```
scripts/opp_finder/
  main.py
  pipeline.py
  config.yaml
  scrapers/
  analysis/
  enrichment/
  utils/
  output/
  README.md
```
