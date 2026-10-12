# Grocery price sync

Local scraper for public ShopRite, Costco, and Amazon product pages. The dashboard "Look Up" button sets `shopping_item_stores.check_status` to `pending`. This script runs on your machine, polls those rows, and writes prices with the Supabase service role. It does not call the `grocery-lookup` edge function.

A run uses one normal desktop browser profile and waits at least 2 seconds between pages. It does not use stealth plugins, proxy rotation, CAPTCHA solving, or a store login. A robot check, an out-of-stock page, or a Costco member-only wall is saved as `check_status = failed` and the previous price stays.

## Run it

From the repo root, with the project virtualenv active:

```bash
source .venv/Scripts/activate
pip install -r requirements/requirements.txt
python -m playwright install chromium
cd scripts
python -m grocery.scraper --listen
```

`cd scripts` is required. From `scripts/grocery`, `python scraper.py --listen` does the same thing.

| Command | What it does |
|---------|----------------|
| `python -m grocery.scraper --listen` | Every 10 seconds, scrape rows with `check_status = pending` and write the result |
| `python -m grocery.scraper --item <item_id>` | Scrape every store link for one master-list item now |
| `python -m grocery.scraper --all` | Re-check every linked master-list item |
| `python -m grocery.scraper --set-shoprite-store` | Open ShopRite so you can pick a store, then save the browser session |

`python -m grocery.sync` still posts batches to the `grocery-lookup` edge function. Use `grocery.scraper` for the local queue.

## Setup

Copy [scripts/grocery/.env.example](../../scripts/grocery/.env.example) values into the repo-root `.env`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- `DEFAULT_SHOPRITE_ZIP`
- `GROCERY_MIN_DELAY_SECONDS` (default 2, and never below 2)
- `GROCERY_TIMEOUT_MS` (default 30000)
- `GROCERY_BATCH_SIZE` (default 20, used by `grocery.sync`)
- `GROCERY_POLL_SECONDS` (default 10)

`SUPABASE_ANON_KEY` is only used by `grocery.sync`. The local queue uses `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.

ShopRite prices depend on the store. Run `--set-shoprite-store` once and choose the store in the browser, or set `DEFAULT_SHOPRITE_ZIP`. The ZIP path only works when the site shows a ZIP field. The saved session file is `scripts/grocery/.shoprite_storage.json` and is gitignored.

## What a lookup does

1. Read `shopping_item_stores` with the item name, brand, UPC, and store provider. `--listen` keeps rows where `check_status` is `pending`.
2. Open `product_url` when it is set. When it is empty, search `{brand} {name}` and keep the first result whose title shares at least half of those words, then open that page and save the URL.
3. Read the current price, regular price, and package size. Amazon uses the one-time purchase price. `unit_price` is the pack price divided by `size_value`.
4. If the last `pack_price` is above 0 and the new price is above 3x or below 0.33x that value, set `check_status` to `flagged`, store `check_error`, and leave `pack_price` unchanged.
5. Otherwise set `pack_price`, `regular_price`, size, `price_source` to `script`, `check_status` to `ok`, clear `check_error`, and insert `shopping_price_history`.
6. On a block, out-of-stock page, or missing price, set `check_status` to `failed` and keep the previous price.

`--listen` prints a line like:

```text
[11:05:22] Found 1 pending lookup: 'Chicken Breast' @ ShopRite -> Found $4.99/lb ($12.48 total). Updated successfully.
```

## Tests

```bash
python -m unittest discover unittests/grocery
```

Fixtures stand in for live pages. Supabase and Playwright are not called.
