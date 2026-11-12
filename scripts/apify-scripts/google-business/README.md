# Google Maps Business Leads – Phone, Website & Rating

**Google Maps Business Leads takes a business name and US state and returns the matching Google Maps listing, with phone, website, address, rating, review count, and a match confidence decision, for sales teams and data teams cleaning or enriching lead lists.**

$0.006 per accepted match ($6 per 1,000) on the free tier, as low as $0.003 on paid Apify plans. Rejected and low-confidence lookups are free.

## Who is it for?

- **Sales and SDR teams** who have company names from a CRM or list and need a verified phone number and website.
- **RevOps and data teams** de-duplicating or enriching account records with Maps place IDs and categories.
- **Agencies** checking a prospect's rating and review count before outreach.
- **Lead-list builders** who need a confidence score so a wrong business never lands in the list.

## What data do you get?

One dataset item per query.

| Field | Type | What it holds |
|-------|------|---------------|
| `query` | object | The name, city, county, state, and `maxResults` you sent |
| `decision` | string | `match`, `low_confidence`, `no_match`, `blocked`, or `error` |
| `score` | number | Match score from 0 to 100 |
| `breakdown` | object | Points for name, location, category, and corroboration |
| `hardRejects` | array | Reasons a listing was rejected, such as `city_mismatch` or `brand_token_missing` |
| `candidate` | object | The matched listing: `business_name`, `phone`, `website`, `address`, `rating`, `user_ratings_total`, `category`, `mapsUrl`, `placeId`. `null` on `no_match` |
| `emails` | array | Validated emails from the matched business's own website, when `includeEmails` is on |
| `sourceStatus` | string | `ok`, `blocked`, `robots_disallowed`, or `error` |
| `error` | string | Reason when the row failed |
| `scrapedAt` | string | ISO timestamp |

Sample row for a Rochester, NY lookup:

```json
{
  "query": {"name": "Wegmans Food Markets", "city": "Rochester", "county": "Monroe", "state": "NY", "maxResults": 3},
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

### What do the decisions mean?

| `decision` | Meaning | Billed |
|------------|---------|--------|
| `match` | Score at or above `minConfidence` (default 80) and no hard reject | yes |
| `low_confidence` | Score between `lowConfidenceFloor` (default 60) and `minConfidence` | no |
| `no_match` | Hard reject, weak score, or no listing. `candidate` is `null` | no |
| `blocked` | Google showed a block page. Later queries are not run | no |
| `error` | Bad input, robots, or an unexpected failure | no |

The first Maps card is never used as a fallback. A different brand in the same city, such as Whole Foods for a Wegmans query, is never attached to the row. Legal suffixes like LLC are ignored when names are compared, and a listing in another city is dropped before scoring.

## Input

```json
{
  "queries": [
    {"name": "Wegmans Food Markets", "city": "Rochester", "county": "Monroe", "state": "NY", "maxResults": 3}
  ],
  "minConfidence": 80,
  "includeEmails": false
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `queries` | — | Up to 50 objects with `name` and `state` (required), plus optional `city`, `county`, `maxResults` |
| `name`, `state`, `city`, `county` | — | Shortcut for a single query |
| `maxResults` | 5 (max 20) | Maps listings opened per query |
| `minConfidence` | 80 | Score needed for `match` |
| `lowConfidenceFloor` | 60 | Score needed for `low_confidence` |
| `maxSearches` | 10 (max 50) | Maps searches per run |
| `includeEmails` | false | Read emails from the website of each `match` |
| `maxSpendUsd` | 5 (max 100) | Hard cap on what one run can charge |
| `maxProxyCostUsd`, `allowCaptcha`, `proxyConfiguration` | 0.5, false, off | Block handling, see below |

Search and detail delays are randomized (2.0–4.5 s and 1.2–2.8 s) and can be overridden.

## How much does it cost?

Pay per event. You pay only for accepted matches.

| Event | Free tier | Bronze | Silver | Gold and up |
|-------|-----------|--------|--------|-------------|
| Accepted match (`result`) | $0.006 | $0.005 | $0.004 | $0.003 |

- **100 matches:** 100 × $0.006 = **$0.60**
- **1,000 matches:** 1,000 × $0.006 = **$6.00** (as low as $3.00 on Gold)

`low_confidence`, `no_match`, `blocked`, and `error` rows are saved and not billed, so a list full of closed or unknown businesses costs nothing for those rows. Emails do not add a charge. Apify adds its small per-run start event.

## Limits and data source

- **Source:** public Google Maps search (`/maps/search/`) and place pages (`/maps/place/`) in a real Chromium browser. This is not the paid Google Places API, and you do not need an API key.
- **Never requested:** Google web search (`/search`). Emails are read only from the matched business's own website, never guessed and never searched on Google.
- **Volume:** one Maps results page per query, then up to `maxResults` place pages. Built for lookups and list cleaning, not bulk crawling.
- **Robots:** Google's robots.txt is checked with longest-match rules before any request.
- **Blocks:** the first search is direct. After a block, the query may be retried once through Apify Proxy inside `maxProxyCostUsd`. If it is still blocked, that query is `blocked`, the remaining queries are skipped, and the run ends cleanly. No CAPTCHA solver ships with this Actor.
- **Out of scope:** Places API fields such as official opening hours or owner-verified data.
- **Terms:** Google's terms restrict automated extraction, and a robots.txt `Allow` is not permission. Use this Actor for occasional research and list hygiene.

## FAQ

### How do I find a business's phone number and website from its name?

Add the business name and state (and city if you know it) to `queries` and run. A `match` row has the phone, website, address, and Maps URL in `candidate`.

### How accurate are the matches?

A row is a `match` only when the name and location checks score 80 or more and no hard reject fires, such as a different city, a missing brand word, a closed listing, or a directory site instead of the business's own website. Anything weaker is `low_confidence` or `no_match`, and is not billed.

### Do I need a Google Places API key?

No. The Actor reads the public Maps pages, so no Google API key or Google Cloud billing is involved.

### Can it get business emails?

Yes. Set `includeEmails: true`. Emails are read from the matched business's own website and validated. There is no extra charge for them.

### Does this need a proxy?

Usually not. Searches start direct, and a proxy is used only to retry a search that was blocked. The current price list has no separate proxy charge.

### What counts as a result?

One `match` row. Everything else is free.

## Integrations and output

- **Dataset:** one row per query, with an Overview view (decision and score) and a Detail view (query, breakdown, rejects, candidate). Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` counts pushed, blocked, and error rows.
- **Automation:** run it from the Apify API, on a schedule, or through Make, Zapier, n8n, or Google Sheets.

## Related actors

- [Home Services Leads](https://apify.com/staticxviper/home-services): build a lead list by niche and area, with emails and lead scores.
- [New Business Leads](https://apify.com/staticxviper/new-business): newly registered LLCs and corporations you can then match on Maps.
- [Contractor License Lookup](https://apify.com/staticxviper/contractor-license): verify a California contractor's license status.

## Changelog

Release notes are on the **Changelog** tab of this page.
