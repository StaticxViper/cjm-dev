# Grocery price sync

Local scraper for public ShopRite, Costco, and Amazon product pages. It reads linked rows from `shopping_item_stores` and posts prices to the `grocery-lookup` edge function (`action: push_prices`). The grocery app itself is not in this repo.

A run uses one normal desktop browser profile and waits at least 2 seconds between pages. It does not use stealth plugins, proxy rotation, CAPTCHA solving, or a store login. A robot check is recorded as a failed URL. A Costco page that hides the price behind membership is recorded as `member_only`.

## Run it

From the repo root, with the project virtualenv active:

```bash
source .venv/Scripts/activate
pip install -r requirements/requirements.txt
python -m playwright install chromium
cd scripts
python -m grocery.sync --all
```

`cd scripts` is required. From `scripts/grocery`, `python sync.py --all` does the same thing.

| Command | What it does |
|---------|----------------|
| `python -m grocery.sync --all` | Scrape every linked item and push prices |
| `python -m grocery.sync --store shoprite` | Scrape one store (`shoprite`, `costco`, or `amazon`) |
| `python -m grocery.sync --dry-run --store costco` | Scrape and print the payload. Does not POST |
| `python -m grocery.sync --test-url "https://www.amazon.com/dp/..."` | Scrape one URL. Does not POST |
| `python -m grocery.sync --search "whole milk" --store costco` | Search and print up to 20 hits. Does not POST |
| `python -m grocery.sync --set-shoprite-store` | Open ShopRite so you can pick a store, then save the browser session |
| `--force` | Send `force: true` with `--all` or `--store` so a flagged outlier can overwrite |

## Setup

Copy [scripts/grocery/.env.example](../../scripts/grocery/.env.example) values into the repo-root `.env`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- `DEFAULT_SHOPRITE_ZIP`
- `GROCERY_MIN_DELAY_SECONDS` (default 2, and never below 2)
- `GROCERY_TIMEOUT_MS` (default 30000)
- `GROCERY_BATCH_SIZE` (default 20)

ShopRite prices depend on the store. Run `--set-shoprite-store` once and choose the store in the browser, or set `DEFAULT_SHOPRITE_ZIP`. The ZIP path only works when the site shows a ZIP field. The saved session file is `scripts/grocery/.shoprite_storage.json` and is gitignored.

`--test-url` and `--search` do not need the Supabase keys. `--all`, `--store`, and `--dry-run` do.

## What a sync does

1. `GET /rest/v1/shopping_item_stores` with the service role bearer token and the anon `apikey`. `--store` filters on `shopping_stores.provider`.
2. Skip rows with no `product_url`.
3. Open the product page and read the current price, regular price, package size, URL, and UPC or ASIN when the page exposes them. Amazon uses the one-time purchase price and ignores Subscribe & Save. Package strings such as `Pack of 2, 32 oz each` become a total size (`64` `oz`).
4. Drop a price that is missing, not finite, not positive, or above 10000.
5. `POST /functions/v1/grocery-lookup` in batches of 20 with `source: "script"` and `force: false` unless `--force` is set.
6. Print OK, flagged outliers, failed URLs, and a skipped count. A flagged row was rejected by the backend's 3x outlier guard and was not written. Exit 1 when any URL failed. Exit 2 when configuration is missing.

## Tests

```bash
python -m unittest discover unittests/grocery
```

Fixtures stand in for live pages. Supabase and Playwright are not called.
