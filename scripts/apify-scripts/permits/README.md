# Building Permits Scraper – Roofing, Solar, Pool & Remodel Leads

Recent building permits from verified city and county open-data portals. Issue #128. Aimed at contractor and exterior-cleaning leads: roof, siding, pool, deck, solar, and new construction.

The Actor reads `sources.json` in this folder and reuses `scripts/lead_automation/new_business_sources/open_data.py` and `http_table.py` for Socrata page URLs and HTML tables. Those modules stay the source of truth for polite HTTP and query strings. Permit field mapping lives in this Actor because the shared adapters emit business-formation records.

Low-volume research. Each feed is requested with a polite delay. The default pause is 2 seconds and jitters upward by up to 2 seconds, which covers the Crawl-delay of 1 on the SODA robots files. There is no browser and no stealth plugin.

Coverage is narrow on purpose. A portal is queried only after its open-data feed is verified in `sources.json`.

## What it does

Checked 2026-10-26 with a one-row HTTPS read of each resource:

| City | Source id | Endpoint |
|------|-----------|----------|
| Chicago | `chicago_building_permits` | `https://data.cityofchicago.org/resource/ydr8-5enu.json` |
| Seattle | `seattle_building_permits` | `https://data.seattle.gov/resource/76t5-zqzr.json` |
| Austin | `austin_issued_permits` | `https://data.austintexas.gov/resource/3syk-w9eu.json` |
| Los Angeles | `los_angeles_building_permits` | `https://data.lacity.org/resource/pi9x-tg5x.json` |

Rows are filtered by `dateFrom` / `dateTo`, optional permit types, and optional `minValue`, then deduped on `(source, permit_id)`. The same permit id from two cities stays two rows.

`owner_name` is filled only when that portal publishes an owner. Chicago copies a contact when `contact_N_type` contains "owner", and a contractor when it contains "contractor". Seattle and Austin publish a contractor company and no owner column, so `owner_name` is empty. Los Angeles publishes the site address, value, and work description, and does not publish a contractor or an owner. Chicago does not publish a property ZIP, so `zip` is empty on that feed.

An `http_table` source can be added when a city publishes a plain HTML table and that page has been checked the same way. Query style `arcgis` is supported for a FeatureServer that has been verified the same way. The current catalog is Socrata.

Access ladder, cheapest path first:

1. Direct HTTP.
2. Apify Proxy only after a real block (HTTP 401, 403, 429, or a challenge page). The group comes from the input. An empty group uses datacenter. Residential is used only when the input selects it.
3. A CAPTCHA solve only when that proxy retry is still a challenge, `allowCaptcha` is true, and `maxSpendUsd` covers the solve.

A robots disallow is not retried through a proxy. If the run is still blocked and the proxy budget is gone, or CAPTCHA is off, or no solver is configured, the Actor pushes one `blocked` row and stops. It exits 0. This package does not ship a third-party solver key, so `allowCaptcha: true` still stops unpaid until a solver is configured.

## Input

`fixtures/INPUT.json`:

```json
{
  "sources": ["chicago_building_permits"],
  "dateFrom": "2026-09-26",
  "dateTo": "2026-10-26",
  "permitTypes": ["roof", "siding", "pool", "deck", "solar"],
  "minValue": 1000,
  "maxItems": 25,
  "maxRequests": 24,
  "delaySeconds": 2,
  "maxSpendUsd": 5,
  "maxProxyCostUsd": 0.5,
  "allowCaptcha": false,
  "headless": true,
  "proxyConfiguration": {"useApifyProxy": false}
}
```

Leave `sources` empty to query every verified feed. `dateFrom` defaults to 30 days before the run. `dateTo` defaults to the run date. `permitTypes` accepts `roof`, `siding`, `pool`, `deck`, `solar`, and `new construction`. Roof also matches reroof and shingle. `minValue` of 0 keeps blank job values. A minimum above 0 drops blanks. `maxItems` defaults to 50 and cannot exceed 200. `maxSpendUsd` defaults to 5 and cannot exceed 100. `maxProxyCostUsd` defaults to 0.50 and is clamped to the spend cap. `allowCaptcha` defaults to false. `headless` is kept for the shared Actor contract and has no effect.

## Output

One dataset item per permit, plus a status row when a source is blocked, disallowed, empty, or the input is wrong. Key-value `SUMMARY` records found, billedPermits, proxyCharges, captchaCharges, mergedDuplicates, spendUsd, and one object per source (`id`, `status`, `fetched`, `kept`). The run log writes that same per-source line.

