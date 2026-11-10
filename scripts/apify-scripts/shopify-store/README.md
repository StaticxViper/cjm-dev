# Shopify Store Intel – Products, Prices & Theme Hints

**Shopify Store Intel exports the public product catalog of any list of Shopify stores, with titles, variants, prices, compare-at prices, availability, and collections, plus the store's theme name and app hints and optional price-change tracking between runs, for ecommerce analysts, brands, and agencies that monitor competitors.**

$0.002 per product ($2 per 1,000) plus $0.01 per store, on every plan. Direct HTTP only: no login, no proxy, and no CAPTCHA solving.

## Who is it for?

- **Ecommerce and pricing analysts** tracking competitor prices, discounts, and stock across Shopify stores.
- **DTC brands** watching how rivals launch products and run sales.
- **Shopify agencies and app developers** finding stores by theme and spotting the apps they load.
- **Dropshippers and product researchers** exporting catalogs to compare assortments.
- **Market researchers** building product datasets by vendor, type, and tag.

## What data do you get?

Each store returns one store row, then one row per product.

| Field | Row | What it holds |
|-------|-----|---------------|
| `kind` | both | `store` or `product` |
| `store`, `storeUrl`, `myshopifyDomain` | both | Store domain, storefront URL, and `.myshopify.com` domain |
| `title`, `handle`, `productId`, `url` | product | Product title, handle, id, and product page URL |
| `vendor`, `productType`, `tags` | product | Catalog attributes |
| `publishedAt`, `updatedAt` | product | Product timestamps |
| `available`, `priceMin`, `priceMax`, `currency` | product | Availability and price range |
| `variantCount`, `variants` | product | Each variant's id, title, SKU, price, compare-at price, availability, and options |
| `priceChange`, `priceChanged` | product | Comparison with the last run, when tracking is on |
| `themeName` | product | Theme name, copied from the store row |
| `theme`, `themeStatus` | store | `Shopify.theme` details from the homepage |
| `appHints` | store | Script URLs that look like Shopify apps. Hints, not a verified install list |
| `collections`, `collectionCount`, `collectionsStatus` | store | Collection id, title, handle, and product count |
| `sourceStatus`, `decision`, `partial`, `ok`, `error`, `scrapedAt` | both | Status, change decision, partial flag, success flag, failure reason, timestamp |

Sample product row from the Actor's saved test catalog, with price tracking on:

```json
{
  "kind": "product",
  "store": "example.test",
  "title": "Wool Runner",
  "productId": "1001",
  "handle": "wool-runner",
  "vendor": "Example",
  "productType": "Shoes",
  "url": "https://example.test/products/wool-runner",
  "available": true,
  "priceMin": 98.0,
  "priceMax": 98.0,
  "currency": "USD",
  "variants": [
    {
      "variantId": "5001",
      "title": "8 / Natural",
      "sku": "WR-8",
      "price": 98.0,
      "compareAtPrice": 110.0,
      "available": true,
      "previousPrice": 90.0,
      "priceDelta": 8.0,
      "priceChanged": true
    }
  ],
  "priceChange": {
    "tracked": true,
    "changed": true,
    "variantsChanged": 1,
    "previousMin": 90.0,
    "previousMax": 90.0,
    "previousSeenAt": "2026-10-01T00:00:00+00:00",
    "reason": ""
  },
  "themeName": "Dawn",
  "sourceStatus": "found",
  "decision": "changed",
  "ok": true,
  "scrapedAt": "2026-11-03T12:00:00+00:00"
}
```

`decision` is `listed` when tracking is off, `new` for a product with no saved price, `changed` when a variant price moved, and `unchanged` when prices match.

## Input

