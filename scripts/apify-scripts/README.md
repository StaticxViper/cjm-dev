# Apify Actors

Playwright scrapers packaged for the Apify Marketplace. Issue #128. Local CLIs stay in place and are the source of truth. Actors under this folder import them.

| Folder | Status | Source CLI |
|--------|--------|------------|
| [`_template/`](_template/) | Copy this for a new Actor | — |
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
5. Add `COPY` lines to the Dockerfile for the modules you import, copy `scripts/apify-scripts/runtime.py` and `scripts/apify-scripts/access.py`, and set `CJM_REPO_ROOT=/home/myuser/repo`. Set `defaultRunOptions.timeoutSecs`.
6. Write the marketplace `README.md` from the template headings.
7. Add unit tests under `unittests/apify_scripts/` for input mapping and dataset shape. No live site calls in those tests.

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

1. `apify login` with `APIFY_TOKEN` (not `APIFY_API_KEY`).
2. In the Actor directory, `apify push`.
3. Run the committed `fixtures/INPUT.json` once on the platform (private build). Confirm dataset rows and key-value `SUMMARY`.
4. Paste the Actor `README.md` into the Store listing. Set categories in the Console (they are not an `actor.json` field). Suggested starting points are in each README.
5. Set the Console pricing model to pay per event using `.actor/pay_per_event.json`. Charge `result` only for a successful city profile or an accepted Maps match. Charge `license` only for a found contractor license. Charge `business` only for a returned entity and `enrichment` only when a website or email is found. Charge `permit` only for a pushed building permit. Charge `proxy` only after a blocked request was retried through Apify Proxy, and `captcha` only when a solver returns a token. Do not enable pay per dataset item.
6. Choose a private listing or a public one. Public Google Business needs the ToS / robots section left intact.
7. Save a sample dataset export and a screenshot with the listing. Update `.actor/CHANGELOG.md`.

## Purpose, inputs, outputs, and secrets

Actors package the local Playwright CLIs for the Apify platform. Input is the Actor `INPUT.json` (`fixtures/INPUT.json` locally). Output is an Apify dataset plus a key-value `SUMMARY`. Local run is `apify run --purge` from the Actor directory, or `python -m src` after copying the fixture into `storage/key_value_stores/default/INPUT.json`. GitHub Actions workflow `ci.yml` runs `pytest unittests/` on every pull request, including `unittests/apify_scripts`. `apify_scripts.yml` is a manual re-run of those actor tests. Publish uses `APIFY_TOKEN`. The Actors themselves do not read `APIFY_API_KEY`. `zillow-apify` is the Script Manager entry that starts the Zillow Actor through the Apify API and downloads the dataset. The other Actors are not Script Manager entries. Longer notes are the sections above.

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
