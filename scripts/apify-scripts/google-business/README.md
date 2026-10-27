# Google Maps Business Match

Low-volume Google Maps lookup for a business name plus a US state. The Actor searches `https://www.google.com/maps/search/`, opens place pages, and scores each listing with the same name and location rules as issue #127. A row is a `match` only when that scorer would accept it. The first Maps card is never used as a fallback.

This is not the Google Places API. That API is a separate paid product and this Actor does not call it.

## What it does

Each query becomes one dataset item:

| `decision` | Meaning |
|------------|---------|
| `match` | Score at or above `minConfidence` (default 80) and no hard reject |
| `low_confidence` | Score at or above `lowConfidenceFloor` (default 60) and below the minimum |
| `no_match` | Hard reject, weak score, or no listing |
| `blocked` | Google showed a block page. Later queries are not run |
| `error` | Input, robots, or unexpected failure |

`hardRejects` can include `brand_token_missing`, `city_mismatch`, `distinctive_token_missing`, `state_mismatch`, `county_mismatch`, `address_mismatch`, `area_code_state_mismatch`, `permanently_closed`, and `website_is_directory`. Legal suffixes such as LLC are stripped before the name comparison. State on the query is required.

A different brand is not returned as the candidate. Retail words (`food`, `market`, `store`, `shop`, `grocery`) do not count as the brand, and every remaining brand token has to match. When the query has a city, a listing in another city is dropped before scoring. A card that already passed that check is scored under the query name, so a Maps title of "Wegmans" can match "Wegmans Food Markets". The row still shows the Maps title. `no_match` leaves `candidate` null.

Known false pairs that stay `no_match`:

- STRIKER CONSTRUCTION SERVICES LLC (NY, Cattaraugus) vs “C. Staker Remodeling”
- B&B Basecamp LLC (Denver) vs “Base Camp at Golden Gate Canyon”

`includeEmails` defaults to false. When true, emails are read only from the website of a `match`, then validated. The Actor does not guess addresses and does not search Google for them.

## Input

`fixtures/INPUT.json`:

```json
{
  "queries": [
    {
      "name": "Wegmans Food Markets",
      "city": "Rochester",
      "county": "Monroe",
      "state": "NY",
      "maxResults": 3
    }
  ],
  "minConfidence": 80,
  "lowConfidenceFloor": 60,
  "maxSearches": 1,
  "headless": true,
  "includeEmails": false,
  "maxSpendUsd": 5,
  "maxProxyCostUsd": 0.5,
  "allowCaptcha": false,
  "proxyConfiguration": {"useApifyProxy": false}
}
```

A single object (`name`, `state`, optional `city` and `county`) works when `queries` is omitted. `maxResults` defaults to 5 and cannot exceed 20. `maxSearches` defaults to 10 and cannot exceed 50. Search delay defaults to a random 2.0–4.5 seconds and detail delay to 1.2–2.8 seconds, same as the local Maps session. Overrides are optional. `maxSpendUsd` defaults to 5, `maxProxyCostUsd` to 0.50, and `allowCaptcha` to false. The proxy group is used only after a block. The default run timeout is 900 seconds at 2048 MB.

## Output

```json
{
  "query": {
    "name": "Wegmans Food Markets",
    "city": "Rochester",
    "county": "Monroe",
    "state": "NY",
    "maxResults": 3
  },
  "decision": "match",
  "score": 90,
  "breakdown": {"name": 50, "location": 35, "category": 0, "corroboration": 5},
  "hardRejects": [],
  "candidate": {
    "business_name": "Wegmans",
    "phone": "(585) 244-7950",
    "website": "https://www.wegmans.com/stores/east-ave-ny/",
    "address": "1750 East Ave, Rochester, NY 14610",
    "rating": 4.5,
    "user_ratings_total": 4754,
    "category": "Grocery store",
    "mapsUrl": "https://www.google.com/maps/place/Wegmans/",
    "placeId": "ChIJhwPAPIHK1okRJJMPqz59rNE"
  },
  "sourceStatus": "ok",
  "scrapedAt": "2026-10-10T00:00:00+00:00"
}
```

A different business, such as Whole Foods Market in the same city, is not attached to that row. A rejected query looks like `decision: "no_match"`, `candidate: null`, and `hardRejects` of `brand_token_missing` or `city_mismatch`. The dataset Overview shows the decision and score. Detail shows the query, breakdown, hard rejects, and candidate. `sourceStatus` is `ok`, `blocked`, `robots_disallowed`, or `error`. Key-value `SUMMARY` counts pushed, blocked, and error rows.

Candidate fields come from the Maps session: phone, website, address, rating, `user_ratings_total`, category, `mapsUrl`, `placeId`.

## Google terms, robots, and blocks

Google’s terms restrict automated extraction. A robots.txt `Allow` is not permission to automate Maps. This Actor is for occasional research, not bulk lead lists.

`https://www.google.com/robots.txt` is read first and evaluated with longest-match rules (`crm_enrich_robots.py`). Under those rules, `/maps/search/` and `/maps/place/` can be allowed while `Disallow: /maps/` is also present, and `/search` stays disallowed. This Actor never requests `https://www.google.com/search`. Python’s `urllib.robotparser` is not used, because it hides the more specific Maps `Allow` lines.

If Google returns a block page, the Actor retries that query once through Apify Proxy when `maxProxyCostUsd` and `maxSpendUsd` still have room. The first search stays direct. The proxy group comes from `proxyConfiguration` or `proxyGroups`; an empty group uses datacenter. A CAPTCHA solve runs only when that retry is still a challenge, `allowCaptcha` is true, and the spend cap covers the solve. This Actor does not ship a solver, so `allowCaptcha: true` still pushes `blocked` and does not bill a solve until one is configured. When the cap is already spent, solving is off, or the proxy URL cannot be opened, the current query is pushed as `blocked`, remaining queries are skipped, and the run exits successfully. A robots disallow is not retried. Chromium starts with `--disable-blink-features=AutomationControlled` from `BusinessDiscoverySession`. No stealth plugin is added. Search and detail delays stay on the source session.

## Limitations

- One Maps page of results per query, then place pages up to `maxResults`.
- Official Places API data (opening hours from the API, verified owner fields) is out of scope.
- Emails are not collected for `low_confidence` or `no_match` rows.
- ZIP-to-county and area-code checks use the tables in `scripts/lead_automation/data/` when those files are present.

## Pricing

Pay per event. The primary event is `result` at $0.05, charged only for `decision: "match"`. `low_confidence`, `no_match`, `blocked`, and `error` rows are stored and not billed. `proxy` is $0.01 and is charged only when a blocked query is retried through Apify Proxy. `captcha` is $1.00 and is charged only when a solver returns a token. Direct searches are free. Dataset items are not a charge event, so a rejected business does not cost a result. `maxSpendUsd` (default 5) caps those events together. `maxProxyCostUsd` (default 0.50) caps proxy events. The platform still applies its start event. Prices are the starting Store rates in `.actor/pay_per_event.json`. A local run logs that the charge was ignored until the Console pricing model is pay per event; the dataset row is still saved. Default memory is 2048 MB and the default timeout is 900 seconds. Do not price this as a bulk crawler.

## Categories

Set in the Apify Console. Suggested: Business, Lead generation.

## Local run

```bash
cd scripts/apify-scripts/google-business
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

A local run opens Google Maps. Unit tests do not. Publish with `APIFY_TOKEN`, not `APIFY_API_KEY`. See `scripts/apify-scripts/README.md`.
