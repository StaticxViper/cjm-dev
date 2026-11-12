# Changelog

## Unreleased

- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated.

## 0.2

- Add verified New York City (DOB NOW initial permits), New Orleans, and Cincinnati feeds. Seven cities in total.
- New `permit_category` (primary) and `permit_categories` (all matches) fields: `solar`, `pool`, `roof`, `siding`, `deck`, `new_construction`, `remodel`, or `other`, in that priority order.
- New `remodel` permit type: remodel, renovation, alteration, addition, kitchen, bath, interior.
- `newSinceLastRun` skips permits charged by an earlier run. Seen `(source, permit_id)` keys live in the named key-value store `stateStoreName` (default `permits-state`). Skipped permits are not billed and do not count toward `maxItems`. If that store cannot be read, the run pushes one `error` row and charges nothing.
- `maxProxyCostUsd` now defaults to 0. A block pushes one `blocked` row and the run exits; set a proxy budget to opt into the single proxy retry.
- ArcGIS epoch-millisecond dates are read as UTC days.
- `permit` Store tiers: FREE $0.012, BRONZE $0.010, SILVER $0.009, GOLD/PLATINUM/DIAMOND $0.008.

## 0.1

- Package verified Chicago, Seattle, Austin, and Los Angeles building-permit feeds as an Actor.
- Charge `permit` only when a permit row is pushed. Direct requests are free.
- Apify Proxy only after a block. CAPTCHA only when that retry is still a challenge, `allowCaptcha` is true, and the spend cap covers the solve.