```json
{
  "permit_id": "B-EXAMPLE-1",
  "issued_date": "2026-10-12",
  "type": "PERMIT - RENOVATION - Roof",
  "description": "Tear off and re-roof with architectural shingles",
  "value_usd": 18500,
  "address": "100 N EXAMPLE AVE",
  "city": "Chicago",
  "state": "IL",
  "zip": "",
  "lat": 41.5,
  "lng": -87.5,
  "contractor_name": "Example Roofing Co",
  "contractor_license": "",
  "owner_name": "Example Owner",
  "source": "chicago_building_permits",
  "source_url": "https://data.cityofchicago.org/resource/ydr8-5enu.json?permit_=B-EXAMPLE-1",
  "sourceStatus": "found",
  "ok": true,
  "error": "",
  "scrapedAt": "2026-10-26T21:00:00+00:00"
}
```

| sourceStatus | Meaning | permit event |
|--------------|---------|--------------|
| `found` | A permit was returned | yes, while `maxSpendUsd` still covers it |
| `not_found` | The feed answered and nothing matched | no |
| `blocked` | Direct request was rejected and the run could not continue inside the caps | no |
| `robots_disallowed` | robots.txt disallows the feed | no |
| `error` | The fetch failed, the request cap was hit, or the input was incomplete | no |

## Limitations

- Verified feeds today are Chicago, Seattle, Austin, and Los Angeles. Schemas differ. A city is not added until a live one-row read confirms the columns.
- The NYC DOB permit-issuance resource `ipu4-2q9a` had no rows with `issuance_date` after 2025-01-01 on 2026-10-26, so it is not in the catalog. San Francisco resource `i98e-djpj` returned 404. Los Angeles resource `nbyu-2ha9` returned 403; `pi9x-tg5x` is the one this Actor calls.
- Chicago job value is `reported_cost`. Austin is `total_job_valuation`. Los Angeles is `valuation`. Seattle is `estprojectcost`. A blank value is kept only when `minValue` is 0.
- `maxItems` applies after the date, type, and value filters and after dedupe. `truncated` in `SUMMARY` is true when that cap stopped the run. Permit charges never exceed `maxItems`.
- Once `maxSpendUsd` cannot cover the next permit event, later permits are saved without a success charge.
- Empty, failed, blocked, and robots runs do not emit `permit`.

## Robots and terms

robots.txt is fetched for each host and evaluated with `scripts/lead_automation/crm_enrich_robots.py` (longest match, `User-agent: *`). The verified SODA feeds allow `/resource/` and publish Crawl-delay 1. A shorter `Disallow` on browse and catalog URLs does not hide `/resource/`. A disallowed feed is not fetched and is not retried through a proxy.

Terms noted when the feeds were verified (2026-10-26):

- Chicago, Seattle, Austin, and Los Angeles publish these extracts on their Socrata open-data portals. The rows are public data for research. They are not certified permit records and they are not a substitute for the city's permit file.

## Pricing

Pay per event. Prices are the starting Store rates in `.actor/pay_per_event.json`.

| Event | Price | When it is charged |
|-------|-------|--------------------|
| `permit` (primary) | $0.05 | A permit row is pushed |
| `proxy` | $0.01 | One request was sent through Apify Proxy after a direct block |
| `captcha` | $1.00 | A solver returned a token after the proxy retry was still a challenge |

Direct requests are free. A challenge with `allowCaptcha` false, or with no solver configured, stores a `blocked` row and does not emit `captcha`. A run that pushes no permits does not emit `permit`. Dataset items are not a charge event. The platform still applies its start event. Memory default is 1024 MB and the default timeout is 900 seconds.

Proxy uses the input group, or datacenter when the input leaves the group empty, and only after a block. The proxy password is the platform `APIFY_PROXY_PASSWORD`. It is not logged.

## Categories

Set in the Apify Console, not in `actor.json`. Suggested: Business, Real estate.

## Local run

```bash
cd scripts/apify-scripts/permits
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

Unit tests read fixtures only:

```bash
python -m unittest unittests.apify_scripts.test_permits
```

Publish with `APIFY_TOKEN` (`apify push`). That token is not `APIFY_API_KEY`. See `scripts/apify-scripts/README.md`.
