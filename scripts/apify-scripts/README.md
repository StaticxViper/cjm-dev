# Apify Actors

Playwright scrapers packaged for the Apify Marketplace. Issue #128. Local CLIs stay in place and are the source of truth. Actors under this folder import them.

| Folder | Status | Source CLI |
|--------|--------|------------|
| [`_template/`](_template/) | Copy this for a new Actor | — |
| [`city-data/`](city-data/) | Phase 1 | [`scripts/city_data/`](../city_data/) (issue #99) |
| [`google-business/`](google-business/) | Phase 1 | Maps session in [`scripts/lead_automation/playwright_discovery.py`](../lead_automation/playwright_discovery.py); match rules from issue #127 |
| [`contractor-license/`](contractor-license/) | Public records | CA CSLB open CSV. AZ, NJ, and PA adapters stop on a challenge or a closed portal. Issue #155. |

Later folders (not created yet): `amazon/`, `youtube/`, `instagram/`. Each one is a copy of `_template/` after Phase 1 is accepted. Instagram already has a Store Actor we call from `helper_scripts/api_manager`; a first-party listing is a separate decision.

## Create an Actor

1. Copy `_template/` to `scripts/apify-scripts/<name>/`.
2. Rename `name` / `title` / `description` in `.actor/actor.json`.
3. Extend the input and dataset schemas. Keep `headless`. Add a proxy field when the target needs one. Declare dataset fields for nested objects and add a Detail view next to Overview. Use `editor: "select"` when a field is a list of known values.
4. Replace `src/main.py`. Call the existing scraper inside `asyncio.to_thread`. Import it; do not move or rewrite the CLI. `src/runtime.py` re-exports `scripts/apify-scripts/runtime.py`.
5. Add `COPY` lines to the Dockerfile for the modules you import, copy `scripts/apify-scripts/runtime.py`, and set `CJM_REPO_ROOT=/home/myuser/repo`. Set `defaultRunOptions.timeoutSecs`.
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
5. Set the Console pricing model to pay per event using `.actor/pay_per_event.json`. Charge `result` only for a successful city profile or an accepted Maps match. Charge `license` only for a found contractor license. Do not enable pay per dataset item.
6. Choose a private listing or a public one. Public Google Business needs the ToS / robots section left intact.
7. Save a sample dataset export and a screenshot with the listing. Update `.actor/CHANGELOG.md`.

## Purpose, inputs, outputs, and secrets

Actors package the local Playwright CLIs for the Apify platform. Input is the Actor `INPUT.json` (`fixtures/INPUT.json` locally). Output is an Apify dataset plus a key-value `SUMMARY`. Local run is `apify run --purge` from the Actor directory, or `python -m src` after copying the fixture into `storage/key_value_stores/default/INPUT.json`. These Actors are not Script Manager entries. GitHub Actions workflow `ci.yml` runs `pytest unittests/` on every pull request, including `unittests/apify_scripts`. `apify_scripts.yml` is a manual re-run of those actor tests. Publish uses `APIFY_TOKEN`. The Actors themselves do not read `APIFY_API_KEY`. Longer notes are the sections above.

## Rules that stay in force

- Playwright only for city-data and google-business. No paid Maps or Places call in `google-business`. `contractor-license` is HTTP open data: it does not launch Chromium, rotate proxies, or solve CAPTCHAs.
- Respect robots.txt with `scripts/lead_automation/crm_enrich_robots.py` (longest match). Google web search (`/search`) is never requested.
- On a block page, current Actors push a `blocked` row and stop. Proxy rotation and CAPTCHA solving may be used when a target requires them. Spend caps and billing details can land in a follow-up. The Maps session launches Chromium with `--disable-blink-features=AutomationControlled`.
- Do not change CLI flags, defaults, or env loading in `scripts/lead_automation/` or `scripts/city_data/`.
