# Changelog

## Unreleased

- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated.

## 0.1

- Read SAM.gov Get Opportunities v2 (`api.sam.gov/opportunities/v2/search`) and USAspending contract awards (`api.usaspending.gov/api/v2/search/spending_by_award/`, award types A, B, C, D). Official APIs only.
- One row per notice or award with id, agency, title, NAICS, value, deadline, awardee, published contact, and URL. Dedupe on `(source, recordType, id)`, using the USAspending generated internal id when it is present.
- `samApiKey` is a secret input. It is sent only as the SAM.gov `api_key` query parameter and is redacted from result URLs, errors, the dataset, and `SUMMARY`. Awards do not use it. A missing key skips SAM.gov with one free `skipped` row and still reads awards.
- Charge `opportunity` ($0.008, primary) only when an opportunity row is pushed. Charge `award` ($0.008) only when an award row is pushed. $0.008 is $8 per 1,000 rows. The brief's $0.01 price was above that line. A lead is pushed only when that charge fits under `maxSpendUsd`. `maxItems` bounds the fetch. `maxSpendUsd` is applied when rows are pushed. If the platform charge raises, the row stays in the dataset, is not billed, and the feed stops.
- The Apify title is `Federal Contract Leads – SAM.gov & USAspending` (46 characters). Apify rejects a title longer than 63.
- Direct HTTP only. No proxy, no CAPTCHA solver, no browser. HTTP 401, 403, or 429 stops that source, pushes one `blocked` row, and the other source still runs. 5xx and network errors are retried once.
- SAM.gov `offset` is sent as a page index. A page that repeats ids already seen stops that query. `maxItems` caps successful rows and later pages are not requested.
- The CI fixture is awards-only (`fixtures/INPUT.json`): NAICS 541512, Virginia, 2024-01-01 through 2024-03-31, `maxItems` 2, no SAM key. `fixtures/budget.json` expects exactly 2 dataset rows so a status-only failure cannot pass the Docker smoke.
