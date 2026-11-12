# Contractor License Lookup – Verify License Status (CA)

**Contractor License Lookup checks a California contractor license by license number or business name with the official CSLB license check, and returns status, classification, issue and expiry dates, bond, insurance, and address, for homeowners, general contractors, insurers, and lead-gen teams who need to verify a contractor fast.**

$0.008 per found license ($8 per 1,000) on the free tier, lower on paid Apify plans. A lookup that finds nothing is free.

## Who is it for?

- **General contractors and property managers** verifying subcontractors before a job.
- **Insurance carriers, agents, and surety bond writers** checking license status, bond, and workers' comp exemption.
- **Home-improvement marketplaces and lead sellers** screening contractors before listing them.
- **Lenders and title companies** confirming the contractor on a renovation loan.
- **Lead-gen teams** pulling licensed contractors by trade classification in California.

## What data do you get?

One dataset item per found license, or one status row when nothing is found.

| Field | Type | What it holds |
|-------|------|---------------|
| `state` | string | State searched |
| `license_no` | string | License number |
| `name` | string | Business name on the license |
| `status` | string | The board's license status, such as `CLEAR` |
| `class` | string | Classification codes, such as `B` (General Building) |
| `issue_date`, `expiry_date` | string | Dates as the board publishes them |
| `bond` | string | Contractor bond surety and amount |
| `insurance` | string | Workers' compensation coverage, or `Exempt` |
| `address` | string | Business address of record |
| `source_url` | string | The board page the record came from |
| `sourceStatus` | string | `found`, `not_found`, `unsupported`, `captcha`, `robots_disallowed`, or `error` |
| `ok`, `error`, `scrapedAt` | | Success flag, failure reason, timestamp |

Sample found row (shape only, values are not a live record):

```json
{
  "state": "CA",
  "license_no": "1000001",
  "name": "NORTHWIND BUILDERS LLC",
  "status": "CLEAR",
  "class": "B",
  "issue_date": "01/10/2015",
  "expiry_date": "01/31/2027",
  "bond": "Contractor: SURETY EXAMPLE 15000",
  "insurance": "Exempt",
  "address": "100 Example St, Sacramento, CA, 95814",
  "source_url": "https://www.cslb.ca.gov/onlineservices/dataportal/ContractorList",
  "sourceStatus": "found",
  "ok": true,
  "error": "",
  "scrapedAt": "2026-10-24T20:00:00+00:00"
}
```

## Input

```json
{
  "state": "CA",
  "licenseNo": "1000001",
  "name": "",
  "trade": "",
  "maxResults": 25
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `state` | required | `CA` is fully supported. `AZ`, `NJ`, and `PA` return a status row, see Limits |
| `licenseNo` | — | Exact license number. Spaces and leading zeros are ignored |
| `name` | — | Business name. Punctuation and suffixes like LLC are ignored |
| `trade` | — | Classification code (`B-1` and `B1` are the same) or class description words |
| `maxResults` | 25 (max 50) | Licenses returned per run |
| `maxRequests` | 4 (max 8) | Board requests per run, including robots.txt |
| `delaySeconds` | 2 (max 10) | Pause between requests. Keep it at 2 or higher |

Set `licenseNo`, `name`, `trade`, or a mix. When more than one is set, every one must match.

## How much does it cost?

Pay per event. You pay only when a license is found.

| Event | Free tier | Bronze | Silver | Gold and up |
|-------|-----------|--------|--------|-------------|
| Found license (`license`) | $0.008 | $0.007 | $0.006 | $0.005 |

- **100 license checks, all found:** 100 × $0.008 = **$0.80**
- **1,000 license checks, all found:** 1,000 × $0.008 = **$8.00** (as low as $5.00 on Gold)

`not_found`, `unsupported`, `captcha`, `robots_disallowed`, and `error` rows are free. Apify adds its small per-run start event.

## Limits and data source

| State | Board | Result |
|-------|-------|--------|
| CA | Contractors State License Board (CSLB) | Full lookup through the official Check a License form, then the license detail page |
| AZ | Registrar of Contractors | Reads the public "All Current Contractors" CSV when the posting page is served. A Cloudflare challenge returns `captcha` |
| NJ | Department of Community Affairs | Returns `unsupported`. The builder page now links a service portal that does not return records anonymously, and that portal is not opened |
| PA | Attorney General, Home Improvement Consumer Protection Act | Returns `captcha`. The HIC search loads Cloudflare Turnstile, and the form is not submitted. Pennsylvania has no statewide general-contractor license |

- **Lookups:** a license-number or name check is a few HTML pages and does not download the statewide file. A trade-only search streams the CSLB master file and stops at `maxResults`. That file omits cancelled, revoked, and expired licenses.
- **`not_found`:** means the current board record has no match. It is not proof a license never existed.
- **No bypassing:** no browser, no proxy rotation, and no CAPTCHA solving. A challenged or closed portal returns one free status row.
- **Robots:** robots.txt is checked for every host before any request.
- **Out of scope:** sheriff-sale, foreclosure, and probate records. Pennsylvania PALS and municipal licenses.
- **Terms:** CSLB recommends Instant License Check for the newest status before you rely on a record. Registration under Pennsylvania's Home Improvement Consumer Protection Act is not an endorsement by the Attorney General.

## FAQ

### How do I verify a California contractor license?

Set `state` to `CA` and `licenseNo` to the license number, then run. The row shows the CSLB status, classification, expiry date, bond, and workers' comp insurance.

### Can I look up a contractor by business name?

Yes. Put the business name in `name`. Suffixes like LLC and Inc. and punctuation are ignored when names are compared.

### How do I find every licensed roofer or electrician in California?

Use `trade` with the classification code, such as `C-39` for roofing or `C-10` for electrical, and set `maxResults`. Results come from the CSLB master file of active licenses.

### Which states are supported?

California is fully supported. Arizona works when its posting page is not behind a challenge. New Jersey and Pennsylvania return a free status row because their portals are closed to anonymous lookups or protected by a CAPTCHA.

### What counts as a result?

One found license. `not_found`, `unsupported`, and `captcha` rows are free.

### Does this need a proxy?

No. The CSLB lookup answers direct, so there is no proxy cost.

## Integrations and output

- **Dataset:** one row per license or status. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has `pushed`, `found`, `notFound`, `unsupported`, `captcha`, billed counts, and `truncated`.
- **Automation:** call it from the Apify API inside an onboarding or vetting workflow, or through Make, Zapier, n8n, or Google Sheets.

## Related actors

- [Building Permits Scraper](https://apify.com/staticxviper/permits): recent permits with the contractor who pulled them.
- [Home Services Leads](https://apify.com/staticxviper/home-services): local contractors by niche and area, with emails and lead scores.
- [Google Maps Business Leads](https://apify.com/staticxviper/google-business-lead-generation): a contractor's phone, website, and Google rating.

## Changelog

Release notes are on the **Changelog** tab of this page.
