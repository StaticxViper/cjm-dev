# Zillow agent pipeline

**Source:** `scripts/zillow_automation/zillow_agents.py`

## Purpose

Searches Zillow for listings in one or more areas, saves each listing's address and listing agent, and fills a missing email or phone from Google and public agent or brokerage pages.

This is the in-house replacement for the paid Apify ZIP actor used by [property_listing_gen.md](property_listing_gen.md). The same pipeline is packaged as the Zillow agents Actor under [scripts/apify-scripts/zillow](../../scripts/apify-scripts/zillow/). The local script still runs on this machine. The Actor runs on Apify.

## Prerequisites

- Python 3.12+
- Playwright Chromium: `python -m playwright install chromium`
- No API key

Run it from the script manager so the working directory and `PYTHONPATH` are set:

```bash
python -m scripts.script_manager run zillow-agents -- --zip-codes 08002 --results-limit 25
```

Or from the script folder:

```bash
cd scripts/zillow_automation
python zillow_agents.py --input search_settings.json
```

## Inputs

`--input` is a JSON object. [search_settings.json](../../scripts/zillow_automation/search_settings.json) already has the ZIP and price fields this script reads. CLI flags override the file.

| Field | Meaning |
|-------|---------|
| `zipCodes` | ZIP codes. A string or a list. |
| `areas` | Cities, counties, or other area text. Use this, `zipCodes`, or both. |
| `priceMin`, `priceMax` | Listing price bounds. |
| `bedsMin`, `bathsMin` | Minimum beds and baths. |
| `homeTypes` | `house`, `condo`, `townhouse`, `multi`, `manufactured`, `land`, `apartment`. |
| `daysOnZillow` | Maximum days listed. Passed through as Zillow's `doz` value. |
| `forSaleByAgent`, `forSaleByOwner`, `forRent`, `sold` | Listing status filters. Defaults match `search_settings.json`: agent listings on, the others off. |
| `resultsLimit` | Maximum listings kept per area. Default 100. `0` means no cap. |

At least one ZIP or area is required.

```bash
python zillow_agents.py --zip-codes 08002 08057 --price-min 150000 --beds-min 3 --results-limit 50
python zillow_agents.py --areas "Cherry Hill, NJ" "Camden County, NJ"
```

## What it collects

From each listing: full address, price, status, beds, baths, square footage, listing URL, and listing id (`zpid`).

From the listing agent: name, brokerage, phone, email, license number, and profile URL. Blank when the page does not show them.

Listings dedupe by listing id, then by normalized address. Agents dedupe by normalized name plus brokerage. One agent keeps every listing address and id.

A seen index (`zillow_seen.json`) remembers listing ids and addresses across runs. A later run does not fetch those listings again. A new listing for an agent already in the seen index is still saved.

## Enrichment

Agents missing an email or a phone are looked up on Google (name, brokerage, and area), then on the agent site, a brokerage page, and at most one directory page.

A value is stored only when the agent name agrees and the brokerage or the area also agrees:

| Score | Requirement |
|-------|-------------|
| 100 | Name, brokerage, and area all agree |
| 80 | Name, plus brokerage or area |
| blank | Anything weaker. The field stays empty. |

`enrichment_source` is `website` and `enrichment_source_url` is the page the value came from. Lookups are cached in `zillow_agent_enrich_cache.json` for 30 days, keyed by name, brokerage, and area.

`--no-enrich` skips this step. A Google block stops further Google searches and still writes the listings already collected.

## Outputs

Files land in `--output-dir` (default `scripts/zillow_automation/`):

| File | Contents |
|------|----------|
| `zillow_agents_YYYY-MM-DD_<area>.json` and `.csv` | One agent: name, brokerage, phone, email, license, profile URL, enrichment source, source URL, confidence, listing addresses, listing ids. JSON also has a `run` object. |
| `zillow_listings_YYYY-MM-DD_<area>.json` and `.csv` | One listing per row. |

`<area>` is the single ZIP or area slug. Two or three areas use the first and last slug (`08002_08057`). More than three use a count (`4areas`).

The `run` object counts listings found, duplicates skipped, agents found, agents enriched, blocked pages, areas completed, and areas blocked. The same line is logged at the end.

CSV listing addresses and listing ids are joined with `; `.

## Resume

A checkpoint is written after each search page and each batch of listing pages. The default file is `zillow_agents_checkpoint.json`. The same criteria resume on the next run. `--fresh` ignores the checkpoint for that criteria. A checkpoint for different criteria is left in place; this run uses a sibling file named with the criteria hash.

Finished areas are not searched again. An area that hit a block is tried again on a later run. Pages that failed after retries stay unfinished so the next run can continue.

The script manager timeout for this script is 8 hours. A multi-ZIP run can still be stopped and resumed.

## Blocks and pacing

Images, fonts, and media are not downloaded. Listing pages use a small pool (`--concurrency`, default 2). Each host waits about 2–4.5 seconds between requests. Zillow's cap is high enough for a long run. Other hosts stop after 30 requests. Navigation timeout is 30 seconds, with two retries and backoff for timeouts and server errors.

A captcha or block page stops that area and increments `blocked_pages`. The run does not solve captchas, rotate proxies, change identities, or hide automation. Google's own block page stops enrichment searches the same way.

## Limits

- Zillow's markup changes. Parsers prefer embedded listing JSON, then visible fields. When a page no longer matches, update the fixtures in `unittests/zillow_automation/fixtures/` and the parser together.
- A block ends that area. There is no bypass.
- `resultsLimit` is per area. Thousands of listings across many ZIPs depend on the checkpoint.
- Enrichment will not guess. A weak name match stays blank.
- CRM and Property Portal upload is not part of this script.
- Tests use saved HTML only. Do not point CI at live Zillow or Google.

```bash
python -m unittest unittests.zillow_automation.test_zillow_agents unittests.apify_scripts.test_zillow_actor
```

## Apify Actor

The Actor is `scripts/apify-scripts/zillow`. On Apify the only required input is `zip_codes`. `max_listings` defaults to 100 across every ZIP. `max_agents` defaults to 50 unique agents. Listing status, price range, enrichment, and the proxy group sit in the Advanced section.

Platform runs send Zillow traffic through Apify Proxy (`Actor.create_proxy_configuration`, residential unless the input picks another group). A local run of the same input connects directly and still writes `zillow_agents_YYYY-MM-DD_<area>.csv` and the matching JSON files. A block or captcha page is recorded on that ZIP and the run continues. The Actor does not solve captchas.

Deploy from the Actor directory with `apify push`. The full input, output, and cost notes are in [scripts/apify-scripts/zillow/README.md](../../scripts/apify-scripts/zillow/README.md).

Script Manager name `zillow-apify` starts that Actor through the Apify API with `APIFY_TOKEN` and `APIFY_USER_ID`, then downloads the dataset into the same dated files. Set `ZILLOW_ACTOR_ID` when the Actor id is not `<APIFY_USER_ID>~zillow-agents`. The universal action already accepts any registered script:

```bash
gh workflow run "Script Manager" --ref <branch> -f script=zillow-apify -f args="--zip-codes 08002 --max-listings 100 --max-agents 50" -f confirm=true
```

`confirm=true` is required because the run spends Apify credit. Script Manager is already a `workflow_dispatch` workflow. Pick this branch as the ref until the registry entry is on the default branch.
