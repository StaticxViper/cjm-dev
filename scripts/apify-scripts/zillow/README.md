# Zillow Listing Agents

Search Zillow by ZIP code, keep each listing, and return the listing agent. Agents are deduped across listings. When an agent is missing an email or a phone, the run looks that contact up on Google, the agent site, and the brokerage site, and stores the page URL and a confidence score.

The scraper is the in-house pipeline in `scripts/zillow_automation`. This Actor runs that same code on Apify. A local run uses the same input and writes the same dated CSV and JSON files.

## What it collects

Each dataset item is one agent:

| Field | Meaning |
|-------|---------|
| `agent_name` | Listing agent name |
| `brokerage` | Brokerage shown on the listing |
| `phone` | Phone from the listing, or from enrichment |
| `email` | Email from the listing, or from enrichment |
| `license` | License number when the page shows one |
| `profile_url` | Zillow profile URL |
| `enrichment_source` | `website` when a missing contact was filled from a public page |
| `enrichment_source_url` | Page the contact came from |
| `confidence` | `100` when name, brokerage, and area agree. `80` when name plus brokerage or area agree. Blank when the match is weaker |
| `listing_addresses` | Addresses for the listings tied to this agent |

A value is stored only when the agent name agrees and the brokerage or the search area also agrees. A weaker match stays blank.

Listings themselves are saved as the key-value record `LISTINGS`. The run summary is `SUMMARY`.

## How to run

From this directory, with the [Apify CLI](https://docs.apify.com/cli) logged in (`APIFY_TOKEN` in the environment, or `apify login`):

```bash
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

`apify run` uses the local Python environment and does not upload `storage/` to the Apify Console. Publish with:

```bash
apify push
```

Run the build from the Apify Console with `zip_codes`, `max_listings`, and `max_agents`. The sample input is `fixtures/INPUT.json`.

From the repo, Script Manager script `zillow-apify` starts the published Actor through the Apify API and downloads the dataset. It reads `APIFY_TOKEN` and `APIFY_USER_ID`. Set `ZILLOW_ACTOR_ID` when the id is not `<APIFY_USER_ID>~zillow-agents`.

```bash
python -m scripts.script_manager run zillow-apify -- --zip-codes 08002 --max-listings 100 --max-agents 50
```

The universal Script Manager action accepts that script name. Pass `confirm=true` because the run spends Apify credit:

```bash
gh workflow run "Script Manager" -f script=zillow-apify -f args="--zip-codes 08002 --max-listings 100 --max-agents 50" -f confirm=true
```

## Input

```json
{
  "zip_codes": ["08002"],
  "max_listings": 100,
  "max_agents": 50
}
```

| Field | Default | Meaning |
|-------|---------|---------|
| `zip_codes` | required | ZIP codes to search |
| `max_listings` | `100` | Total listings across every ZIP |
| `max_agents` | `50` | Total unique agents to return |

The Advanced section holds listing status (`forSaleByAgent`, `forSaleByOwner`, `forRent`, `sold`), `priceMin`, `priceMax`, `enrich`, `headless`, and `proxyConfiguration`. Agent listings are on by default. Enrichment is on by default. The proxy group defaults to residential.

`max_listings` and `max_agents` stop the run. A later page is not requested once either cap is reached. Agents past `max_agents` are dropped before enrichment.

## Output

One dataset item per agent, pushed to the default dataset.

Key-value store:

| Key | Contents |
|-----|----------|
| `LISTINGS` | Listings collected on this run, with the run counts |
| `SUMMARY` | `listings_found`, `agents_found`, `agents_enriched`, `blocked_zips` |
| `CHECKPOINT` | Search position, pending listing URLs, and agents already kept. A migrated or restarted run resumes from this record |

`blocked_zips` lists ZIP codes whose search page was a block or captcha. That ZIP is skipped and the next ZIP still runs.

A local run also writes dated files next to the pipeline, for example `scripts/zillow_automation/zillow_agents_2026-10-24_08002.csv`, plus the matching listings CSV and the JSON pair. `zillow-apify` writes those same names after it downloads the dataset.

## Proxy

On Apify (`APIFY_IS_AT_HOME=1`) every Zillow browser request uses `Actor.create_proxy_configuration()`. The default group is `RESIDENTIAL`. Another group in `proxyConfiguration.apifyProxyGroups` replaces it. The session id stays on one residential IP for the run.

A local run, including `apify run` on a laptop, leaves `APIFY_IS_AT_HOME` unset. Chromium then starts with no proxy, and the dated files are written on disk.

Images, fonts, and media are blocked. The existing per-host pause (about 2–4.5 seconds), the navigation timeout, and the retry with backoff stay in place. A press-and-hold or "are you a robot" page is stored as blocked for that ZIP. The Actor does not solve captchas and does not switch to an unblocker group on its own.

## Cost

Residential proxy traffic is billed by Apify per gigabyte transferred. Blocking images, fonts, and media is what keeps that transfer down. Current proxy prices are on [Apify pricing](https://apify.com/pricing).

Compute is a Chromium run. The default is 4096 MB with an 8 hour timeout. A 100-listing run is paced at a few seconds per page, so it usually finishes well inside that window. Enrichment adds Google and site visits for agents that are still missing a phone or an email.

Pay per event, when you enable it from `.actor/pay_per_event.json`, charges `result` ($0.05) for an agent row that has a name. A blocked ZIP adds no agent row. Proxy gigabytes are the platform proxy bill. There is no captcha charge.

## Limits

Zillow's markup changes. Parsers prefer the embedded listing JSON, then the visible fields. Update the fixtures in `unittests/zillow_automation/fixtures/` together with the parser.

A block ends that ZIP for this run. The checkpoint lets a restarted run continue the ZIPs that were still in progress.

Tests use saved HTML only:

```bash
python -m unittest unittests.zillow_automation.test_zillow_agents unittests.apify_scripts.test_zillow_actor
```

Results can include names, phone numbers, and email addresses from public listing pages. Store them only when you have a lawful reason to do so.
