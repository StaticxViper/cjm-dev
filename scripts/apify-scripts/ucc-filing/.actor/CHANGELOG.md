# Changelog

## 0.1

- Read new commercial UCC filings from two public-domain open-data files: Connecticut `data.ct.gov` `xfev-8smz` (active liens, commercial `ORIG FIN STMT` / `OFS` only) and Oregon `data.oregon.gov` `snfi-f79b` (UCC filings entered last month). Checked 2026-11-16. Both `robots.txt` files allow `/resource/*.json` with Crawl-delay 1. OData, CSV exports, and portal search are not requested.
- Colorado `wffy-3uut` has filing dates and types and no party names, so it is unsupported. Florida Sunbiz, New Jersey, and Kentucky's paid bulk file are unsupported. Any other state returns one free `unsupported` row.
- One row per filing. Connecticut and Oregon party rows are folded together. Fields are state, filing number, UCC-1 or UCC-3, filing date, lapse date, debtor, secured party, addresses, collateral when the file has it, source, and source URL. These two files do not publish collateral text, so that field is empty. A lapse date of year 9999 is treated as no lapse date. Names and addresses are passed through. Nothing is enriched.
- Charge `filing` at $0.008 ($8 per 1,000) only when a filing row is pushed, and only when that charge fits under `maxSpendUsd`. The platform start fee is `apify-actor-start` at $0.00005. Status rows are free.
- `newSinceLastRun` reads a named key-value store. If that record cannot be read, the run fetches nothing and bills nothing. A missing record is a first run. Only charged filings are remembered.
- Pages are SODA JSON with `$limit` of 100. The body is streamed and the read stops at `maxItems`. A response past 2 MB stops. A statewide CSV is never requested.
- The CI fixture is Connecticut commercial UCC-1 filings accepted on 2024-06-03, `maxItems` 2. `fixtures/budget.json` expects exactly 2 dataset rows.
- The Apify title is `UCC Filing Leads – New UCC-1 Debtor Feed` (41 characters).
- Icon is `.actor/icon.png`, a purple liquid-glass document. It is not the MV logo.
