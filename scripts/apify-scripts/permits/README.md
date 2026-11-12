# Building Permits Scraper – Roofing, Solar, Pool & Remodel Leads

**Building Permits Scraper returns recently issued building permits from the Chicago, Seattle, Austin, Los Angeles, New York City, New Orleans, and Cincinnati open-data portals, with address, job value, work description, contractor, and a permit category, for roofing, solar, pool, remodel, deck, and siding contractors who want homeowners with active projects.**

$0.012 per permit ($12 per 1,000) on the free tier, down to $0.008 on paid Apify plans. Empty searches and status rows are free.

## Who is it for?

- **Roofing and exterior contractors** following up on reroof and siding permits in their service area.
- **Solar installers and pool builders** finding properties with new solar or pool permits, and the competitors that pulled them.
- **Remodelers and kitchen and bath companies** reaching homes with renovation, alteration, and addition permits.
- **Exterior-cleaning, gutter, and landscaping companies** marketing to homes that just finished a project.
- **Building-material suppliers and distributors** tracking which contractors pull the most permits.
- **Real estate and construction analysts** measuring permit activity and job value by city.

## What data do you get?

One dataset item per permit.

| Field | Type | What it holds |
|-------|------|---------------|
| `permit_id` | string | The city's permit number |
| `issued_date` | string | Issue date (`YYYY-MM-DD`) |
| `type`, `description` | string | Permit type and work description as published |
| `permit_category` | string | Main category: `solar`, `pool`, `roof`, `siding`, `deck`, `new_construction`, `remodel`, or `other` |
| `permit_categories` | array | Every category the permit matched |
| `value_usd` | number | Reported job value, when published |
| `address`, `city`, `state`, `zip` | string | Site address. Chicago and New Orleans do not publish a ZIP |
| `lat`, `lng` | number | Coordinates, when published. Cincinnati does not publish them |
| `contractor_name`, `contractor_license` | string | Contractor on the permit, when published |
| `owner_name` | string | Owner, only where the city publishes one |
| `source`, `source_url` | string | Feed id and a link to the record |
| `sourceStatus` | string | `found`, `not_found`, `blocked`, `robots_disallowed`, or `error` |
| `ok`, `error`, `scrapedAt` | | Success flag, failure reason, timestamp |

Sample row in the shape of a Chicago roof permit (names and id are masked):

