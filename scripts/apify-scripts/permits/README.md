# Building Permits Scraper – Roofing, Solar, Pool & Remodel Leads

Recent building permits from verified city and county open-data portals. Issues #128 and #178. Aimed at contractor and exterior-cleaning leads: roof, solar, pool, remodel, siding, deck, and new construction. Seven metros today, each row tagged with a normalized `permit_category`. Turn on `newSinceLastRun` and a scheduled task becomes a feed of only the permits it has not sold you before.

The Actor reads `sources.json` in this folder and reuses `scripts/lead_automation/new_business_sources/open_data.py` and `http_table.py` for Socrata page URLs and HTML tables. Those modules stay the source of truth for polite HTTP and query strings. Permit field mapping lives in this Actor because the shared adapters emit business-formation records.

Low-volume research. Each feed is requested with a polite delay. The default pause is 2 seconds and jitters upward by up to 2 seconds, which covers the Crawl-delay of 1 on the SODA robots files. There is no browser and no stealth plugin.

Coverage is narrow on purpose. A portal is queried only after its open-data feed is verified in `sources.json`.

## What it does

Each resource was checked with a one- or two-row HTTPS read ordered by its issue date, plus its robots.txt:

| City | Source id | Endpoint | Checked |
|------|-----------|----------|---------|
| Chicago | `chicago_building_permits` | `https://data.cityofchicago.org/resource/ydr8-5enu.json` | 2026-10-26 |
| Seattle | `seattle_building_permits` | `https://data.seattle.gov/resource/76t5-zqzr.json` | 2026-10-26 |
| Austin | `austin_issued_permits` | `https://data.austintexas.gov/resource/3syk-w9eu.json` | 2026-10-26 |
| Los Angeles | `los_angeles_building_permits` | `https://data.lacity.org/resource/pi9x-tg5x.json` | 2026-10-26 |
| New York City | `nyc_dob_now_permits` | `https://data.cityofnewyork.us/resource/rbx6-tga4.json` | 2026-11-11 |
| New Orleans | `new_orleans_permits` | `https://data.nola.gov/resource/rcm3-fn58.json` | 2026-11-11 |
| Cincinnati | `cincinnati_building_permits` | `https://data.cincinnati-oh.gov/resource/uhjb-xac9.json` | 2026-11-11 |

Rows are filtered by `dateFrom` / `dateTo`, optional permit types, and optional `minValue`, then deduped on `(source, permit_id)`. The same permit id from two cities stays two rows. With `newSinceLastRun` on, permits charged by an earlier run are skipped next.

`owner_name` is filled only when that portal publishes an owner. Chicago copies a contact when `contact_N_type` contains "owner", and a contractor when it contains "contractor". Seattle, Austin, and Cincinnati publish a contractor company and no owner column, so `owner_name` is empty. Los Angeles publishes the site address, value, and work description, and does not publish a contractor or an owner. New York City copies DOB's `owner_business_name` (the owner entity; the personal `owner_name` column is not copied) and the applicant business and license as the contractor. New Orleans publishes `owner` and `contractors`. Chicago and New Orleans do not publish a property ZIP, and Cincinnati does not publish coordinates.

New York City is DOB NOW: Build approved permits filtered to `filing_reason = 'Initial Permit'`, so renewals are not sold as new leads. New Orleans mixes building, trade, and pool permits in one feed; `permit_category` and `permitTypes` sort them.

### Permit categories

Every permit row has `permit_category` (one string) and `permit_categories` (every match). Categories come from whole-word matches in the permit type and description:

| Category | Matches |
|----------|---------|
| `solar` | solar, photovoltaic |
| `pool` | pool |
| `roof` | roof, reroof, re-roof, shingle |
| `siding` | siding |
| `deck` | deck |
| `new_construction` | new construction, new building, new single family, new dwelling, new residence |
| `remodel` | remodel, renovation, alteration, alter, addition, kitchen, bath, bathroom, interior |
| `other` | nothing above matched |

