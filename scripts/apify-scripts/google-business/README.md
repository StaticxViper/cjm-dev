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

`hardRejects` can include `distinctive_token_missing`, `state_mismatch`, `county_mismatch`, `address_mismatch`, `area_code_state_mismatch`, `permanently_closed`, and `website_is_directory`. Legal suffixes such as LLC are stripped before the name comparison. State on the query is required.

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
      "name": "Northwind Customs LLC",
      "city": "Olean",
      "county": "Cattaraugus",
      "state": "NY",
      "maxResults": 3
    }
  ],
  "minConfidence": 80,
  "lowConfidenceFloor": 60,
  "maxSearches": 1,
  "headless": true,
  "includeEmails": false
}
```

A single object (`name`, `state`, optional `city` and `county`) works when `queries` is omitted. `maxResults` defaults to 5 and cannot exceed 20. `maxSearches` defaults to 10 and cannot exceed 50. Search delay defaults to a random 2.0–4.5 seconds and detail delay to 1.2–2.8 seconds, same as the local Maps session. Overrides are optional. `proxyConfiguration` is ignored.

## Output

```json
{
  "query": {
    "name": "Northwind Customs LLC",
    "city": "Olean",
    "county": "Cattaraugus",
    "state": "NY",
    "maxResults": 3
  },
  "decision": "no_match",
  "score": 32,
  "breakdown": {"name": 17, "location": 10, "category": 5, "corroboration": 0},
  "hardRejects": ["distinctive_token_missing", "county_mismatch"],
  "candidate": {
    "business_name": "C. Staker Remodeling",
    "phone": "(631) 821-4921",
    "website": "http://cstakerremodeling.com/",
    "address": "100 Main St, Huntington, NY 11743",
    "rating": null,
    "user_ratings_total": null,
    "category": "Remodeler",
    "mapsUrl": null,
    "placeId": "ChIJ___LaZ1n6IkRBv6QRmL-qc4"
  },
  "sourceStatus": "ok",
  "scrapedAt": "2026-10-10T00:00:00+00:00"
}
```

That sample is the rejected STRIKER pairing, not a recommended live query. `sourceStatus` is `ok`, `blocked`, `robots_disallowed`, or `error`. Key-value `SUMMARY` counts pushed, blocked, and error rows.

Candidate fields come from the Maps session: phone, website, address, rating, `user_ratings_total`, category, `mapsUrl`, `placeId`.

## Google terms, robots, and blocks

Google’s terms restrict automated extraction. A robots.txt `Allow` is not permission to automate Maps. This Actor is for occasional research, not bulk lead lists.

`https://www.google.com/robots.txt` is read first and evaluated with longest-match rules (`crm_enrich_robots.py`). Under those rules, `/maps/search/` and `/maps/place/` can be allowed while `Disallow: /maps/` is also present, and `/search` stays disallowed. This Actor never requests `https://www.google.com/search`. Python’s `urllib.robotparser` is not used, because it hides the more specific Maps `Allow` lines.

If Google returns a block page, the current query is pushed as `blocked`, remaining queries are skipped, and the run exits successfully. The Actor does not solve CAPTCHAs, rotate proxies or user agents, or add stealth plugins. Chromium still starts with the existing `--disable-blink-features=AutomationControlled` flag from `BusinessDiscoverySession`.

## Limitations

- One Maps page of results per query, then place pages up to `maxResults`.
- Official Places API data (opening hours from the API, verified owner fields) is out of scope.
- Emails are not collected for `low_confidence` or `no_match` rows.
- ZIP-to-county and area-code checks use the tables in `scripts/lead_automation/data/` when those files are present.

## Pricing

Placeholder, not a live price: pay per query result, or compute units, after a private one-query run is measured. Default memory is 2048 MB. Do not price this as a bulk crawler.

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
