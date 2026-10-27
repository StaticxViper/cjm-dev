# Home Services Lead Enricher

Low-volume lead list for one niche and one area. The Actor searches Google Maps with the Playwright session in `scripts/lead_automation/playwright_discovery.py`, then keeps a row only when the issue #127 matcher in `scripts/apify-scripts/google-business/` would accept it. Accepted rows can be enriched from the business website with an email, a website-quality score, and an intent lead score.

Pass `mapsDataset` to score listings you already have. That path does not open Google Maps.

This Actor does not call the Google Places API. Google web search (`/search`) is never requested. Emails come from the business website, not from a Google query.

## What it does

| `decision` | Meaning | Billed |
|------------|---------|--------|
| `accepted` | Issue #127 score at or above `minConfidence` (default 80) and no hard reject | `place`, plus add-ons when they produce a value |
| `rejected` | Negative keyword, hard reject, score below the minimum, or a different city | No |
| `blocked` | Google showed a block page. Later searches are not run | No |
| `error` | Input, robots, or unexpected failure | No |

A listing is scored under its own name against the requested city, county, and state. The niche keyword is the Maps search text. It is not treated as the business name, and the first Maps card is never used as a fallback. `low_confidence` stays `rejected` and is not billed.

Name plus state is 60. A city or county match adds the points that clear 80. A state-only area does not copy the card’s city, so those rows usually stay `rejected`. A `mapsDataset` with no area is matched to each listing’s own address.

Niche negative keywords (for example Leslie's for `pool_specialists`) are `rejected` before scoring.

## Input

`fixtures/INPUT.json`:

```json
{
  "niche": "pool_specialists",
  "area": "Rochester, NY",
  "maxItems": 5,
  "maxSearches": 1,
  "maxResults": 3,
  "includeEmail": true,
  "includeWebsiteQuality": true,
  "includeScore": true,
  "headless": true
}
```

`niche` is an id from `scripts/lead_automation/niches.json`.

`area` is a name from `scripts/lead_automation/geo_regions.json`, or `City, ST`, or `Monroe County, NY`. `city`, `county`, and `state` override that string. A region with several cities is searched city by city until `maxSearches` or `maxItems` is reached.

`mapsDataset` replaces the Maps search. Each item may use `business` or `business_name`, `phone`, `website`, `address`, `rating`, `review_count`, `category`, and `place_id`. With an area, a listing in another city is `rejected`. Without an area, each listing is matched to its own address.

`maxItems` is the cap on accepted leads (default 10, maximum 25). `maxSearches` caps Maps searches (default 5, maximum 20). `maxResults` caps listings opened per search (default 5, maximum 10). Search and detail delays stay on the Maps session.

`includeEmail`, `includeWebsiteQuality`, and `includeScore` default to true. Turn one off to skip that step.

## Output

```json
{
  "business": "Aqua Leak Pros",
  "phone": "(212) 555-0100",
  "website": "https://aqualeakpros.com/",
  "rating": 4.8,
  "review_count": 32,
  "email": "owner@aqualeakpros.com",
  "website_quality": 70,
  "website_label": "Poor",
  "lead_score": 45,
  "intent_signals": [
    {"key": "high_value_service", "label": "High-value specialty", "points": 10}
  ],
  "decision": "accepted",
  "match_score": 85,
  "hardRejects": [],
  "niche": "pool_specialists",
  "area": {"region": null, "city": "Rochester", "county": null, "state": "NY"},
  "sourceStatus": "ok",
  "scrapedAt": "2026-10-24T00:00:00+00:00"
}
```

`website_quality` uses the niche model: a higher number is a weaker site. `100` means no website. `lead_score` and `intent_signals` come from `intent_scoring.score_intent_lead`. The legacy `lead_scoring.py` model is not executed.

Key-value `SUMMARY` includes `accepted`, `rejected`, `blocked`, `errors`, `pushed`, `emailsFound`, and `scoresProduced`.

## Google terms, robots, and blocks

Google’s terms restrict automated extraction. A robots.txt `Allow` is not permission to automate Maps. This Actor is for occasional research. The Maps vertical is crowded, and this listing is differentiated by the niche filter and the enrichment, not by bulk scraping.

`https://www.google.com/robots.txt` is read before any Maps navigation and evaluated with longest-match rules (`crm_enrich_robots.py`). `/maps/search/` and `/maps/place/` can be allowed while `/search` stays disallowed. This Actor never requests `https://www.google.com/search`. Python’s `urllib.robotparser` is not used for that file.

Each business website is checked the same way before an email or quality fetch. A disallow, or a robots fetch that fails, skips those fetches. The place can still be saved. No email event is charged for that skip.

If Google returns a block page, the current search is pushed as `blocked`, remaining searches are skipped, and the run exits successfully. This Actor does not yet call the shared proxy and CAPTCHA ladder in `scripts/apify-scripts/access.py`, so a block stops the run with no proxy or solve charge. Chromium starts with `--disable-blink-features=AutomationControlled` from `BusinessDiscoverySession`.

## Limitations

- One Maps page of results per keyword, then place pages up to `maxResults`.
- Accepted leads stop at `maxItems`. Further keywords are not searched.
- A listing in another city is `rejected` and is not attached to an accepted row.
- Emails are not guessed and are not searched on Google.
- Website-only intent signals (broken site, missing form, ads) are omitted unless website quality actually fetched the page.
- Official Places API fields are out of scope.
- ZIP-to-county and area-code checks use `scripts/lead_automation/data/` when those files are present.
- `geo_regions.json` can be empty. `City, ST` still works.

## Pricing

Pay per event. Prices are the starting Store rates in `.actor/pay_per_event.json`.

| Event | When it is charged | Starting price |
|-------|--------------------|----------------|
| `place` | `decision` is `accepted` | $0.05 |
| `email-found` | That accepted row has a validated `email` | $0.03 |
| `score` | That accepted row has a `lead_score` | $0.02 |

`rejected`, `blocked`, `error`, a website with no email, and a score that was not produced are stored and not billed. Dataset items are not a charge event. The platform still applies its start event. A local run logs that the charge was ignored until the Console pricing model is pay per event. Default memory is 2048 MB and the default timeout is 900 seconds. Do not price this as a bulk crawler.

## Categories

Set in the Apify Console. Suggested: Business, Lead generation.

## Local run

```bash
cd scripts/apify-scripts/home-services
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

A local run without `mapsDataset` opens Google Maps. Unit tests do not. Publish with `APIFY_TOKEN`, not `APIFY_API_KEY`. See `scripts/apify-scripts/README.md`.
