# City Data Scraper – Population, Crime & Demographics

**City Data Scraper returns one JSON row per US city from city-data.com, with population, income, housing, cost of living, education, and crime stats, for real estate investors, market researchers, and anyone comparing towns.**

$0.008 per city profile ($8 per 1,000) on the free tier, lower on paid Apify plans. Only successful profiles are billed.

## Who is it for?

- **Real estate investors and agents** comparing median home value, rent, and renter share across towns before buying or farming an area.
- **Relocation and site-selection analysts** who need population, income, and cost-of-living numbers side by side.
- **Local lead-gen and marketing teams** sizing a market by households, income, and growth before a campaign.
- **Journalists and researchers** pulling crime index and year-by-year crime counts for a list of cities.
- **Data teams** enriching a CRM or spreadsheet of city names with demographics.

## What data do you get?

One dataset item per city. Pick the groups you need with `fields`.

| Field | Type | What it holds |
|-------|------|---------------|
| `city`, `state` | string | The city and 2-letter state you asked for |
| `ok` | boolean | `true` when the city page was fetched and parsed |
| `sourceStatus` | string | `ok`, `blocked`, `robots_disallowed`, or `error` |
| `error` | string | Reason when the row is not `ok` |
| `urls` | object | city-data.com URLs used for the city and crime pages |
| `population` | object | Year, total, urban/rural %, change since 2000, median age, males, females |
| `income` | object | Year, median household income, per capita income, poverty rate |
| `housing` | object | Median home value, median gross rent, renter % |
| `cost_of_living` | object | Cost-of-living index and year |
| `education` | object | High school or higher %, bachelor's or higher % (age 25+) |
| `crime` | object | Crime index, year, vs US average, year-over-year %, homicides, violent and property rates, officers per 1,000, `by_year` |
| `scrapedAt` | string | ISO timestamp of the fetch |

Sample row from a live Clementon, NJ run (later runs will show newer numbers):

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

Keys a page does not publish are left out. In the dataset, the Overview view shows the city and status, and the Detail view shows every group.

## Input

Two cities with every field group:

```json
{
  "cities": [
    {"city": "Clementon", "state": "NJ"},
    {"city": "Austin", "state": "TX"}
  ],
  "fields": ["population", "income", "housing", "cost_of_living", "education", "crime"],
  "maxCities": 5
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `cities` | — | Up to 50 `{city, state}` objects. An optional `slug` overrides the URL token |
| `city`, `state` | — | Shortcut for a single city |
| `fields` | all six groups | `population`, `income`, `housing`, `cost_of_living`, `education`, `crime` |
| `maxCities` | 5 (max 50) | Cities processed per run |
| `delaySeconds` | 1.5 | Pause between requests. Keep it at 1.5 or higher |
| `timeoutMs` | 30000 | Page-load timeout |
| `maxSpendUsd` | 5 (max 100) | Hard cap on what one run can charge |
| `maxProxyCostUsd`, `allowCaptcha`, `proxyConfiguration` | 0.5, false, off | Block handling, see below |

## How much does it cost?

Pay per event. You pay only for city profiles that come back `ok`.

| Event | Free tier | Bronze | Silver | Gold and up |
|-------|-----------|--------|--------|-------------|
| City profile (`result`) | $0.008 | $0.007 | $0.006 | $0.005 |

- **100 cities:** 100 × $0.008 = **$0.80**
- **1,000 cities:** 1,000 × $0.008 = **$8.00** (as low as $5.00 on Gold)

Missing pages, robots skips, blocked rows, and errors are saved to the dataset and not billed. Apify adds its small per-run start event. `maxSpendUsd` stops the run before a charge would pass your cap.

## Limits and data source

- **Source:** public city and crime pages on [city-data.com](https://www.city-data.com/). Each city is `/city/{City}-{State}.html`, plus `/crime/crime-{City}-{State}.html` when `crime` is selected. When the crime page is missing, crime numbers come from the city page table.
- **Coverage:** US cities and towns that have a city-data.com profile. A city without a page returns `ok: false` and the run moves on.
- **Pacing:** one browser per run, 1.5 seconds between requests by default, one retry on a failed navigation.
- **Robots:** robots.txt is checked before every URL. A disallowed path is skipped and recorded as `robots_disallowed`.
- **Blocks:** the first request is always direct. After a real block (HTTP 401, 403, 429, or a challenge page) the Actor may retry that URL once through Apify Proxy, inside `maxProxyCostUsd`. If it is still blocked, the row is `blocked` and later cities are not requested. No CAPTCHA solver ships with this Actor.
- **Not scraped:** sex-offender lists, forum pages, and anything behind a login. Addresses are not geocoded.
- **Terms:** city-data.com restricts automated collection. Keep runs small and keep the delay at 1.5 seconds or higher.

## FAQ

### How do I get population and median income for a list of US cities?

Add each city and state to `cities`, keep `population` and `income` in `fields`, and run. Each city comes back as one row with a `population` and an `income` object. Export as CSV or Excel from the dataset tab.

### Can I get crime rates by city?

Yes. Include `crime` in `fields`. The row's `crime` object has the city-data crime index, its comparison with the US average, year-over-year change, violent and property crime rates, and a `by_year` history when the page publishes one.

### What counts as a billable result?

One city profile with `ok: true`. Cities with no page, robots-skipped cities, blocked requests, and errors are free.

### Does this need a proxy?

No. Runs start on a direct connection. A proxy is used only to retry a request that was actually blocked, and the current price list has no separate proxy charge.

### How many cities can I run at once?

Up to 50 per run (`maxCities`). For bigger lists, split them across runs or schedule the Actor.

### Is the data current?

The numbers are what city-data.com shows at the time of the run. `scrapedAt` records when each row was fetched, and each group carries the year city-data.com reports.

## Integrations and output

- **Dataset:** one row per city. Download it as JSON, CSV, Excel, or HTML, or read it from the API.
- **Key-value store:** `SUMMARY` holds the pushed, blocked, and error counts for the run.
- **Automation:** call the Actor from the Apify API, schedule it in Apify, or connect it to Make, Zapier, n8n, or Google Sheets through Apify integrations.

## Related actors

- [Building Permits Scraper](https://apify.com/staticxviper/permits): recent roofing, solar, and pool permits for Chicago, Seattle, Austin, and Los Angeles.
- [Zillow Real Estate Agent Scraper](https://apify.com/staticxviper/zillow-agents): listing agents by ZIP code with phone and email.
- [New Business Leads](https://apify.com/staticxviper/new-business): newly registered LLCs and corporations by state and county.

## Changelog

Release notes are on the **Changelog** tab of this page.
