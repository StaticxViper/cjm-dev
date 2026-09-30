# Job Automation Opportunity Finder

CLI research tool that finds South New Jersey and remote U.S. job listings where employers appear to be hiring for repetitive digital/administrative workflows that could potentially be improved with software automation.

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

- Target NJ counties / place hints
- `include_remote`
- Keyword groups
- Source enable/disable
- Search limits and qualification thresholds
- Browser pacing / headless defaults
- Output CSV paths

## Commands

Run from `scripts/opp_finder/`:

```bash
cd scripts/opp_finder
python main.py search --south-nj --limit 100
python main.py search --remote --limit 50
python main.py search --keyword "property research" --limit 25
python main.py search --south-nj --remote --limit 100 --headless
python main.py search --refresh --verbose
```

Flags:

| Flag | Meaning |
|------|---------|
| `--south-nj` | Prioritize South/Central NJ geography (default when no geo flag is given) |
| `--remote` | Focus on remote U.S. roles |
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
