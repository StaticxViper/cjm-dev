# Changelog

## Unreleased

- New `triggers` input. `liquor_license` adds NY State Liquor Authority pending applications and Colorado recently approved liquor licenses. `restaurant_inspection` adds NYC pre-permit initial inspections. The default stays `entity_formation`, so existing inputs return the same rows.
- New dataset fields `trigger`, `trigger_date`, and `status`. `type` holds the license or inspection type on trigger rows.
- Rows are interleaved across triggers before `maxResults` is applied. Rows dated after the run date are dropped.
- Trigger rows bill the same `business` event. States without a feed for a trigger return a free `unsupported` row.

- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated.

## 0.1

- Package the new-business entity feeds as an Actor. New York, Pennsylvania, and Colorado open-data rows are imported from the existing pipeline.
- Charge `business` for a returned entity and `enrichment` only when a website or email is found.
- Direct HTTP first. Apify Proxy datacenter only after a block. CAPTCHA only when that retry is still a challenge, `allowCaptcha` is true, and the spend cap covers the solve.
