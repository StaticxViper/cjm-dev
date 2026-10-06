# Opp finder v2

Config-driven finder for remote and contract roles. It reads public JSON and RSS first, and uses Playwright only for boards that have no such feed. Output is a JSON file (and optional CSV) for a later CRM ingest. This run does not call a CRM, apply, or message anyone.

`scripts/opp_finder` (automation-opportunity scoring, contact enrichment, Google discovery) and `scripts/lead_automation` (local-business lead gen) are separate tools. V2 does not import them.

## Run it

From the repo root, with the project virtualenv active. Install dependencies first if Python reports `No module named 'jsonschema'`:

```bash
source .venv/Scripts/activate
pip install -r requirements/requirements.txt
cd scripts
python -m opp_finder_v2
```

That searches the enabled boards and writes `scripts/opp_finder_v2/output/opps_<timestamp>.json`. The `cd scripts` is required. From the repo root, `python -m opp_finder_v2` cannot find the package.

`--dry-run` uses fixtures and does not use the network. `--format both` also writes a CSV beside the JSON. The rest of the flags are in [scripts/opp_finder_v2/README.md](../../scripts/opp_finder_v2/README.md).

## What a run does

1. Validate `sites.json` and `criteria.json`. Invalid files exit 2.
2. Walk the selected sites one at a time.
3. Fetch with the adapter for `mode` (`api`, `rss`, `playwright`). `mode: none` is recorded as `skipped_manual` and not fetched.
4. Normalize each listing, apply hard filters, then a deterministic `relevance_score`.
5. Dedupe across sites on canonical URL, then on `sha256(title|company)` when the company name is present.
6. Rewrite the output file after every site so a crash keeps earlier results.

Hard filters drop a record for an exclude keyword, a failed `keywords.all` list, no `keywords.any` match, `remote: false` when `remote_only` is set, a location deny phrase, a known post date older than `posted_within_days`, a known USD rate under `min_rate`, or an employment type outside the allowed list. Missing date, rate, location, or type does not drop the record and does not add points, unless that field's `unknown` value is `drop`.

Score weights live in `scripts/opp_finder_v2/relevance.py`. `relevance_score` is the sum of `score_breakdown`, clamped to 100. Records under `min_relevance` are dropped and counted.

## Setup and commands

```bash
pip install -r requirements/requirements.txt
python -m playwright install chromium
cd scripts
python -m opp_finder_v2 --list-sites
python -m opp_finder_v2 --dry-run --format both --out opp_finder_v2/output/out.json
```

See [scripts/opp_finder_v2/README.md](../../scripts/opp_finder_v2/README.md) for the full flag list, how to add a site, how to refresh fixtures, and how to create a storage-state file outside the repo.

Tests, from the repo root:

```bash
pytest unittests/opp_finder_v2
python -m unittest discover unittests/opp_finder_v2
```

Both should pass. They do not use the network. The Playwright test loads `fixtures/sample_board/page.html` with `page.set_content`.

## Enabled boards

Verified against the live feeds on 2026-10-05 and enabled:

- Remotive `GET https://remotive.com/api/remote-jobs` (one request per run; keywords filtered locally; attribute Remotive)
- Remote OK `GET https://remoteok.com/api` (first element is the legal notice and is skipped; attribute Remote OK)
- We Work Remotely `https://weworkremotely.com/remote-jobs.rss` (title `Company: Role` is split in `adapters/custom/wwr_title.py`)
- Himalayas `https://himalayas.app/jobs/api/search`
- Jobicy `https://jobicy.com/api/v2/remote-jobs` (no API key; `url` stays the Jobicy listing)
- HN "Who is hiring?" via `hn.algolia.com/api/v1` (`adapters/custom/hn_hiring.py` reads the monthly thread's comments)

Working Nomads is present and disabled: no documented public JSON or RSS endpoint was confirmed. Greenhouse and Lever board JSON is wired but disabled until `companies` lists board tokens. Dice, Remote.co, Built In, Indeed, LinkedIn (guest and logged-in), Wellfound, Upwork, FlexJobs, and Contra are disabled placeholder entries. Toptal and SuperCruiter use `mode: none`.

## Politeness and blocks

One site at a time. Random delay between requests to that site, plus `max_requests` and `max_results`. Network errors, HTTP 429, and HTTP 5xx retry twice with backoff and honor `Retry-After`. HTTP 403 and detected block pages do not retry.

Detection looks for captcha widgets, "verify you are human", Cloudflare challenges, `/sorry/`, and login URLs (`/login`, `/signin`, `/authwall`, `/checkpoint`). It does not treat the bare word "blocked" or a noscript "enable javascript" line as a block. A hit stops that site and writes HTML, a screenshot, and `meta.json` under `scripts/opp_finder_v2/artifacts/`.

## CI

`.github/workflows/opp_finder_v2.yml` has two jobs:

- Pull requests that touch this package run `pytest unittests/opp_finder_v2`.
- `workflow_dispatch` runs the CLI against the public API/RSS ids by default, uploads `opp-finder-v2-results`, and writes the top 10 rows to the job summary. It never passes `--allow-login`.

`workflow_dispatch` can be started only after this file is on the default branch (`main`). A copy that exists only on a feature branch will not appear in the Actions list.