`permit_category` is the first match in that table order. Trade words outrank the broad classes because cities file a pool under "NEW CONSTRUCTION" or a reroof under "RENOVATION". So Chicago's `PERMIT - NEW CONSTRUCTION` pool row is `pool` with `permit_categories` `["pool", "new_construction"]`. Matching is whole-word: "additional" is not remodel and "decker" is not deck. Status rows have an empty category and an empty list.

An `http_table` source can be added when a city publishes a plain HTML table and that page has been checked the same way. Query style `arcgis` is supported for a FeatureServer that has been verified the same way. The current catalog is Socrata.

Default behavior on a block: direct HTTP only. A real block (HTTP 401, 403, 429, or a challenge page) pushes one `blocked` row, skips the remaining sources, and the run exits 0. There is no proxy rotation and no CAPTCHA solving by default, and a blocked run emits no `permit` event.

The shared Actor contract still allows an opt-in ladder:

1. Direct HTTP.
2. One Apify Proxy retry after a block, only when `maxProxyCostUsd` is above 0 (default 0). The group comes from the input. An empty group uses datacenter. Residential is used only when the input selects it.
3. A CAPTCHA solve only when that proxy retry is still a challenge, `allowCaptcha` is true, and `maxSpendUsd` covers the solve.

A robots disallow is not retried through a proxy. This package does not ship a third-party solver key, so `allowCaptcha: true` still stops unpaid until a solver is configured.

## Input

`fixtures/INPUT.json`:

```json
{
  "sources": ["chicago_building_permits"],
  "dateFrom": "2026-10-12",
  "dateTo": "2026-11-11",
  "permitTypes": ["roof", "siding", "pool", "deck", "solar", "remodel"],
  "minValue": 1000,
  "newSinceLastRun": false,
  "maxItems": 10,
  "maxRequests": 24,
  "delaySeconds": 2,
  "maxSpendUsd": 5,
  "maxProxyCostUsd": 0,
  "allowCaptcha": false,
  "headless": true,
  "proxyConfiguration": {"useApifyProxy": false}
}
```

Leave `sources` empty to query every verified feed. `dateFrom` defaults to 30 days before the run. `dateTo` defaults to the run date. Both are inclusive and checked again on each row after the city answers. `permitTypes` accepts `roof`, `siding`, `pool`, `deck`, `solar`, `new construction`, and `remodel`, with the same keywords as the category table above. `minValue` of 0 keeps blank job values. A minimum above 0 drops blanks. `maxItems` defaults to 50 and cannot exceed 200. `maxSpendUsd` defaults to 5 and cannot exceed 100. `maxProxyCostUsd` defaults to 0 (no proxy retry) and is clamped to the spend cap. `allowCaptcha` defaults to false. `headless` is kept for the shared Actor contract and has no effect.

`newSinceLastRun` (default false) skips permits charged by an earlier run. Seen `source:permit_id` keys and their `firstSeen` time live in the named key-value store `stateStoreName` (default `permits-state`), which persists between runs. Use a different store name per saved task to keep feeds apart. Skipped permits are not pushed, not billed, and do not count toward `maxItems`. Only permits that were pushed and charged are recorded, so a permit held back by `maxItems` or saved unbilled after `maxSpendUsd` is still new next run. The store keeps up to 200,000 keys and drops the oldest first. Every run records charged permits, so turning the flag on later already knows what earlier runs sold.

## Output

One dataset item per permit, plus a status row when a source is blocked, disallowed, empty, or the input is wrong. Key-value `SUMMARY` records found, billedPermits, proxyCharges, captchaCharges, mergedDuplicates, skippedSeen, newSinceLastRun, stateStore, stateKeys, spendUsd, and one object per source (`id`, `status`, `fetched`, `kept`, `duplicates`, `skippedSeen`). The run log writes that same per-source line.