```json
{
  "domains": ["allbirds.com", "https://www.gymshark.com"],
  "maxProductsPerStore": 50,
  "maxItems": 100,
  "trackPriceChanges": true
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `domains` | — | Up to 100 store hostnames or storefront URLs. `www.` and paths are dropped |
| `maxProductsPerStore` | 50 (max 1,000) | Products read per store |
| `maxItems` | 100 (max 5,000) | Product rows per run, across all stores |
| `trackPriceChanges` | false | Compare each variant price with the last run |
| `stateStoreName` | `shopify-store-state` | Named store that keeps the last seen prices. Use one per saved task |
| `delaySeconds` | 1 (max 10) | Pause between requests |
| `maxSpendUsd` | 5 (max 100) | Hard cap on what one run can charge |

The first tracked run has no saved prices, so every product is `new`. Later runs show what changed.

## How much does it cost?

Pay per event.

| Event | When it is charged | Price |
|-------|--------------------|-------|
| Product row (`product`) | A product is returned | $0.002 |
| Store profile (`store`) | A store's catalog was readable and its profile row is returned | $0.01 |

- **1 store with 100 products:** $0.01 + 100 × $0.002 = **$0.21**
- **10 stores with 100 products each (1,000 products):** 10 × $0.01 + 1,000 × $0.002 = **$2.10**

`blocked`, `unavailable`, `not_found`, `robots_disallowed`, `spend_capped`, and `error` rows are free. Apify adds its small per-run start event.

## Limits and data source

- **Source:** each store's public storefront feeds, `/products.json` and `/collections.json`, plus the homepage HTML for theme and app hints. No Admin API, no login, no checkout or customer data.
- **Shopify only:** a site that serves HTML instead of catalog JSON, including a password page, returns `unavailable`.
- **Theme and apps:** the theme comes from the homepage `Shopify.theme` object. App hints are script paths with `/apps/` or `/extensions/` and are not Shopify's installed-app list.
- **Pagination:** up to 250 products per page. `maxProductsPerStore` and `maxItems` stop further requests.
- **Prices:** rounded to cents. A change under one cent is not counted. Compare-at price is stored but is not the tracking baseline.
- **Blocks:** HTTP 401, 403, 429, or a challenge on a catalog URL saves one `blocked` row and stops the run. Products already read are kept. A blocked homepage only marks `themeStatus: "blocked"` and the run continues.
- **Robots:** robots.txt is checked for every host before any request.
- **Personal data:** product listings can still contain personal data a merchant chose to publish, which the GDPR and similar laws protect. Collect it only with a legitimate reason.

## FAQ

### How do I export all products from a Shopify store?

Add the store domain to `domains`, raise `maxProductsPerStore` and `maxItems` to cover the catalog, and run. Download the dataset as CSV or Excel.

### How do I track competitor price changes on Shopify?

Turn on `trackPriceChanges` and schedule the Actor daily. Each product row shows `priceChanged`, the previous price, and the price delta per variant.

### How do I tell which theme a Shopify store uses?

The store row's `theme` and every product row's `themeName` show the theme from the storefront's `Shopify.theme` object.

### Does it work on any Shopify store?

It works on stores whose public `/products.json` feed is open, which is the Shopify default. Password-protected stores and stores that block the feed return a free status row.

### Does this need a proxy?

No. The catalog feeds are public, so there is no proxy cost. A store that blocks the request is reported, not bypassed.

### What counts as a result?

One product row ($0.002) and one store profile ($0.01) per readable store.

## Integrations and output

- **Dataset:** store rows, product rows, then status rows. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has counts, spend, and one report per domain. Last seen prices live in the named store from `stateStoreName`.
- **Automation:** schedule daily price checks and send changes to Slack, Google Sheets, Airtable, Make, Zapier, or n8n.

## Related actors

- [App Store Reviews Scraper](https://apify.com/staticxviper/app-reviews): iOS App Store reviews for a brand's app.
- [Google Maps Business Leads](https://apify.com/staticxviper/google-business-lead-generation): a business's Google Maps phone, website, and rating.
- [ATS Jobs Feed](https://apify.com/staticxviper/ats-jobs): hiring signals from Greenhouse, Lever, Ashby, and Workable boards.

## Changelog

Release notes are on the **Changelog** tab of this page.
