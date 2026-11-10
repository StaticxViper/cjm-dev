# Changelog

## Unreleased

- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated.

## 0.1

- Package verified Chicago, Seattle, Austin, and Los Angeles building-permit feeds as an Actor.
- Charge `permit` only when a permit row is pushed. Direct requests are free.
- Apify Proxy only after a block. CAPTCHA only when that retry is still a challenge, `allowCaptcha` is true, and the spend cap covers the solve.