```json
{
  "permit_id": "B-EXAMPLE-1",
  "issued_date": "2026-10-12",
  "type": "PERMIT - RENOVATION - Roof",
  "permit_category": "roof",
  "permit_categories": ["roof", "remodel"],
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

- Verified feeds today are Chicago, Seattle, Austin, Los Angeles, New York City, New Orleans, and Cincinnati. Schemas differ. A city is not added until a live read confirms the columns and recent rows.
- The older NYC DOB permit-issuance resource `ipu4-2q9a` had no rows with `issuance_date` after 2025-01-01 on 2026-10-26, so NYC uses DOB NOW `rbx6-tga4`. San Francisco resource `i98e-djpj` returned 404 and a 2026-11-11 Socrata catalog search on data.sfgov.org returned no permit dataset. Dallas `e7gq-4sah` stores `issued_date` as text like `01/01/18`, so the date window cannot be sent to the city; it is not used. New Orleans `nbcf-m6c2` stopped updating in 2025-08. Los Angeles resource `nbyu-2ha9` returned 403; `pi9x-tg5x` is the one this Actor calls.
- Chicago job value is `reported_cost`. Austin is `total_job_valuation`. Los Angeles is `valuation`. Seattle is `estprojectcost`. New York City is `estimated_job_costs`. New Orleans is `constrval`. Cincinnati is `estprojectcostdec`. A blank value is kept only when `minValue` is 0.
- Cincinnati has no free-text scope; its description repeats the permit type, so categories there come from the type alone.
- `maxItems` applies after the date, type, and value filters, dedupe, and `newSinceLastRun`. `truncated` in `SUMMARY` is true when that cap stopped the run. Permit charges never exceed `maxItems`.
- Once `maxSpendUsd` cannot cover the next permit event, later permits are saved without a success charge.
- Empty, failed, blocked, and robots runs do not emit `permit`.

## Robots and terms

robots.txt is fetched for each host and evaluated with `scripts/lead_automation/crm_enrich_robots.py` (longest match, `User-agent: *`). The verified SODA feeds allow `/resource/` and publish Crawl-delay 1. A shorter `Disallow` on browse, catalog, `/api/odata/`, and `/api/collocate*` URLs does not hide `/resource/`. A disallowed feed is not fetched and is not retried through a proxy.

Terms noted when the feeds were verified (2026-10-26 and 2026-11-11):

- All seven cities publish these extracts on their Socrata open-data portals. The rows are public data for research. They are not certified permit records and they are not a substitute for the city's permit file.

## Pricing

Pay per event, success only. Store tiers from `.actor/pay_per_event.json`:

| Event | FREE | BRONZE | SILVER | GOLD | PLATINUM | DIAMOND | When it is charged |
|-------|------|--------|--------|------|----------|---------|--------------------|
| `permit` (primary) | $0.012 | $0.010 | $0.009 | $0.008 | $0.008 | $0.008 | A permit row is pushed |

Only `permit` is a Store event. Empty, not_found, blocked, robots, error, and already-seen rows are free. Dataset items are not a charge event. The platform still applies its start event. Memory default is 1024 MB and the default timeout is 900 seconds.

`maxSpendUsd` is checked against a conservative local schedule in `src/spend.py` (`permit` $0.05, `proxy` $0.01, `captcha` $1.00), not the Store tier, so the cap stops early rather than late. `proxy` and `captcha` are counted only on the opt-in ladder (`maxProxyCostUsd` above 0, or `allowCaptcha` true) and are not priced Store events.

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

`--purge` clears the default stores only. The named `permits-state` store under `storage/key_value_stores/` survives, so a second local run with `newSinceLastRun: true` returns only new permits. Delete that folder to start fresh.

Unit tests read fixtures only:

```bash
python -m unittest unittests.apify_scripts.test_permits
```

Publish with `APIFY_TOKEN` (`apify push`). That token is not `APIFY_API_KEY`. See `scripts/apify-scripts/README.md`.
