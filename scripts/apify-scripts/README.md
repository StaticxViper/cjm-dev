# Apify Actors

Playwright scrapers packaged for the Apify Marketplace. Issue #128. Local CLIs stay in place and are the source of truth. Actors under this folder import them.

| Folder | Status | Source CLI |
|--------|--------|------------|
| [`_template/`](_template/) | Copy this for a new Actor | — |
| [`ats-jobs/`](ats-jobs/) | Job listings | Public Greenhouse, Lever, Ashby, and Workable job-board APIs for a company list. HTTP only, no proxy or CAPTCHA. A block stops with one `blocked` row. |
| [`city-data/`](city-data/) | Phase 1 | [`scripts/city_data/`](../city_data/) (issue #99) |
| [`google-business/`](google-business/) | Phase 1 | Maps session in [`scripts/lead_automation/playwright_discovery.py`](../lead_automation/playwright_discovery.py); match rules from issue #127 |
| [`contractor-license/`](contractor-license/) | Public records | CA CSLB open CSV. AZ, NJ, and PA adapters stop on a challenge or a closed portal. Issue #155. |
| [`home-services/`](home-services/) | Phase 1 | Wraps the google-business matcher and Maps session. Niche and area leads with website email, quality, and intent score |
| [`new-business/`](new-business/) | Entity filings | Verified NY, PA, and CO open-data feeds from [`scripts/lead_automation/new_business_pipeline.py`](../lead_automation/new_business_pipeline.py). |
| [`permits/`](permits/) | Building permits | Verified Chicago, Seattle, Austin, and Los Angeles Socrata feeds. Reuses [`new_business_sources`](../lead_automation/new_business_sources/) open-data and HTML-table adapters. |
| [`zillow/`](zillow/) | Listing agents | [`scripts/zillow_automation/zillow_agents.py`](../zillow_automation/zillow_agents.py). Residential Apify Proxy on the platform. Script Manager entry `zillow-apify` starts it with `APIFY_TOKEN`. |

Later folders (not created yet): `amazon/`, `youtube/`, `instagram/`. Each one is a copy of `_template/` after Phase 1 is accepted. Instagram already has a Store Actor we call from `helper_scripts/api_manager`; a first-party listing is a separate decision.

## Create an Actor

1. Copy `_template/` to `scripts/apify-scripts/<name>/`.
2. Rename `name` / `title` / `description` in `.actor/actor.json`.
3. Extend the input and dataset schemas. Keep `headless`, `maxSpendUsd`, `maxProxyCostUsd`, `allowCaptcha`, and the proxy group fields from the template. Declare dataset fields for nested objects and add a Detail view next to Overview. Use `editor: "select"` when a field is a list of known values.
4. Replace `src/main.py`. Call the existing scraper inside `asyncio.to_thread`. Import it; do not move or rewrite the CLI. `src/runtime.py` re-exports `scripts/apify-scripts/runtime.py`, including the access ladder in `access.py`.
5. List every repo file the Actor imports in `bundle.txt` (keep `runtime.py` and `access.py`), then run `python scripts/apify-scripts/actor_build.py bundle <name>` and `isolate <name>`. Leave the Dockerfile as copied. Set `defaultRunOptions.timeoutSecs`.
6. Give every integer `max*` input a `default` and a `maximum`, and every free-form list a `maxItems`. Keep the defaults small.
7. Write `fixtures/INPUT.json` as a small run and `fixtures/budget.json` for it (see [Build and budgets](#build-and-budgets)). Run `budgets --write` to refresh the table below.
8. Write the marketplace `README.md` from the template headings.
9. Add unit tests under `unittests/apify_scripts/` for input mapping and dataset shape. No live site calls in those tests.

## Build and budgets

Each Actor folder is its own Docker build context. `apify push` from the folder uploads only that folder, and the Dockerfile copies only local files. Repo modules the Actor imports are listed in `bundle.txt` and copied into the committed `platform_bundle/` folder; `CJM_REPO_ROOT` points there in the image. The Dockerfile leaves the base image `WORKDIR` (`/usr/src/app`) and its `./xvfb-entrypoint.sh` entrypoint in place. A `!module` line in `bundle.txt` names an import that only the local CLI reaches, left out on purpose.

`actor_build.py` (standard library only) keeps that honest:

| Command | What it does |
|---------|--------------|
| `bundle [ACTOR ...]` | Rewrite `platform_bundle/` from `bundle.txt`. Run it after a shared module changes. |
| `check [ACTOR ...]` | Fail on bundle drift, a Dockerfile or `actor.json` path outside the Actor folder, an unbounded input limit, a budget outside the Actor's memory range or timeout, or a stale budget table. `ci.yml` runs it on every pull request. |
| `isolate ACTOR` | Copy the build context to a temp folder and import every module the Actor names from the bundle only. |
| `smoke ACTOR` | Build the image, run `fixtures/INPUT.json` in Docker with the budget memory as a hard limit and pay per event simulated from `.actor/pay_per_event.json`, and fail on an overrun. |
| `smoke ACTOR --platform` | Run the pushed Actor on Apify with `APIFY_TOKEN` at the budget memory and timeout, and fail on an overrun. Adds the platform usage check. |

A smoke run fails when the status is not `SUCCEEDED` (including out of memory and timeout), peak memory is above `memoryMbytes`, the run takes longer than `maxDurationSecs`, the dataset row count is outside `minItems`-`maxItems`, the pay-per-event charge is above `maxChargeUsd`, or (platform only) usage is above `maxUsageUsd`. An event that is not in `pay_per_event.json` is priced at $1 in a Docker smoke, so it shows up as an overrun.

Budgets live in each `fixtures/budget.json`. The table is generated by `actor_build.py budgets --write`, and `check` fails when it is stale:

<!-- budgets:begin -->
| Actor | Memory (MB) | Max duration (s) | Dataset rows | Max PPE charge (USD) | Max platform usage (USD) |
|-------|-------------|------------------|--------------|----------------------|--------------------------|
| `city-data` | 2048 | 300 | 1-2 | 0.05 | 0.1 |
| `contractor-license` | 512 | 300 | 1-5 | 0.25 | 0.03 |
| `google-business` | 2048 | 420 | 1-3 | 0.2 | 0.1 |
| `home-services` | 2048 | 600 | 1-5 | 0.5 | 0.15 |
| `new-business` | 1024 | 300 | 1-10 | 0.5 | 0.05 |
| `permits` | 1024 | 300 | 1-10 | 0.5 | 0.05 |
| `zillow` | 4096 | 600 | 0-2 | 0.1 | 0.25 |
<!-- budgets:end -->

`.github/workflows/apify_actors.yml` runs `check`, then builds every image, runs the import probe inside it, and runs the Docker smoke against the budget. It runs on pull requests that touch an Actor or a shared module, weekly, and by hand. A manual run with `platform` checked also runs `apify push` and the platform smoke, with the `APIFY_TOKEN` secret.

A budget is for the fixture, not for a Store run. Store users get the input-schema defaults, which `check` requires to be bounded. Raise a budget only with a note in its `notes` field. Fixture failures caused by Actor logic belong to that Actor's issue, and the fix must pass the same gate.

## Run locally

From the Actor directory, repo virtualenv active (Python 3.12, Playwright Chromium, `apify` CLI):

```bash
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

`storage/` is gitignored. `apify run` executes `python -m src` on the host. It does not need Docker. If the Apify CLI is not installed, the same entrypoint is `python -m src` from the Actor directory after `fixtures/INPUT.json` is copied to `storage/key_value_stores/default/INPUT.json`. A platform build uses the Dockerfile.

## Publish checklist

Do this only when a listing is requested. `APIFY_TOKEN` is the CLI / `apify push` credential. `APIFY_API_KEY` and `APIFY_USER_ID` stay the consumer credentials in `api_manager`. Do not register the new Actors in `ACTORS` until after the first public listing.

1. `python scripts/apify-scripts/actor_build.py check <name>` and `smoke <name>` pass (or the Apify Actors workflow is green for the commit).
2. `apify login` with `APIFY_TOKEN` (not `APIFY_API_KEY`).
3. In the Actor directory, `apify push`. No staging step is needed; `platform_bundle/` is already in the folder.
4. `python scripts/apify-scripts/actor_build.py smoke <name> --platform` passes. It runs the committed `fixtures/INPUT.json` on the private build at the budget memory and timeout. Confirm dataset rows and key-value `SUMMARY`.
5. Paste the Actor `README.md` into the Store listing. Set categories in the Console (they are not an `actor.json` field). Suggested starting points are in each README.
6. Set the Console pricing model to pay per event using `.actor/pay_per_event.json`. Charge `result` only for a successful city profile or an accepted Maps match. Charge `license` only for a found contractor license. Charge `business` only for a returned entity and `enrichment` only when a website or email is found. Charge `permit` only for a pushed building permit. Charge `proxy` only after a blocked request was retried through Apify Proxy, and `captcha` only when a solver returns a token. Do not enable pay per dataset item.
7. Choose a private listing or a public one. Public Google Business needs the ToS / robots section left intact.
8. Save a sample dataset export and a screenshot with the listing. Update `.actor/CHANGELOG.md`.

## Purpose, inputs, outputs, and secrets

Actors package the local Playwright CLIs for the Apify platform. Input is the Actor `INPUT.json` (`fixtures/INPUT.json` locally). Output is an Apify dataset plus a key-value `SUMMARY`. Local run is `apify run --purge` from the Actor directory, or `python -m src` after copying the fixture into `storage/key_value_stores/default/INPUT.json`. GitHub Actions workflow `ci.yml` runs `pytest unittests/` on every pull request, including `unittests/apify_scripts`, and `actor_build.py check`. `apify_actors.yml` builds each Actor image and runs its fixture smoke against the budget. `apify_scripts.yml` is a manual re-run of the actor unit tests. Publish uses `APIFY_TOKEN`. The Actors themselves do not read `APIFY_API_KEY`. `zillow-apify` is the Script Manager entry that starts the Zillow Actor through the Apify API and downloads the dataset. The other Actors are not Script Manager entries. Longer notes are the sections above.

## Proxy, CAPTCHA, and spend

Proxy rotation and CAPTCHA solving are allowed when a target needs them to return data. Use the cheapest path that still works:

1. Direct request first. A page that loads does not use a proxy or a solver.
2. Apify Proxy only after a real block (HTTP 401, 403, 429, or a challenge page). The default group is datacenter. A residential group is used only when the input selects it.
3. A CAPTCHA solve only when that proxy retry is still a challenge, `allowCaptcha` is true, and `maxSpendUsd` still covers the solve.

`maxSpendUsd` caps result, proxy, and CAPTCHA events together. `maxProxyCostUsd` caps proxy events and is clamped to the spend cap. `0` skips the proxy retry. `allowCaptcha` defaults to false. When a cap is hit, solving is off, or no solver is configured, push one `blocked` row and exit 0. Do not keep retrying and do not hide the cost inside the developer account. Charge `proxy` and `captcha` through pay per event. A solve is billed only when a solver returns a token. Data rows stay success-only charges. Direct requests are free.

Shared helpers live in `scripts/apify-scripts/access.py` (`Actor.create_proxy_configuration` on escalate, the block ladder, the spend ledger, and the proxy / CAPTCHA charge). `city-data`, `google-business`, and `permits` call them. `new-business` follows the same ladder in its HTTP fetch. `home-services` still stops on a block with no proxy charge until it calls that module. `contractor-license` returns a status row when a portal shows a challenge and does not spend to get past it.

`zillow` is the exception. Zillow blocks the platform IP, so every Zillow request on Apify goes through `Actor.create_proxy_configuration` with the residential group unless the input selects another group. A local run leaves the proxy unset. A block or captcha page is stored for that ZIP and the run moves on. This Actor does not call a CAPTCHA solver.

## Rules that stay in force

- Playwright only for city-data, google-business, and home-services. No paid Maps or Places call in `google-business` or `home-services`. `contractor-license`, `new-business`, and `permits` are HTTP and do not launch Chromium.
- Respect robots.txt with `scripts/lead_automation/crm_enrich_robots.py` (longest match). Google web search (`/search`) is never requested. A robots disallow is not retried through a proxy.
- Keep the delays from the source session. Do not add stealth plugins. The Maps session still launches Chromium with `--disable-blink-features=AutomationControlled`.
- Say in the Actor README when a run may use a proxy or a solve, and note the site terms.
- Do not change CLI flags, defaults, or env loading in `scripts/lead_automation/` or `scripts/city_data/`. The browser sessions take an optional `proxy` argument that CLI runs leave unset.
