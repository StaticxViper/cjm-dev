# Apify Actors

Playwright scrapers packaged for the Apify Marketplace. Issue #128. Local CLIs stay in place and are the source of truth. Actors under this folder import them.

| Folder | Status | Source CLI |
|--------|--------|------------|
| [`_template/`](_template/) | Copy this for a new Actor | — |
| [`city-data/`](city-data/) | Phase 1 | [`scripts/city_data/`](../city_data/) (issue #99) |
| [`google-business/`](google-business/) | Phase 1 | Maps session in [`scripts/lead_automation/playwright_discovery.py`](../lead_automation/playwright_discovery.py); match rules from issue #127 |

Later folders (not created yet): `amazon/`, `youtube/`, `instagram/`. Each one is a copy of `_template/` after Phase 1 is accepted. Instagram already has a Store Actor we call from `helper_scripts/api_manager`; a first-party listing is a separate decision.

## Create an Actor

1. Copy `_template/` to `scripts/apify-scripts/<name>/`.
2. Rename `name` / `title` / `description` in `.actor/actor.json`.
3. Extend the input and dataset schemas. Keep `headless` and `proxyConfiguration` (the proxy field stays unused).
4. Replace `src/main.py`. Call the existing scraper inside `asyncio.to_thread`. Import it; do not move or rewrite the CLI.
5. Add `COPY` lines to the Dockerfile for the modules you import, and set `CJM_REPO_ROOT=/home/myuser/repo`.
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
5. Leave pricing as a placeholder until a private run shows compute per result. Then pick compute units or pay-per-result.
6. Choose a private listing or a public one. Public Google Business needs the ToS / robots section left intact.
7. Save a sample dataset export and a screenshot with the listing. Update `.actor/CHANGELOG.md`.

## Rules that stay in force

- Playwright only for these Actors. No paid Maps or Places call in `google-business`.
- Respect robots.txt with `scripts/lead_automation/crm_enrich_robots.py` (longest match). Google web search (`/search`) is never requested.
- On a block page, push a `blocked` row and stop. No CAPTCHA solving, proxy rotation, or extra stealth flags. The Maps session already launches Chromium with `--disable-blink-features=AutomationControlled`; do not add more.
- Do not change CLI flags, defaults, or env loading in `scripts/lead_automation/` or `scripts/city_data/`.
