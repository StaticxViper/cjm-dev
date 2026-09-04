# Zillow Property Listing Generator

**Source:** `scripts/zillow_automation/property_listing_gen.py`

## Purpose

Searches Zillow by ZIP code through Apify and writes a JSON array of property listing URLs. Uses `APIManager.run_apify` with the `Zillow ZIP Search` actor (`maxcopell/zillow-zip-search`).

The actor returns full listing cards (price, address, beds, photos). This script keeps only `propertyUrl` values so later steps can feed those URLs into a detail scraper.

## Prerequisites

- Python 3.12+
- `apify-client`, `python-dotenv`
- `APIFY_API_KEY` in repo-root `.env`
- Apify account with access to [`maxcopell/zillow-zip-search`](https://apify.com/maxcopell/zillow-zip-search)

The actor is paid per result (about $1.10 per 1,000 listings). Set `resultsLimit` before a large run.

## Configuration

| File | Description |
|------|-------------|
| `search_settings.json` | Default actor input (ZIP codes, price range, listing types, result cap) |
| `property_urls.json` | Output JSON array of listing URLs (created/overwritten on each run) |

Default `search_settings.json` matches the actor's example input:

```json
{
  "zipCodes": ["14010", "07306"],
  "priceMin": 100000,
  "priceMax": 400000,
  "daysOnZillow": "2",
  "forSaleByAgent": true,
  "forSaleByOwner": false,
  "forRent": false,
  "sold": false,
  "resultsLimit": 10
}
```

`resultsLimit` is per ZIP code. Two ZIP codes with a limit of 10 can return up to 20 URLs.

## How to run

```bash
cd scripts/zillow_automation

# Use search_settings.json
python property_listing_gen.py

# Custom input file and output path
python property_listing_gen.py --input search_settings.json --output-path property_urls.json

# Override ZIP codes and cap without editing the file
python property_listing_gen.py --zip-codes 19103 08002 --results-limit 5
```

From repo root:

```bash
python scripts/zillow_automation/property_listing_gen.py
```

### CLI flags

| Flag | Description |
|------|-------------|
| `--input PATH` | Actor input JSON (default `search_settings.json`) |
| `--output-path PATH` | URL list destination (default `property_urls.json`) |
| `--zip-codes ZIP [ZIP ...]` | ZIP codes to search (overrides `--input`) |
| `--price-min INT` | Minimum listing price |
| `--price-max INT` | Maximum listing price |
| `--days-on-zillow STR` | Max days listed (or days since sold when `--sold`) |
| `--results-limit INT` | Maximum properties per ZIP code |
| `--for-sale-by-agent` / `--no-for-sale-by-agent` | Include or exclude agent listings |
| `--for-sale-by-owner` / `--no-for-sale-by-owner` | Include or exclude owner listings |
| `--for-rent` / `--no-for-rent` | Include or exclude rentals |
| `--sold` / `--no-sold` | Include or exclude recently sold listings |

Flags overlay the input file. Unspecified flags leave the file values unchanged.

## How it works

1. Load actor input from `--input` (or built-in defaults if the file is missing).
2. Apply CLI overrides and require a non-empty `zipCodes` list.
3. Call `APIManager().run_apify(actor="Zillow ZIP Search", input=...)`.
4. Read `propertyUrl` from each dataset item (`detailUrl` / `hdpUrl` / `url` as fallback). Skip non-Zillow hosts and duplicates.
5. Write a JSON array of URLs atomically.

```mermaid
flowchart LR
  settings[search_settings.json] --> gen[property_listing_gen.py]
  gen --> actor[maxcopell/zillow-zip-search]
  actor --> urls[property_urls.json]
```

Example output:

```json
[
  "https://www.zillow.com/homedetails/125-Perry-St-PHE-New-York-NY-10014/458671486_zpid/"
]
```

## Entry points

| Function | Used by | Behavior |
|----------|---------|----------|
| `generate_listings(search_input, output_path, api=None)` | CLI / other scripts | Run the actor, write URLs, return the list |
| `run_search(search_input, api=None)` | `generate_listings` | Actor call only; no file write |
| `extract_property_urls(items)` | `run_search` | Pull unique Zillow listing URLs from dataset items |
| `normalize_search_input(data)` | load / resolve | Validate and coerce `zipCodes` |

## Related scripts

- [api_manager.md](../helper_scripts/api_manager.md) — Apify actor runner and key resolution
