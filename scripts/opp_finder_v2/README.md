# Opp finder v2

Personal remote and contract job search. A JSON file lists the boards. For each enabled site the tool uses the cheapest compliant read path: a public JSON API, then RSS, then guest Playwright. Logged-in browsing stays off unless you opt in.

This package does not import or modify `scripts/opp_finder` or `scripts/lead_automation`. It does not apply to jobs, send messages, or upload results to a CRM. It writes JSON and optional CSV.

## Setup

From the repo root, install dependencies (Playwright is already listed):

```bash
pip install -r requirements/requirements.txt
python -m playwright install chromium
```

Chromium is only required when a run selects a `playwright` site. API and RSS runs do not launch a browser.

Run from `scripts/` so the package imports:

```bash
cd scripts
python -m opp_finder_v2 --validate
python -m opp_finder_v2 --list-sites
python -m opp_finder_v2 --dry-run --sites remotive,remoteok,weworkremotely
```

`--dry-run` reads `fixtures/<site_id>/` and does not open a network connection.

## CLI

```bash
cd scripts
python -m opp_finder_v2 \
  --config opp_finder_v2/sites.json \
  --criteria opp_finder_v2/criteria.json \
  --keywords "python, automation, playwright" \
  --sites remotive,remoteok,weworkremotely \
  --out opp_finder_v2/output/out.json \
  --format both \
  --max-per-site 50
```

| Flag | Behavior |
| --- | --- |
| `--config` | Site catalogue. Default is the package `sites.json`. |
| `--criteria` | Scoring and hard filters. Default is the package `criteria.json`. |
| `--keywords` | Replaces `keywords.any` for this run. |
| `--sites` | Comma-separated ids. Disabled guest sites run when named. Unknown ids exit 2. |
| `--out` | JSON path. Default `output/opps_<run_id>.json`. |
| `--format` | `json` (default), `csv`, or `both`. CSV is written next to `--out`. |
| `--dry-run` | Fixtures only. |
| `--headful` | Show the browser. Headless is the default. |
| `--max-per-site` | Lowers each site's `max_results`. It never raises it. |
| `--since-days` | Overrides `posted_within_days`. |
| `--allow-login` | Allow `storage_state` sites. They must also be enabled, and the env var must point at a file outside the repo. |
| `--no-artifacts` | Skip screenshot and HTML dumps. |
| `--list-sites` | Print id, name, mode, access, enabled, and ToS risk, then exit. |
| `--validate` | Validate config and criteria, then exit. |
| `--verbose` | Debug logging. |

Exit codes: `0` the run finished (individual sites may be skipped), `2` invalid config or unknown site id, `3` every selected site failed or was skipped.

## Output

JSON matches `schemas/output.schema.json`. Opportunities are sorted by `relevance_score`, then `posted_date`. `opp_id` is `sha256(normalized title + "|" + normalized company)` truncated to 16 hex characters, so a later ingest can upsert the same role across runs. The URL and location are not part of the hash.

CSV uses the same field names. Lists of strings are joined with ` | `. `sources` and `score_breakdown` are compact JSON.

## Add a site

1. Add an object to `sites.json`. `id` matches `^[a-z0-9_]+$`.
2. Set `mode` to `api`, `rss`, or `playwright`. Use `none` for a catalogue stub that must never be fetched.
3. Map `results.fields` to dotted JSON paths, RSS tag names, or an ordered locator list (`role`, `test_id`, `attr`, `text`, `css`).
4. Leave `enabled` false until you have saved a fixture and checked the site's terms.
5. Run `--validate`.

Put Python in `adapters/custom/` only when the payload is not a list of job objects (We Work Remotely's `Company: Role` titles, HN comment threads). Register the module name in `adapters/custom/__init__.py` and set `custom` on the site.

## Refresh a fixture

```bash
# save the response yourself, then trim it into:
scripts/opp_finder_v2/fixtures/<site_id>/response.json   # API
scripts/opp_finder_v2/fixtures/<site_id>/feed.xml        # RSS
scripts/opp_finder_v2/fixtures/<site_id>/page.html       # Playwright results page
```

Record the capture date and URL in `fixtures/<site_id>/README.md`. Strip email addresses and other personal data. Do not commit storage-state files.

## Logged-in sessions

Create the Playwright storage state outside the repo:

```bash
playwright codegen --save-storage=%USERPROFILE%\secrets\linkedin_state.json https://www.linkedin.com/login
```

Point an env var at that file (for example `LINKEDIN_STORAGE_STATE`) and set `auth.storage_state_env` to the variable name. The site still has to be `enabled: true`, selected, and the process has to be started with `--allow-login`. CI never passes that flag.

## Terms

Prefer the public APIs and RSS feeds that ship enabled (Remotive, Remote OK, We Work Remotely, Himalayas, Jobicy, the HN Algolia API). Keep each record's source URL. Remotive and Remote OK require attribution if you display results.

LinkedIn and Indeed prohibit automated scraping and ship `enabled: false` with `tos.risk: high`. Logged-in LinkedIn scraping can cost you the account. Dice, Upwork, Wellfound, FlexJobs, and Built In also ship disabled. Working Nomads stays disabled until a documented public feed exists. Toptal is a talent network, not a board (`mode: none`). SuperCruiter is a stub until the real URL is confirmed.

On a captcha, login wall, or block page the tool stops that site, writes `artifacts/<run_id>/<site_id>/`, and does not retry or bypass. A normal page that merely contains the word "blocked" is not treated as a block.

Default caps are 50 results per site, a few pages, and multi-second random delays. One site runs at a time. This is engineering guidance for personal low-volume use, not legal advice.

## GitHub Actions

`.github/workflows/opp_finder_v2.yml` runs the unit tests on pull requests and a `workflow_dispatch` search. GitHub only shows `workflow_dispatch` after the workflow file is on the default branch (`main`). Until then, dispatching `opp_finder_v2.yml` will not work.