```json
{
  "permit_id": "B-EXAMPLE-1",
  "issued_date": "2026-10-12",
  "type": "PERMIT - RENOVATION - Roof",
  "description": "Tear off and re-roof with architectural shingles",
  "permit_category": "roof",
  "permit_categories": ["roof", "remodel"],
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

### Permit categories

Categories come from whole-word matches in the permit type and description. `permit_category` is the first match in this order, so a pool filed under "NEW CONSTRUCTION" is `pool`.

| Category | Matches |
|----------|---------|
| `solar` | solar, photovoltaic |
| `pool` | pool |
| `roof` | roof, reroof, re-roof, shingle |
| `siding` | siding |
| `deck` | deck |
| `new_construction` | new construction, new building |
| `remodel` | remodel, renovation, alteration, alter, addition, kitchen, bath, bathroom, interior |
| `other` | none of the above |

## Input

```json
{
  "sources": ["chicago_building_permits", "nyc_dob_now_permits"],
  "dateFrom": "2026-10-12",
  "dateTo": "2026-11-11",
  "permitTypes": ["roof", "solar", "pool", "remodel"],
  "minValue": 1000,
  "maxItems": 50,
  "newSinceLastRun": true
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `sources` | every city | `chicago_building_permits`, `seattle_building_permits`, `austin_issued_permits`, `los_angeles_building_permits`, `nyc_dob_now_permits`, `new_orleans_permits`, `cincinnati_building_permits` |
| `dateFrom`, `dateTo` | last 30 days | Issue-date window (`YYYY-MM-DD`) |
| `permitTypes` | all | `roof`, `siding`, `pool`, `deck`, `solar`, `new construction`, `remodel`. Same keywords as the category table |
| `minValue` | 0 | Minimum job value. `0` keeps permits with no published value |
| `maxItems` | 50 (max 200) | Permits returned per run, after filters, de-duplication, and `newSinceLastRun` |
| `newSinceLastRun` | false | Skip permits an earlier run already charged you for |
| `stateStoreName` | `permits-state` | Named key-value store that remembers those permits. Use one name per saved task |
| `maxRequests` | 24 (max 80) | Feed requests per run |
| `delaySeconds` | 2 | Pause between requests |
| `maxSpendUsd` | 5 (max 100) | Hard cap on what one run can charge |
| `maxProxyCostUsd`, `allowCaptcha`, `proxyConfiguration` | 0, false, off | Block handling, see below |

## How much does it cost?

Pay per event. You pay only for permits returned.

| Event | Free tier | Bronze | Silver | Gold and up |
|-------|-----------|--------|--------|-------------|
| Permit row (`permit`) | $0.012 | $0.010 | $0.009 | $0.008 |

- **100 permits:** 100 × $0.012 = **$1.20**
- **1,000 permits:** 1,000 × $0.012 = **$12.00** (as low as $8.00 on Gold)

`not_found`, `blocked`, `robots_disallowed`, and `error` rows are free. Permits skipped by `newSinceLastRun` are not returned and not billed. Apify adds its small per-run start event. `maxSpendUsd` uses a conservative $0.05 per permit, so it stops billing early rather than late.

## Limits and data source

| City | Portal | Job value field | Contractor | Owner |
|------|--------|-----------------|------------|-------|
| Chicago, IL | data.cityofchicago.org | reported cost | yes | when a contact is typed as owner |
| Seattle, WA | data.seattle.gov | estimated project cost | yes | no |
| Austin, TX | data.austintexas.gov | total job valuation | yes | no |
| Los Angeles, CA | data.lacity.org | valuation | no | no |
| New York City, NY | data.cityofnewyork.us (DOB NOW) | estimated job costs | applicant business and license | owner business name |
| New Orleans, LA | data.nola.gov | construction value | yes | yes |
| Cincinnati, OH | data.cincinnati-oh.gov | estimated project cost | yes | no |

- **Coverage:** these seven cities only. A city is added after a live read confirms its columns and recent rows. San Francisco and Dallas were checked and are not included: San Francisco publishes no usable permit dataset, and Dallas stores issue dates as text that cannot be filtered.
- **New York City:** initial permits only, so renewals are not returned as new leads.
- **Source:** official city open-data (Socrata) APIs over plain HTTP. No browser and no login.
- **Dedupe:** one row per city and permit id.
- **Pacing:** 2 seconds between requests with jitter. robots.txt is checked for every host, and the portals publish `/resource/` as allowed.
- **Blocks:** requests are direct. By default a block saves one `blocked` row and the run stops cleanly. Setting `maxProxyCostUsd` above 0 allows one retry through Apify Proxy; there is no proxy rotation. No CAPTCHA solver ships with this Actor.
- **Public data:** these are public open-data extracts for research. They are not certified permit records and do not replace the city's permit file.

## FAQ

### How do I find new roofing permits in Chicago?

Set `sources` to `["chicago_building_permits"]`, `permitTypes` to `["roof"]`, and the date window you want. Each row has the address, job value, and the contractor who pulled the permit.

### How do I get only permits I have not seen before?

Turn on `newSinceLastRun` and schedule the Actor. Each run skips permits an earlier run charged you for. Give each saved task its own `stateStoreName` to keep separate feeds apart. If that store cannot be read, the run returns one free `error` row instead of re-sending old permits.

### Which cities are covered?

Chicago, Seattle, Austin, Los Angeles, New York City, New Orleans, and Cincinnati. Leave `sources` empty to search all seven.

### Do permits include the homeowner's name?

Only where the city publishes it. Chicago lists an owner when a permit contact is marked as the owner, New Orleans publishes an owner, and New York City publishes the owner's business name. Seattle, Austin, Los Angeles, and Cincinnati do not publish owner names.

### Can I filter by job value?

Yes. `minValue` drops permits below the amount. Leave it at `0` to also keep permits that have no published value.

### What counts as a result?

One permit row. A search that finds nothing is free.

### Does this need a proxy?

No. City open-data APIs answer direct. A proxy retry happens only if you set `maxProxyCostUsd` above 0 and a request was actually blocked.

## Integrations and output

- **Dataset:** one row per permit plus status rows. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has `found`, `billedPermits`, `mergedDuplicates`, `skippedSeen`, `spendUsd`, and a report per city (`id`, `status`, `fetched`, `kept`).
- **Automation:** schedule it weekly with `newSinceLastRun` for a rolling permit feed, or connect it to Make, Zapier, n8n, a CRM, or Google Sheets.

## Related actors

- [Contractor License Lookup](https://apify.com/staticxviper/contractor-license): verify the license of a contractor on a permit.
- [Home Services Leads](https://apify.com/staticxviper/home-services): local contractors by niche and area, with emails and scores.
- [Zillow Real Estate Agent Scraper](https://apify.com/staticxviper/zillow-agents): listing agents by ZIP code.

## Changelog

Release notes are on the **Changelog** tab of this page.
