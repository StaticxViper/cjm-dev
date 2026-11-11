# New Business Leads – Newly Registered LLCs & Corporations

**New Business Leads returns newly registered LLCs and corporations from official New York, Pennsylvania, and Colorado state open-data feeds, filtered by formation date, county, and entity type, for B2B sellers who want to reach businesses in their first weeks.**

$0.008 per returned business ($8 per 1,000) on the free tier, lower on paid Apify plans. Optional website and email enrichment is billed only when a value is found.

## Who is it for?

- **Insurance agents, accountants, and bookkeepers** who sell to brand-new LLCs.
- **Business banking, payroll, and merchant-services reps** working a territory by county.
- **Web designers, sign shops, and marketing agencies** reaching new companies before they choose a vendor.
- **Registered-agent and compliance services** monitoring new filings.
- **Researchers and journalists** tracking business formation by state and county.

## What data do you get?

One dataset item per business.

| Field | Type | What it holds |
|-------|------|---------------|
| `entity_id` | string | The state's entity or DOS id, liquor application or license number, or NYC restaurant id (CAMIS) |
| `name` | string | Registered business name, or the trade name on a license or inspection |
| `trigger` | string | `entity_formation`, `liquor_license`, or `restaurant_inspection` |
| `trigger_date` | string | Formation, license received or issue, or inspection date (`YYYY-MM-DD`) |
| `formation_date` | string | Date the entity was formed. Blank on license and inspection rows |
| `type` | string | Entity type as filed, such as `DOMESTIC LIMITED LIABILITY COMPANY`, or the license or inspection type |
| `status` | string | Entity status, liquor application status (`Under Review`, `Conditionally Approved`), or inspection grade |
| `address`, `county`, `state` | string | Location fields the feed publishes |
| `website`, `email` | string | Filled by enrichment when found |
| `enrichmentFound` | boolean | `true` when a website or email was verified |
| `source_url` | string | Link to the record in the state's open-data API |
| `sourceStatus` | string | `found`, `not_found`, `unsupported`, `blocked`, `robots_disallowed`, or `error` |
| `ok`, `error`, `scrapedAt` | | Success flag, failure reason, timestamp |

Sample New York row (the id and name are masked):

```json
{
  "entity_id": "EXAMPLE7931947",
  "name": "Example Reid LLC",
  "trigger": "entity_formation",
  "trigger_date": "2026-09-14",
  "formation_date": "2026-09-14",
  "type": "DOMESTIC LIMITED LIABILITY COMPANY",
  "status": "active",
  "address": "NY",
  "county": "Montgomery",
  "state": "NY",
  "website": "",
  "email": "",
  "source_url": "https://data.ny.gov/resource/n9v6-gdp6.json?dos_id=EXAMPLE7931947",
  "sourceStatus": "found",
  "ok": true,
  "error": "",
  "scrapedAt": "2026-10-24T21:00:00+00:00",
  "enrichmentFound": false
}
```

New York's extract often leaves the street address blank, so `county` is the reliable location field for NY.

## New-opening triggers

Set `triggers` to add businesses that are about to open, not just newly filed:

- **`liquor_license`:** New York State Liquor Authority pending applications (restaurants, bars, grocery and liquor stores) and Colorado recently approved liquor licenses. Wholesalers, importers, permits, and tobacco licenses are left out.
- **`restaurant_inspection`:** New York City pre-permit initial inspections, the first health inspection of a new restaurant.

Trigger rows have the same shape and price as entity rows. Each row's `trigger` field names the feed it came from. When `maxResults` cuts a run short, rows are taken from each trigger in turn.

## Input

