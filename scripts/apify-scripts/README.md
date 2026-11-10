# Apify Actors

Playwright scrapers packaged for the Apify Marketplace. Issue #128. Local CLIs stay in place and are the source of truth. Actors under this folder import them.

| Folder | Status | Source CLI |
|--------|--------|------------|
| [`_template/`](_template/) | Copy this for a new Actor | — |
| [`ats-jobs/`](ats-jobs/) | Job listings | Public Greenhouse, Lever, Ashby, and Workable job-board APIs for a company list. HTTP only, no proxy or CAPTCHA. A block stops with one `blocked` row. |
| [`app-reviews/`](app-reviews/) | App reviews | Public iTunes customer-reviews RSS and lookup. HTTP only, no proxy or CAPTCHA. A block stops with one `blocked` row. Google Play is deferred. |
| [`shopify-store/`](shopify-store/) | Shopify catalogs | Public `/products.json` and `/collections.json` for a domain list. HTTP only, no proxy or CAPTCHA. A block pushes one `blocked` row and stops the run. Issue #183. |
| [`gov-contracts/`](gov-contracts/) | Federal contracts | SAM.gov opportunities and USAspending contract awards by NAICS, state, and set-aside. Official APIs only. A missing SAM key skips opportunities. A block stops that source. |
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
8. Write the marketplace `README.md` from the [Store README template](#store-readme-template). Build notes go under [Actor notes](#actor-notes), not in the Store page.
9. Add unit tests under `unittests/apify_scripts/` for input mapping and dataset shape. No live site calls in those tests.

Do not merge an Actor that is missing from `python scripts/apify-scripts/actor_build.py list`, or whose `check` or `smoke <name>` fails. Unit tests are not a substitute. `check` fails when `bundle.txt`, `fixtures/INPUT.json`, or `fixtures/budget.json` is missing, and `ci.yml` runs it on every pull request. The Apify Actors workflow then builds and smokes every name `list` prints, with no hardcoded Actor list. An HTTP-only Actor may use `apify/actor-python:3.12` instead of the Playwright image. It still omits `dockerContextDir` and leaves `WORKDIR` at `/usr/src/app`.

## Build and budgets

Each Actor folder is its own Docker build context. `apify push` from the folder uploads only that folder, and the Dockerfile copies only local files. Repo modules the Actor imports are listed in `bundle.txt` and copied into the committed `platform_bundle/` folder; `CJM_REPO_ROOT` points there in the image. The Dockerfile leaves the base image `WORKDIR` (`/usr/src/app`) and its `./xvfb-entrypoint.sh` entrypoint in place. A `!module` line in `bundle.txt` names an import that only the local CLI reaches, left out on purpose.

`actor_build.py` (standard library only) keeps that honest:

| Command | What it does |
|---------|--------------|
| `bundle [ACTOR ...]` | Rewrite `platform_bundle/` from `bundle.txt`. Run it after a shared module changes. |
| `check [ACTOR ...]` | Fail when `bundle.txt`, `fixtures/INPUT.json`, or `fixtures/budget.json` is missing, on bundle drift, on a Dockerfile or `actor.json` path outside the Actor folder, on an unbounded input limit, on a budget outside the Actor's memory range or timeout, or on a stale budget table. `ci.yml` runs it on every pull request. A folder with `.actor/actor.json` is included even before those files exist, so a new Actor cannot skip the smoke. |
| `isolate ACTOR` | Copy the build context to a temp folder and import every module the Actor names from the bundle only. |
| `smoke ACTOR` | Build the image, run `fixtures/INPUT.json` in Docker with the budget memory as a hard limit and pay per event simulated from `.actor/pay_per_event.json`, and fail on an overrun. |
| `smoke ACTOR --platform` | Run the pushed Actor on Apify with `APIFY_TOKEN` at the budget memory and timeout, and fail on an overrun. Adds the platform usage check. |

A smoke run fails when the status is not `SUCCEEDED` (including out of memory and timeout), peak memory is above `memoryMbytes`, the run takes longer than `maxDurationSecs`, the dataset row count is outside `minItems`-`maxItems`, the pay-per-event charge is above `maxChargeUsd`, or (platform only) usage is above `maxUsageUsd`. An event that is not in `pay_per_event.json` is priced at $1 in a Docker smoke, so it shows up as an overrun.

Budgets live in each `fixtures/budget.json`. The table is generated by `actor_build.py budgets --write`, and `check` fails when it is stale:

<!-- budgets:begin -->
| Actor | Memory (MB) | Max duration (s) | Dataset rows | Max PPE charge (USD) | Max platform usage (USD) |
|-------|-------------|------------------|--------------|----------------------|--------------------------|
| `app-reviews` | 512 | 180 | 1-5 | 0.02 | 0.05 |
| `ats-jobs` | 512 | 180 | 1-5 | 0.02 | 0.05 |
| `city-data` | 2048 | 300 | 1-2 | 0.05 | 0.1 |
| `contractor-license` | 512 | 300 | 1-5 | 0.25 | 0.03 |
| `google-business` | 2048 | 420 | 1-3 | 0.2 | 0.1 |
| `gov-contracts` | 512 | 180 | 2-2 | 0.016 | 0.05 |
| `home-services` | 2048 | 600 | 1-5 | 0.5 | 0.15 |
| `new-business` | 1024 | 300 | 1-10 | 0.5 | 0.05 |
| `permits` | 1024 | 300 | 1-10 | 0.5 | 0.05 |
| `shopify-store` | 512 | 180 | 1-5 | 0.02 | 0.05 |
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
5. Check that `actor.json` `name` is the Store slug before `apify push`. The Store page shows the `README.md` of the latest build. Confirm the title and description in the Console match `actor.json`, and set categories there (they are not an `actor.json` field).
6. Set the Console pricing model to pay per event using `.actor/pay_per_event.json`. Charge `result` only for a successful city profile or an accepted Maps match. Charge `license` only for a found contractor license. Charge `business` only for a returned entity and `enrichment` only when a website or email is found. Charge `permit` only for a pushed building permit. Charge `review` only for a pushed App Store review and `sentiment` only when that add-on is on for the same pushed review. Charge `opportunity` only for a pushed SAM.gov opportunity and `award` only for a pushed USAspending award. Charge `product` only for a pushed Shopify product and `store` only for a pushed Shopify store profile. Charge `proxy` only after a blocked request was retried through Apify Proxy, and `captcha` only when a solver returns a token. Do not enable pay per dataset item.
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

Shared helpers live in `scripts/apify-scripts/access.py` (`Actor.create_proxy_configuration` on escalate, the block ladder, the spend ledger, and the proxy / CAPTCHA charge). `city-data`, `google-business`, and `permits` call them. `new-business` follows the same ladder in its HTTP fetch. `home-services` still stops on a block with no proxy charge until it calls that module. `contractor-license` returns a status row when a portal shows a challenge and does not spend to get past it. `shopify-store` does not call the ladder: a 401, 403, 429, or challenge on `/products.json` or `/collections.json` pushes one `blocked` row and stops the run.

`zillow` is the exception. Zillow blocks the platform IP, so every Zillow request on Apify goes through `Actor.create_proxy_configuration` with the residential group unless the input selects another group. A local run leaves the proxy unset. A block or captcha page is stored for that ZIP and the run moves on. This Actor does not call a CAPTCHA solver.

## Rules that stay in force

- Playwright only for city-data, google-business, and home-services. No paid Maps or Places call in `google-business` or `home-services`. `contractor-license`, `new-business`, `permits`, `gov-contracts`, `ats-jobs`, `app-reviews`, and `shopify-store` are HTTP and do not launch Chromium.
- Respect robots.txt with `scripts/lead_automation/crm_enrich_robots.py` (longest match). Google web search (`/search`) is never requested. A robots disallow is not retried through a proxy.
- Keep the delays from the source session. Do not add stealth plugins. The Maps session still launches Chromium with `--disable-blink-features=AutomationControlled`.
- Say in the Actor README when a run may use a proxy or a solve, and note the site terms.
- Do not change CLI flags, defaults, or env loading in `scripts/lead_automation/` or `scripts/city_data/`. The browser sessions take an optional `proxy` argument that CLI runs leave unset.

## Store README template

Each Actor `README.md` is the Store page, so it is written for buyers. Keep repo paths, issue numbers, and build notes out of it; they go in [Actor notes](#actor-notes) below. Sections, in order:

1. H1 equal to the `actor.json` `title` (63 characters or fewer, keyword first), then one bold sentence an answer engine can quote: what it returns, from which source, for whom. The primary price per 1,000 results goes right under it.
2. Who is it for: 3–5 buyer personas.
3. What data do you get: a field table that matches `dataset_schema.json`, then one sample row taken from a fixture or a real run.
4. Input: a small example and a table of fields with the `input_schema.json` defaults and maximums.
5. How much does it cost: the events in `pay_per_event.json` only, with worked costs for 100 and 1,000 results.
6. Limits and data source: coverage, pacing, robots, block handling, what is not scraped, and terms or public-data notes.
7. FAQ: question headings that read like search queries, including "Does this need a proxy?" and "What counts as a result?".
8. Integrations and output: dataset, key-value records from `output_schema.json`, and API, schedule, and Make / Zapier / Sheets use.
9. Related actors: 2–3 links to other public `staticxviper` Actors, by their Store slug.
10. Changelog: point to the Changelog tab (`.actor/CHANGELOG.md`).

Store categories are set in the Console. The `actor.json` `name` must equal the Store slug, or `apify push` creates a second Actor: `city-data` publishes as `city-data-scraper` and `google-business` as `google-business-lead-generation`.

## Actor notes

Build and design notes that were moved out of the Store READMEs.

### city-data

Wraps `scripts/city_data/city_data_scraper.py` (issue #99) and its BeautifulSoup parsers. One Chromium session per run. Images, fonts, media, and common ad hosts are blocked by that session. Robots was checked against the live `https://www.city-data.com/robots.txt` while packaging: `/city/{Name}.html` and `/crime/crime-{Name}.html` are not disallowed for `User-agent: *`, while `/so/`, `/city/js/getBoxes.php*`, forum search, and several script endpoints are, and named AI crawlers are `Disallow: /`. The Actor sends the local scraper's Chrome user agent and evaluates the `*` group before every URL.

### google-business

Maps session from `scripts/lead_automation/playwright_discovery.py` (`BusinessDiscoverySession`) with the issue #127 match rules. `https://www.google.com/robots.txt` is evaluated with `crm_enrich_robots.py` because Python's `urllib.robotparser` hides the more specific `/maps/search/` and `/maps/place/` `Allow` lines under `Disallow: /maps/`. Retail words (`food`, `market`, `store`, `shop`, `grocery`) do not count as the brand. Known false pairs that must stay `no_match`: STRIKER CONSTRUCTION SERVICES LLC (NY, Cattaraugus) vs "C. Staker Remodeling", and B&B Basecamp LLC (Denver) vs "Base Camp at Golden Gate Canyon". ZIP-to-county and area-code checks use the tables in `scripts/lead_automation/data/` when present.

### home-services

Reuses the google-business matcher and Maps session. `niche` ids come from `scripts/lead_automation/niches.json` and named areas from `scripts/lead_automation/geo_regions.json` (which can be empty; `City, ST` still works). Name plus state scores 60, so a city or county match is what clears 80. `lead_score` and `intent_signals` come from `intent_scoring.score_intent_lead`; the legacy `lead_scoring.py` model is not executed. This Actor does not call the `access.py` ladder yet, so a Maps block stops the run with no proxy retry.

### new-business

Imports `scripts/lead_automation/new_business_pipeline.py`, `new_business_dedupe.py`, `new_business_website.py`, and `new_business_email.py`. A state is queried only after its feed is verified in `scripts/lead_automation/new_business_sources.json`. Feeds verified 2026-10-05: NY `data.ny.gov/resource/n9v6-gdp6.json`, PA `data.pa.gov/resource/xvd7-5r2c.json`, CO `data.colorado.gov/resource/4ykn-tg5h.json` (Good Standing via `extra_where`). The 3–7 second delay covers the SODA Crawl-delay of 1. Once `maxSpendUsd` cannot cover the next event, later entities are saved without a charge and their enrichment fields are omitted. `headless` is kept for the shared contract and has no effect.

### permits

Reads `sources.json` in the Actor folder and reuses `new_business_sources/open_data.py` and `http_table.py` for Socrata URLs and HTML tables. Permit field mapping lives in the Actor because the shared adapters emit formation records. Query styles `http_table` and `arcgis` are supported for feeds verified the same way. Checked 2026-10-26: Chicago `ydr8-5enu`, Seattle `76t5-zqzr`, Austin `3syk-w9eu`, Los Angeles `pi9x-tg5x`. Not included: NYC DOB `ipu4-2q9a` (no `issuance_date` rows after 2025-01-01), San Francisco `i98e-djpj` (404), and Los Angeles `nbyu-2ha9` (403). Unit tests: `python -m unittest unittests.apify_scripts.test_permits`.

### contractor-license

Issue #155. California posts the CSLB Check a License form by number or name and reads the detail page. A trade-only search streams the master file, capped at 80 MB. CSLB `robots.txt` returned 404 while packaging. Arizona's robots response was a Cloudflare challenge, returned as `captcha`. Arizona's current-contractor CSV has no bond or insurance columns, and qualifying-party names are not copied.

### zillow

Runs `scripts/zillow_automation/zillow_agents.py` on Apify. On the platform (`APIFY_IS_AT_HOME=1`) search and listing pages are Chrome-impersonation HTTP GETs through `Actor.create_proxy_configuration()`, residential group and US exit by default, with the ZIP resolved to a Zillow region before the first request so the exit city does not replace the search. The first session is reused; a block retries once on a second session. A local run uses no proxy and writes dated files such as `scripts/zillow_automation/zillow_agents_2026-10-24_08002.csv`. Script Manager entry `zillow-apify` starts the published Actor with `APIFY_TOKEN` and `APIFY_USER_ID` (set `ZILLOW_ACTOR_ID` when the id is not `<APIFY_USER_ID>~zillow-agents`) and downloads the dataset:

```bash
python -m scripts.script_manager run zillow-apify -- --zip-codes 08002 --max-listings 100 --max-agents 50
gh workflow run "Script Manager" -f script=zillow-apify -f args="--zip-codes 08002 --max-listings 100 --max-agents 50" -f confirm=true
```

Fixtures live in `unittests/zillow_automation/fixtures/`; update them with the parser. Tests: `python -m unittest unittests.zillow_automation.test_zillow_agents unittests.apify_scripts.test_zillow_actor`.

### HTTP-only Actors: app-reviews, ats-jobs, gov-contracts, shopify-store

These drop `headless`, `maxProxyCostUsd`, `allowCaptcha`, `proxyConfiguration`, and `proxyGroups` from the template input and keep only `maxSpendUsd`. They read public JSON over plain HTTP and stop on a block instead of spending to get past it, the same path `contractor-license` takes. The Dockerfile uses `apify/actor-python:3.12`, leaves `WORKDIR` at `/usr/src/app`, sets `CJM_REPO_ROOT=/usr/src/app/platform_bundle`, and has no `xvfb-entrypoint.sh`. Prices under one cent would round to zero in the shared cent `SpendLedger`, so each one subclasses it in micro-dollars with the same `can()` / `commit()` contract: `ReviewLedger`, `JobLedger`, `LeadLedger`, and the shopify-store ledger. None of them declares `proxy` or `captcha`, because an undeclared event is priced at $1 in the Docker smoke.

- **app-reviews:** $0.001 is the top of an unverified $0.0005–0.001 range; Store comps were not confirmed. Google Play stays deferred because Play reviews load through a batchexecute session with no stable public document to fixture-test.
- **ats-jobs:** $0.002 is a placeholder pending a pricing decision. Store comps read 2026-11-02: fantastic-jobs career-site-job-listing-api "from $4.00 / 1,000", greenhouse-jobs-api "from $1.20 / 1,000", lever-co-jobs-api "from $0.80 / 1,000" (lowest discount tier; undiscounted prices not visible). Endpoint notes from 2026-11-02: the Greenhouse list endpoint accepts `pay_transparency=true` (documented only on the single-job endpoint); Ashby's live response has `id` though the docs omit it; Workable's widget feed is undocumented. Robots that day: Greenhouse disallowed only `/embed/`, Lever allowed `/` with Crawl-delay 1, Workable allowed everything, Ashby answered 401.
- **gov-contracts:** $0.008 was chosen over the brief's $0.01 to stay at $8 per 1,000. `fixtures/INPUT.json` is awards only (NAICS 541512, VA, Q1 2024) so the Docker smoke needs no SAM key; SAM parsing, the missing-key skip, and a SAM block are covered by `unittests/apify_scripts/fixtures/gov_contracts/sam_page.json`. The budget expects exactly two rows and $0.016.
- **shopify-store:** a homepage challenge is recorded on the store row and does not end the run, since stopping there would drop catalogs whose `/products.json` is public. `/meta.json` is not requested. Not on Apify yet: it needs a first `apify push` and an icon before its Store README applies.
