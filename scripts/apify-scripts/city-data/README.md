# City-Data City Profiles

Playwright Actor that reads [city-data.com](https://www.city-data.com/) city profile pages and optional crime pages, then pushes one JSON object per city. It wraps `scripts/city_data/city_data_scraper.py` (issue #99). It does not call a paid API and it does not post results to Lovable.

Low-volume research. Keep `delaySeconds` at 1.5 or higher.

## What it does

For each city the Actor opens one Chromium browser, loads `https://www.city-data.com/city/{City}-{State}.html`, and parses population, income, housing, cost of living, and education with the same BeautifulSoup parsers as the local CLI. When `crime` is requested it also loads `/crime/crime-{City}-{State}.html`. Images, fonts, media, and common ad hosts are blocked by the existing session. A missing city page sets `ok: false` and the run continues with the next city.

Sex-offender lists are not scraped.

## Input

`fixtures/INPUT.json`:

```json
{
  "city": "Clementon",
  "state": "NJ",
  "fields": ["population", "crime"],
  "delaySeconds": 1.5,
  "timeoutMs": 30000,
  "headless": true,
  "maxCities": 1
}
```

A list works too: `cities: [{"city": "Clementon", "state": "NJ", "slug": ""}]`. Optional `slug` overrides the path token. `headless` defaults to true. `proxyConfiguration` is on the form and ignored.

## Output

One dataset item per city, plus key-value `SUMMARY` with pushed / blocked / error counts.

```json
{
  "city": "Clementon",
  "state": "NJ",
  "urls": {
    "city": "https://www.city-data.com/city/Clementon-New-Jersey.html",
    "crime": "https://www.city-data.com/crime/crime-Clementon-New-Jersey.html"
  },
  "ok": true,
  "sourceStatus": "ok",
  "scrapedAt": "2026-09-04T19:00:00+00:00",
  "population": {"year": 2024, "total": 5600},
  "crime": {"index": 120.5, "index_year": 2024, "by_year": []}
}
```

The sample numbers match the local scraper docs. A live page will differ. Missing parser keys are omitted. `sourceStatus` is `ok`, `error`, or `robots_disallowed`.

### Field glossary

| Group | Page | Keys |
|-------|------|------|
| `population` | City | year, total, urban/rural %, change since 2000, median age, males, females |
| `income` | City | year, median household, per capita, poverty rate |
| `housing` | City | median home value, median gross rent, renter % |
| `cost_of_living` | City | index, year |
| `education` | City (age 25+) | high school or higher %, bachelor's or higher % |
| `crime` | Crime page, city table if the crime URL 404s | index, year, vs US average, year-over-year %, homicides, violent/property rates, officers per 1,000, `by_year` |

## Limitations

- One browser for the run. Delay default is 1.5 seconds between requests, same as the CLI.
- The session retries a failed navigation once. The Actor does not add a second retry loop around it.
- A disallowed path is skipped. The row records `robots_disallowed` and no request is sent.
- This Actor does not geocode addresses and does not ingest rows into another app.

## Robots

Checked against the live `https://www.city-data.com/robots.txt` while packaging. For `User-agent: *`, `/city/{Name}.html` and `/crime/crime-{Name}.html` are not disallowed. The file does disallow paths such as `/so/`, `/city/js/getBoxes.php*`, forums search, and several script endpoints. Named AI crawlers are `Disallow: /`. This Actor sends the same Chrome user agent as the local scraper and evaluates the `*` group with the longest-match rules in `crm_enrich_robots.py` before every URL. If the site later disallows `/city/` or `/crime/`, those fetches stop.

## Pricing

Placeholder, not a live price: charge per city result (pay-per-result) or by compute units after a private run measures Chromium time. A one-city Clementon run is the sample to measure. Memory default is 2048 MB.

## Categories

Set in the Apify Console, not in `actor.json`. Suggested: Business, Real estate.

## Local run

```bash
cd scripts/apify-scripts/city-data
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

Publish with `APIFY_TOKEN` (`apify push`). That token is not `APIFY_API_KEY`. See `scripts/apify-scripts/README.md`.