```json
{
  "states": ["NY", "PA"],
  "triggers": ["entity_formation", "liquor_license"],
  "formedSince": "2026-09-01",
  "counties": [],
  "entityTypes": ["LLC"],
  "enrichWebsite": false,
  "maxResults": 50
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `states` | required | `NY`, `PA`, `CO`. Other states return a free `unsupported` row |
| `triggers` | `["entity_formation"]` | Add `liquor_license` (NY, CO) or `restaurant_inspection` (NYC). A state with no feed for a trigger returns a free `unsupported` row |
| `formedSince` | 365 days ago | Earliest trigger date (`YYYY-MM-DD`) |
| `counties` | all | Up to 50 county names. NYC boroughs use county names: `Kings`, `New York`, `Queens`, `Bronx`, `Richmond` |
| `entityTypes` | all | Labels like `LLC` or `corporation`, or license types like `Restaurant` |
| `enrichWebsite` | false | Add the website or email the registry already published, and check that website |
| `maxResults` | 50 (max 200) | Entities returned per run, after de-duplication |
| `maxRequests` | 12 (max 40) | Feed requests per run |
| `delaySeconds` | 3 | Pause between requests |
| `maxSpendUsd` | 5 (max 100) | Hard cap on what one run can charge |
| `maxProxyCostUsd`, `allowCaptcha` | 0.5, false | Block handling, see below |

## How much does it cost?

Pay per event.

| Event | When it is charged | Free tier | Gold and up |
|-------|--------------------|-----------|-------------|
| Returned business (`business`) | A formed entity, liquor license, or new-restaurant inspection row is returned | $0.008 | $0.005 |
| Website or email found (`enrichment`) | `enrichWebsite` is on and a website or email is found | $0.01 | $0.01 |

- **100 new LLCs, no enrichment:** 100 × $0.008 = **$0.80**
- **1,000 new LLCs, no enrichment:** 1,000 × $0.008 = **$8.00** (as low as $5.00 on Gold)
- **100 new LLCs with enrichment, 20 found:** $0.80 + 20 × $0.01 = **$1.00**

`not_found`, `unsupported`, `blocked`, `robots_disallowed`, and `error` rows are free. Apify adds its small per-run start event.

## Limits and data source

| State | Source | Notes |
|-------|--------|-------|
| NY | NY Department of State active corporations (data.ny.gov) | Monthly extract of active entities. Not a legal status certificate |
| PA | Pennsylvania registered businesses (data.pa.gov) | No login and no per-record fee |
| CO | Colorado Secretary of State business entities (data.colorado.gov) | Good Standing entities only |
| NY | NY State Liquor Authority pending licenses (data.ny.gov) | `liquor_license`. New applications only, updated daily |
| CO | Colorado recently approved liquor licenses (data.colorado.gov) | `liquor_license`. No county column, and the feed runs about six weeks behind |
| NYC | NYC DOHMH restaurant inspections (data.cityofnewyork.us) | `restaurant_inspection`. Pre-permit initial inspections only |

- **Coverage:** only feeds that were verified as open data. Delaware, Florida, New Jersey, and Texas portals are not requested. Login-walled or challenged portals are never called.
- **Dedupe:** the same state and entity id collapse into one row. A shared name alone does not merge two entities.
- **Enrichment:** reads a website or email the registry row already has, then checks that website if robots.txt allows it. It does not search Google and does not invent a website, so many NY rows stay unenriched.
- **Pacing:** plain HTTP, no browser, 3 seconds between requests with jitter. robots.txt is checked for every host.
- **Blocks:** requests start direct. After a real block the Actor may retry once through an Apify datacenter proxy inside `maxProxyCostUsd`. If it is still blocked, one `blocked` row is saved and the run stops cleanly.
- **Public data:** the rows are public state records. Use contact data in line with the CAN-SPAM Act, TCPA, and your local rules.

## FAQ

### How do I find new LLCs in New York?

Set `states` to `["NY"]`, set `formedSince` to the earliest date you want, and add `entityTypes: ["LLC"]`. Add `counties` to narrow it to your territory.

### How do I find restaurants and bars that are about to open?

Set `states` to `["NY"]` and `triggers` to `["liquor_license", "restaurant_inspection"]`. A liquor application usually comes before opening day. A pre-permit inspection is the city's first check of a new restaurant. For restaurant liquor applications only, run `liquor_license` alone with `entityTypes: ["Restaurant"]`. Inspection rows carry the inspection type, so that filter would drop them.

### Which states are covered?

New York, Pennsylvania, and Colorado today. A state is added only after its open-data feed is verified. Any other state returns a free `unsupported` row.

### How fresh is the data?

As fresh as each state's feed. The New York extract is published monthly. Each row has `formation_date` so you can filter by recency.

### Do I get phone numbers or emails?

The state feeds do not publish phone numbers. With `enrichWebsite` on, the Actor adds a website or email when the registry already lists one and the site can be checked. You pay $0.01 only when one is found.

### What counts as a result?

One returned entity. Empty searches, unsupported states, and blocked requests are free.

### Does this need a proxy?

No. These are public APIs and normally answer direct. A proxy is used only to retry a request that was actually blocked.

## Integrations and output

- **Dataset:** one row per entity plus status rows. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has `found`, `billedBusiness`, `billedEnrichment`, `mergedDuplicates`, `truncated`, and `spendUsd`.
- **Automation:** schedule it weekly for a steady feed of new businesses, or connect it to Make, Zapier, n8n, HubSpot, or Google Sheets.

## Related actors

- [Google Maps Business Leads](https://apify.com/staticxviper/google-business-lead-generation): find a new business's phone, website, and rating on Google Maps.
- [Federal Contract Leads](https://apify.com/staticxviper/gov-contracts): SAM.gov opportunities and USAspending awards by NAICS and state.
- [Home Services Leads](https://apify.com/staticxviper/home-services): local service businesses by niche and area, with emails and scores.

## Changelog

Release notes are on the **Changelog** tab of this page.
