# New Business Leads – Newly Registered LLCs & Corporations

Recently formed entities from verified Secretary of State and state business open-data feeds. Issue #128. The Actor imports `scripts/lead_automation/new_business_pipeline.py`, `new_business_dedupe.py`, `new_business_website.py`, and `new_business_email.py`. Those CLIs are unchanged.

Low-volume research. Each feed is requested with a polite delay. The default pause is 3 seconds and jitters up to 7, which covers the Crawl-delay of 1 on the SODA robots files.

Coverage is narrow on purpose. A state is queried only after its open-data feed is verified in `scripts/lead_automation/new_business_sources.json`. Portals that require login or a challenge are not called.

## What it does

| State | Source | Endpoint |
|-------|--------|----------|
| NY | NY DOS active corporations | `https://data.ny.gov/resource/n9v6-gdp6.json` |
| PA | Pennsylvania registered businesses | `https://data.pa.gov/resource/xvd7-5r2c.json` |
| CO | Colorado business entities (Good Standing) | `https://data.colorado.gov/resource/4ykn-tg5h.json` |

Rows are filtered by `formedSince`, optional counties, and optional entity types, then deduped with the same `dedupe_new_businesses` rules as the CLI. Same state and entity id collapse. A shared name alone does not merge.

`enrichWebsite` accepts an email the registry already published and, when the row has a website, fetches that site if robots.txt allows it. Google web search (`/search`) is not requested. There is no browser and no stealth plugin.

Access ladder, cheapest path first:

1. Direct HTTP.
2. Apify Proxy datacenter (`groups-DATACENTER`) only after a real block (HTTP 401, 403, 429, or a challenge page).
3. A CAPTCHA solve only when that proxy retry is still a challenge, `allowCaptcha` is true, and `maxSpendUsd` covers the solve.

A robots disallow is not retried through a proxy. If the run is still blocked and the proxy budget is gone, or CAPTCHA is off, or no solver is configured, the Actor pushes one `blocked` row and stops. It exits 0. This package does not ship a third-party solver key, so `allowCaptcha: true` still stops unpaid until a solver is configured.

## Input

`fixtures/INPUT.json`:

```json
{
  "states": ["NY"],
  "counties": [],
  "formedSince": "2026-09-01",
  "entityTypes": [],
  "enrichWebsite": false,
  "maxResults": 50,
  "maxRequests": 12,
  "delaySeconds": 3,
  "maxSpendUsd": 5,
  "maxProxyCostUsd": 0.5,
  "allowCaptcha": false,
  "headless": true
}
```

`states` is required. `formedSince` defaults to 365 days before the run. `entityTypes` accepts labels such as `LLC` (matched to "limited liability company"). `maxResults` defaults to 50 and cannot exceed 200. `maxSpendUsd` defaults to 5 and cannot exceed 100. `maxProxyCostUsd` defaults to 0.50 and is clamped to the spend cap. `allowCaptcha` defaults to false. `headless` is kept for the shared Actor contract and has no effect.

## Output

One dataset item per entity, plus a status row when a state is unsupported, blocked, disallowed, or empty. Key-value `SUMMARY` has found, billedBusiness, billedEnrichment, proxyCharges, captchaCharges, mergedDuplicates, and spendUsd.

```json
{
  "entity_id": "EXAMPLE7931947",
  "name": "Example Reid LLC",
  "formation_date": "2026-09-14",
  "type": "DOMESTIC LIMITED LIABILITY COMPANY",
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

NY location fields are often blank in the DOS extract, so `address` may be only the state. That is the feed, not a geocode. `enrichmentFound` is true only when the enrichment step verified a website or accepted an email.

| sourceStatus | Meaning | business event | enrichment event |
|--------------|---------|----------------|------------------|
| `found` | An entity was returned | yes | only when `enrichmentFound` is true |
| `not_found` | The feed answered and nothing matched | no | no |
| `unsupported` | No verified open-data feed for that state | no | no |
| `blocked` | Direct request was rejected and the run could not continue inside the caps | no | no |
| `robots_disallowed` | robots.txt disallows the feed | no | no |
| `error` | The fetch failed, the request cap was hit, or the input was incomplete | no | no |

## Limitations

- Verified feeds today are NY, PA, and CO. Delaware, Florida, New Jersey, and Texas portals in the source file are not verified open data and are not requested.
- Philadelphia business licenses and Google Maps are not entity-formation feeds and are not queried.
- Colorado results are Good Standing only, because that is the feed's `extra_where`.
- NY addresses are often the service-of-process blank. County is the reliable place field on that extract.
- Enrichment does not invent a website. It only reads a website or email the registry row already has. A New York row with neither stays unenriched.
- `maxResults` applies after dedupe. `truncated` in `SUMMARY` is true when more matches existed than the cap.
- Once `maxSpendUsd` cannot cover the next event, later entities are saved without a success charge. Enrichment fields on those rows are omitted so the add-on is not given away.
- Empty, failed, unsupported, and blocked runs do not emit `business` or `enrichment`.

## Robots and terms

robots.txt is fetched for each host and evaluated with `scripts/lead_automation/crm_enrich_robots.py` (longest match, `User-agent: *`). The verified SODA feeds allow `/resource/` and publish Crawl-delay 1. A shorter `Disallow: /` does not hide `/resource/` when a longer `Allow` exists. Website enrichment uses the same check. A disallowed site is not fetched and is not retried through a proxy.

Terms noted when the feeds were verified (2026-10-05):

- New York: public SODA API. The extract is active entities, monthly, and is not a legal status certificate.
- Pennsylvania: PA Open Data SODA. No login and no per-record fee on this extract.
- Colorado: Colorado Information Marketplace publishes the SOS dataset for public reuse. The query keeps Good Standing rows only.

## Pricing

Pay per event. Prices are the starting Store rates in `.actor/pay_per_event.json`.

| Event | Price | When it is charged |
|-------|-------|--------------------|
| `business` (primary) | $0.05 | A formed entity is returned |
| `enrichment` | $0.03 | `enrichWebsite` found a website or email on that entity |
| `proxy` | $0.01 | One request was sent through Apify Proxy after a direct block |
| `captcha` | $1.00 | A solver returned a token after the proxy retry was still a challenge |

Direct requests are free. A challenge with `allowCaptcha` false, or with no solver configured, stores a `blocked` row and does not emit `captcha`. Dataset items are not a charge event. The platform still applies its start event. Memory default is 1024 MB and the default timeout is 900 seconds.

Proxy uses the datacenter group only, and only after a block. The proxy password is the platform `APIFY_PROXY_PASSWORD`. It is not logged.

## Categories

Set in the Apify Console, not in `actor.json`. Suggested: Business, Other.

## Local run

```bash
cd scripts/apify-scripts/new-business
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

Publish with `APIFY_TOKEN` (`apify push`). That token is not `APIFY_API_KEY`. See `scripts/apify-scripts/README.md`.
