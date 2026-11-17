# Changelog

## 0.1

- Read local bid, RFP, and ITB rows from two official open-data files. Los Angeles `data.lacity.org` `hf3r-utnq` (RAMP open and amended bids, CC0) and Montgomery County `data.montgomerycountymd.gov` `eeq6-nnwe` (solicitations issued in the past 7 years). Checked 2026-11-16. Both `robots.txt` files allow `/resource/*.json` with Crawl-delay 1. OData, CSV exports, and procurement-portal pages are not requested.
- Any other source id returns one free `unsupported` row. SAM.gov, Bonfire, BidNet, PlanetBids, and DemandStar are not fetched.
- A source flagged as needing a Socrata app token is skipped when `appToken` is empty. The other sources still run. Neither verified feed requires a token.
- One row per solicitation. Fields are source, source URL, agency, title, solicitation id, category, NAICS when the file has it, state, city, posted date, due date, estimated value when published, bid status, description, and contact name or email only when the file publishes them. These two files do not publish NAICS, a dollar estimate, or an email. Los Angeles has no description column. Montgomery County publishes a department contact name.
- Charge `opportunity` at $0.008 ($8 per 1,000) only when a bid row is pushed, and only when that charge fits under `maxSpendUsd`. The platform start fee is `apify-actor-start` at $0.00005. Status rows are free.
- `newSinceLastRun` reads a named key-value store. If that record cannot be read, the run fetches nothing and bills nothing. A missing record is a first run. Only charged bids are remembered.
- The date window is the posted or issuance date, last 14 days when empty, at most 92 days. Pages are SODA JSON with `$limit` of 100. The body is streamed and the read stops at `maxItems`. A response past 2 MB stops.
- The CI fixture is two Montgomery County solicitations issued on 2023-03-23, `maxItems` 2. `fixtures/budget.json` expects exactly 2 dataset rows.
- The Apify title is `Local Government Bids – State & City RFP Leads` (46 characters).
- Icon is `.actor/icon.png`, a purple liquid-glass bid sheet. It is not the MV logo.
