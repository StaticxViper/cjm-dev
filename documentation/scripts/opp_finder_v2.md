# Opp finder v2

Config-driven finder for remote and contract roles. It reads public JSON and RSS first, and uses Playwright only for boards that have no such feed. A live run writes JSON (and optional CSV) and uploads kept listings to the CRM MCP server. It does not apply to jobs or message anyone.

`scripts/opp_finder` (automation-opportunity scoring, contact enrichment, Google discovery) and `scripts/lead_automation` (local-business lead gen) are separate tools. V2 does not import them.

## Run it

From the repo root, with the project virtualenv active:

```bash
source .venv/Scripts/activate
cd scripts
python -m opp_finder_v2
```

No flags opens the menu: employment type, remote or on-site, keywords, skill toggles, and saved presets. `--run` skips the menu and searches with `criteria.json`. `--preset "Part-time IT"` runs that saved search. Matches upload to the CRM MCP server (`https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1/mcp-crm`, bearer token `CRM_MCP_MV_LLC`) in the Side Job Leads venture. `--no-crm` and `--dry-run` do not upload. The tool does not use `APIManager`.

The `cd scripts` is required. From the repo root, `python -m opp_finder_v2` cannot find the package.

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

Verified against the live feeds on 2026-10-06 and enabled:

- Remotive `GET https://remotive.com/api/remote-jobs?category=software-dev` (one request per run; a keyword has to appear in the title)
- Remote OK `GET https://remoteok.com/api` (first element is the legal notice and is skipped; attribute Remote OK)
- We Work Remotely combined feed plus the programming and DevOps/sysadmin category RSS feeds (title `Company: Role` is split in `adapters/custom/wwr_title.py`)
- Himalayas `https://himalayas.app/jobs/api/search`
- Jobicy `https://jobicy.com/api/v2/remote-jobs` (no API key; `url` stays the Jobicy listing)
- HN "Who is hiring?" via `hn.algolia.com/api/v1`
- The Muse public API, Computer and IT, Flexible/Remote (`https://www.themuse.com/api/public/jobs`)
- Working Nomads `https://www.workingnomads.com/api/exposed_jobs`
- Greenhouse public boards for GitLab, Cloudflare, Elastic, and Datadog (`boards-api.greenhouse.io`)

Lever board JSON is wired but disabled until `companies` lists board tokens. Dice, Remote.co, Built In, Indeed, LinkedIn (guest and logged-in), Wellfound, Upwork, FlexJobs, and Contra are disabled placeholder entries. Toptal and SuperCruiter use `mode: none`. A kept job has to carry a keyword in the title (`require_title_match`). Hybrid and office locations are not treated as remote.

## Politeness and blocks

One site at a time. Random delay between requests to that site, plus `max_requests` and `max_results`. Network errors, HTTP 429, and HTTP 5xx retry twice with backoff and honor `Retry-After`. HTTP 403 and detected block pages do not retry.

Detection looks for captcha widgets, "verify you are human", Cloudflare challenges, `/sorry/`, and login URLs (`/login`, `/signin`, `/authwall`, `/checkpoint`). It does not treat the bare word "blocked" or a noscript "enable javascript" line as a block. A hit stops that site and writes HTML, a screenshot, and `meta.json` under `scripts/opp_finder_v2/artifacts/`.

## CI

`.github/workflows/opp_finder_v2.yml` has two jobs:

- Pull requests that touch this package run `pytest unittests/opp_finder_v2`.
- `workflow_dispatch` runs the CLI against the public API/RSS ids by default, uploads `opp-finder-v2-results`, and writes the top 10 rows to the job summary. It never passes `--allow-login`.

`workflow_dispatch` can be started only after this file is on the default branch (`main`). A copy that exists only on a feature branch will not appear in the Actions list.
