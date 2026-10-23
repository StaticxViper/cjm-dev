# Grocery

Local Playwright scraper for public ShopRite, Costco, and Amazon product pages. It polls `shopping_item_stores` rows marked `pending` and writes prices back to Supabase. It does not call the `grocery-lookup` edge function.

**Inputs:** pending rows in Supabase, or CLI flags such as `--search`, `--test-url`, and `--all`. **Outputs:** price and `check_status` updates on those rows. A robot check, an out-of-stock page, or a member wall is stored as `failed` and the previous price stays.

**Local run** from `scripts/` after `python -m playwright install chromium`:

```bash
python -m grocery.scraper --listen
python -m grocery.sync
python -m grocery
```

**Script Manager:** `grocery`, `grocery-sync`, and `grocery-cli`. Example: `python -m scripts.script_manager run grocery -- --listen`. No grocery-specific GitHub Actions workflow.

**Secrets:** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. Sync also needs `SUPABASE_ANON_KEY`. Optional: `DEFAULT_SHOPRITE_ZIP`, `GROCERY_MIN_DELAY_SECONDS`, `GROCERY_TIMEOUT_MS`, `GROCERY_BATCH_SIZE`, `GROCERY_POLL_SECONDS`.

Longer guide: [documentation/scripts/grocery.md](../../documentation/scripts/grocery.md).
