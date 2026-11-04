# Changelog

## 0.1

- Read public `/products.json` (paginated) and `/collections.json` for a list of store domains. Homepage HTML is read only for `Shopify.theme` and script-src app hints. `/meta.json` is not requested.
- One store row per catalog that returned product JSON, and one product row with variants, prices, availability, and price change versus the named key-value store when tracking is on and a prior price exists.
- Dedupe on store plus product id. `maxItems` caps product rows and stops later requests. `maxProductsPerStore` caps each catalog.
- Charge `product` ($0.002) only for a pushed product and `store` ($0.01) only for a pushed store profile. A row is pushed only when its charge fits under `maxSpendUsd`.
- Direct HTTP only. No proxy and no CAPTCHA solver. HTTP 401, 403, or 429, or a challenge page, on `/products.json` or `/collections.json` pushes one `blocked` row and stops the run. A homepage challenge is recorded on the store and does not stop the run.
