# Changelog

## Unreleased

- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated.

## 0.1

- Package the new-business entity feeds as an Actor. New York, Pennsylvania, and Colorado open-data rows are imported from the existing pipeline.
- Charge `business` for a returned entity and `enrichment` only when a website or email is found.
- Direct HTTP first. Apify Proxy datacenter only after a block. CAPTCHA only when that retry is still a challenge, `allowCaptcha` is true, and the spend cap covers the solve.
