# Property city-data lookup

**Source:** `scripts/city_data/property_city_lookup.py`

**Workflow:** `.github/workflows/property_city_data.yml`

## Purpose

Accepts a US property address, resolves city/state, scrapes city-data.com demographics and crime via [`city_data_scraper.py`](city_data_scraper.md), and emits a single-address JSON envelope for a future APIManager ingest endpoint.

Data is **city-level**, not street-level. The address is used only to derive `city` + `state` (ZIP is kept as query metadata).

## Prerequisites

- Python 3.12+
- Dependencies from `requirements/requirements.txt`
- `playwright install chromium`

No API keys for scrape-only runs. Ingest is skipped until `CITY_DATA_INGEST_BASE_URL` is set.

## How to run locally

```bash
# From repo root
PYTHONPATH=$PWD python scripts/city_data/property_city_lookup.py \
  --address "123 Main St, Clementon, NJ 08021"

# Optional field allowlist and slug override
PYTHONPATH=$PWD python scripts/city_data/property_city_lookup.py \
  --address "123 Main St, Cherry Hill, NJ 08002" \
  --fields population,income,crime \
  --slug Cherry-Hill-Mall \
  --output-path scripts/city_data/property_city_data_output.json
```

### CLI flags

| Flag | Description |
|------|-------------|
| `--address` | Required US address |
| `--fields` | Comma-separated groups (default: all) |
| `--slug` | Optional city-data URL slug override |
| `--output-path` | Envelope destination (default `property_city_data_output.json`) |
| `--delay` / `--timeout-ms` / `--headless` | Passed through to the scraper |

## GitHub Action (API-triggerable)

`workflow_dispatch` only. Dispatch via the GitHub API:

```http
POST /repos/{owner}/{repo}/actions/workflows/property_city_data.yml/dispatches
Authorization: Bearer <token>
Content-Type: application/json

{
  "ref": "<branch-with-workflow>",
  "inputs": {
    "address": "123 Main St, Clementon, NJ 08021"
  }
}
```

Optional inputs: `fields`, `slug`.

The job installs Playwright Chromium, runs the lookup, prints the JSON in the job log, and uploads `property_city_data_output.json` as the `property-city-data` artifact.

## Output JSON structure

This is the payload the future ingest endpoint should expect. Empty scraper groups are omitted inside `demographics` / `crime`; top-level keys are always present.

```json
{
  "schema_version": "1.0",
  "source": "city-data.com",
  "scraped_at": "2026-09-05T19:00:00+00:00",
  "query": {
    "address": "123 Main St, Clementon, NJ 08021",
    "street": "123 Main St",
    "city": "Clementon",
    "state": "NJ",
    "zip": "08021",
    "slug": null
  },
  "ok": true,
  "error": null,
  "urls": {
    "city": "https://www.city-data.com/city/Clementon-New-Jersey.html",
    "crime": "https://www.city-data.com/crime/crime-Clementon-New-Jersey.html"
  },
  "demographics": {
    "population": {
      "year": 2024,
      "total": 5600,
      "urban_pct": 100.0,
      "rural_pct": 0.0,
      "change_since_2000_pct": 12.3,
      "median_age": 38.1,
      "males": 2700,
      "females": 2900
    },
    "income": {
      "year": 2023,
      "median_household": 65754,
      "per_capita": 30725,
      "poverty_rate": 16.8
    },
    "housing": {
      "median_home_value": 260711,
      "median_gross_rent": 1194,
      "renter_pct": 36.0
    },
    "cost_of_living": {
      "index": 101.4,
      "year": 2024
    },
    "education": {
      "hs_or_higher_pct": 85.2,
      "bachelors_or_higher_pct": 18.4
    }
  },
  "crime": {
    "index": 315,
    "index_year": 2025,
    "vs_us_average": "1.4 times higher",
    "yoy_change_pct": -19.0,
    "homicides": 346,
    "violent_crime_rate": 259.7,
    "property_crime_rate": 247.7,
    "officers_per_1000": 4.25,
    "by_year": [
      {
        "year": 2025,
        "murders": 346,
        "rapes": 0,
        "robberies": 0,
        "assaults": 0,
        "burglaries": 0,
        "thefts": 40000,
        "auto_thefts": 5000,
        "arson": 0,
        "crime_index": 315
      }
    ]
  }
}
```

**Failure shape:** same envelope with `ok: false`, an `error` string, and empty `demographics` / `crime`.

## Ingest (later)

When the endpoint is ready, set:

| Variable | Purpose |
|----------|---------|
| `CITY_DATA_INGEST_BASE_URL` | Base URL for `APIManager.build_request` |
| `CITY_DATA_INGEST_ENDPOINT` | Path (default `/city-data/ingest`) |
| `CITY_DATA_INGEST_API` | Optional APIManager key name for auth |

Until `CITY_DATA_INGEST_BASE_URL` is set, the script logs a skip and only writes/prints the JSON.

## Related

- [city_data_scraper.md](city_data_scraper.md) — underlying scraper and field groups
- [property_listing_gen.md](property_listing_gen.md) — Zillow ZIP listing URLs
- [api_manager.md](../helper_scripts/api_manager.md) — HTTP ingest helper
