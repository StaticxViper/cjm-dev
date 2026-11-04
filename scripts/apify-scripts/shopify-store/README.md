## What does Shopify Store Intel do?

**Shopify Store Intel** reads the public catalog of Shopify stores you list. For each domain it requests [`/products.json`](https://shopify.dev/docs/api/ajax/reference/product) and `/collections.json`, then reads the storefront homepage for `Shopify.theme` and script URLs that look like apps.

It does **not** log in, call the Admin API, rotate proxies, or solve CAPTCHAs. A store that answers HTTP 401, 403, or 429, or a challenge page, on those catalog URLs is saved as one `blocked` row and the run stops.

## Why use Shopify Store Intel?

Use it to watch a list of Shopify catalogs: product titles, variant prices, availability, collections, and a light read of the theme. Schedule a run when you want price changes against the previous push. Results go to an Apify dataset you can download or call from the API, with a `SUMMARY` record for the run.

This Actor stays on a direct connection. It will not spend money to get past a block.

## What data can Shopify Store Intel extract?

| Field | Where | What it is |
|-------|--------|------------|
| `title`, `handle`, `vendor`, `productType`, `tags` | product | Catalog text from `/products.json` |
| `variants` | product | Id, SKU, price, compare-at price, availability, options |
| `priceChange` | product | Set when tracking is on. `reason` is `no_prior` until a saved price exists |
| `collections` | store | Id, title, handle, and `productsCount` from `/collections.json` |
| `theme` | store | `Shopify.theme` from the homepage, when that script is present |
| `appHints` | store | Script URLs under `/apps/` or `/extensions/`. These are hints, not a verified install list |

Product rows also copy `themeName` so a product export still names the theme. App hints stay on the store row.

## How to scrape a Shopify store

1. Open the Actor and add store domains (`allbirds.com` or a full storefront URL).
2. Set `maxProductsPerStore` and `maxItems`. `maxItems` counts products only.
3. Turn on `trackPriceChanges` when you want each variant compared with the last pushed price in `stateStoreName`.
4. Run the Actor. Download the dataset as JSON, CSV, Excel, or HTML, or read it from the API tab.

The first tracked run has no prior prices. Prices of products that were pushed are saved either way, so the next run can compare.

## How much will it cost to scrape a Shopify store?

Pay per event from `.actor/pay_per_event.json`.

| Event | Price | When it is charged |
|-------|-------|--------------------|
| `product` (primary) | $0.002 | A product row is pushed |
| `store` | $0.01 | A store profile is pushed after `/products.json` returned JSON |

A store with 100 products is about $0.01 + 100 × $0.002 = $0.21, plus the platform start event. `blocked`, `unavailable`, `not_found`, `robots_disallowed`, `spend_capped`, and `error` rows are saved and not billed. There is no proxy event and no CAPTCHA event. `maxSpendUsd` stops the feed before a charge that would pass the cap. One store at the $0.01 minimum cap is the store profile only. The next product needs another $0.002.

## Input

See the input tab for the full form. `fixtures/INPUT.json` is the small smoke run:

```json
{
  "domains": ["allbirds.com"],
  "maxProductsPerStore": 2,
  "trackPriceChanges": false,
  "stateStoreName": "shopify-store-state",
  "maxItems": 2,
  "delaySeconds": 1,
  "maxSpendUsd": 1
}
```

- `domains` accepts a hostname or a storefront URL. A path is dropped. A leading `www.` is stripped. The same host twice is read once. At most 100 domains.
- `maxProductsPerStore` defaults to 50 (maximum 1,000). `maxItems` defaults to 100 (maximum 5,000) and counts product rows only. Later stores are not requested once `maxItems` is filled.
- `trackPriceChanges` compares variant prices with the named key-value store. Keys are `domain|productId|variantId`. The store keeps the latest pushed price, up to 200,000 keys.
- `delaySeconds` waits 1–2 seconds between requests. Requests run one at a time.
- `maxSpendUsd` defaults to 5 (minimum 0.01, maximum 100).

## Output

You can download the dataset as JSON, HTML, CSV, or Excel. One store row, then that store's product rows. Status rows follow. Key-value `SUMMARY` records counts, spend, and one report per domain.

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

`decision` is `listed` when tracking is off, `new` when tracking is on and no saved price exists, `changed` when a saved variant price differs, and `unchanged` when saved prices match. `priceChange` is null when tracking is off.

The store row uses `kind: "store"` and carries `theme`, `appHints`, and `collections`. `themeStatus: "blocked"` means the homepage was a challenge or an HTTP block. That does not stop the run. `themeStatus: "not_found"` means the HTML loaded and had no `Shopify.theme` object. `collectionsStatus: "not_found"` means `/collections.json` answered 404. The store and its products are still returned.

| sourceStatus | Meaning | Charged |
|--------------|---------|---------|
| `found` | A store profile or a product parsed from JSON | `store` or `product` |
| `blocked` | HTTP 401, 403, or 429, or a challenge page, on `/products.json` or `/collections.json`. The run stops | no |
| `unavailable` | HTML instead of catalog JSON, including a password page | no |
| `not_found` | HTTP 404 on the catalog URL | no |
| `robots_disallowed` | robots.txt disallows the catalog URL | no |
| `spend_capped` | The next charge did not fit under `maxSpendUsd` or the platform limit | no |
| `error` | Bad domain, invalid JSON, or a 5xx after one retry | no |

## Limitations

- Only public storefront JSON. The Admin API, checkout, and customer accounts are out of scope. `/meta.json` is not requested. It is not a stable public catalog route, and a 403 there would look like a block on a store whose `/products.json` is open.
- Theme and app hints come from the homepage. A theme that does not print `Shopify.theme`, or a homepage that answers 403 while `/products.json` is open, leaves `themeStatus` as `blocked` or `not_found`. App hints are script paths containing `/apps/` or `/extensions/`. They are not Shopify's installed-app list.
- A block on a later `/products.json` page keeps products already parsed, skips collections and the homepage for that store, pushes one `blocked` row, and does not request later domains. A block on `/collections.json` keeps the products and any collections already parsed, skips the homepage, and stops the same way.
- Pagination uses `limit` and `page`. Shopify's page size cap is 250. A page that repeats product ids already seen ends that catalog. `maxItems` and `maxProductsPerStore` stop further product requests.
- Variant prices are numbers rounded to cents. A change smaller than one cent is not a change. Compare-at price is stored and is not the baseline.
- The shared spend ledger counts whole cents, so this Actor uses a micro-dollar ledger. $0.002 would otherwise round to zero and the cap would never stop.

## Robots and terms

robots.txt is fetched once per host and evaluated with `scripts/lead_automation/crm_enrich_robots.py` (longest match, `User-agent: *`). A 4xx robots answer, including 403 and 429, means no rules (RFC 9309). A 5xx or a network failure skips that host. A robots disallow is not a block and is not retried through a proxy.

The catalog URLs are the public Ajax feeds a Shopify storefront serves without a token. Product text belongs to the merchant. Use it in line with Shopify's terms and the store's own terms. This Actor does not bypass a password page, a challenge, or a rate limit.

## Pricing

See the cost section above. Dataset items are not a charge event. Memory default is 512 MB (minimum 256, maximum 2048) and the default timeout is 1,800 seconds.

### Deviation from the template contract

The template keeps `headless`, `maxProxyCostUsd`, `allowCaptcha`, `proxyConfiguration`, and `proxyGroups`, and it retries a block once through Apify Proxy. This Actor drops those fields. It reads public JSON with plain HTTP, never launches a browser, and stops on a catalog block instead of spending to get past it. The run still finishes with exit 0 so the dataset and `SUMMARY` are saved. `SUMMARY.status` is `blocked` or `partial`.

A homepage challenge is recorded on the store row and does not end the run. Stopping there would drop catalogs whose `/products.json` is public and whose homepage is walled.

The Dockerfile uses `apify/actor-python:3.12` instead of the Playwright image. It leaves `WORKDIR` at `/usr/src/app` and sets `CJM_REPO_ROOT=/usr/src/app/platform_bundle`.

## Categories

Set in the Apify Console, not in `actor.json`. Suggested: E-commerce, Marketplace.

## FAQ, disclaimers, and support

Our Actors are ethical and do not extract private customer data such as orders, emails, or accounts. They only read public catalog JSON and public storefront HTML. You should be aware that a product listing can still contain personal data a merchant chose to publish, which is protected by the GDPR in the European Union and by other laws. Do not collect personal data unless you have a legitimate reason. If you are unsure, consult your lawyers.

Questions and bugs belong on the issue tracker. Programmatic runs use the API tab. A `blocked` row means the store refused the catalog request. Narrow the domain list or raise `delaySeconds`. Do not expect a proxy retry from this Actor.

## Local run

```bash
cd scripts/apify-scripts/shopify-store
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

`--purge` clears the default stores only. The named `shopify-store-state` store survives, so a later run with `trackPriceChanges` can see prices from products that were pushed.

Unit tests read fixtures only:

```bash
python -m pytest unittests/apify_scripts/test_shopify_store_actor.py -q
```

Publish with `APIFY_TOKEN` (`apify push`) only after a listing is requested. See `scripts/apify-scripts/README.md`.
