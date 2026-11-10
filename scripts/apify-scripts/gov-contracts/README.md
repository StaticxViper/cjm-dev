# Federal Contract Leads – SAM.gov & USAspending

**Federal Contract Leads returns open SAM.gov contract opportunities and past USAspending contract awards filtered by NAICS code, state, set-aside, and date, with agency, title, value, response deadline, awardee, and contracting contact, for GovCon business-development teams and small businesses bidding on federal work.**

$0.008 per opportunity or award ($8 per 1,000) on every plan. Official government APIs only: no proxy, no browser, and no CAPTCHA solving.

## Who is it for?

- **GovCon business-development and capture teams** building a pipeline of open solicitations by NAICS.
- **Small, 8(a), HUBZone, WOSB, and SDVOSB businesses** finding set-aside opportunities they qualify for.
- **Proposal writers and consultants** monitoring opportunities for several clients.
- **Teaming and subcontracting leads:** past award winners (`awardee`, `uei`) in your NAICS and state are prime partners to approach.
- **Market researchers** sizing federal spend by agency, NAICS, and state.

## What data do you get?

One dataset item per opportunity or award.

| Field | Type | What it holds |
|-------|------|---------------|
| `id` | string | SAM.gov notice id, or the USAspending award id |
| `recordType`, `source` | string | `opportunity` from `sam.gov`, or `award` from `usaspending.gov` |
| `agency`, `subAgency` | string | Contracting or awarding agency |
| `title` | string | Notice title or award description |
| `naics` | string | NAICS code |
| `value` | number | Award amount, when published |
| `deadline` | string | SAM.gov response deadline, or the award's period-of-performance end |
| `awardee`, `uei` | string | Awardee name and Unique Entity ID, when published |
| `contactName`, `contactEmail`, `contactPhone` | string | SAM.gov primary point of contact. Empty on award rows |
| `setAside` | string | Set-aside code, such as `SBA` or `WOSB` |
| `state` | string | Place of performance |
| `noticeType`, `solicitationNumber` | string | SAM.gov notice type and solicitation number |
| `postedDate`, `periodStart` | string | Posted date, and award start date |
| `url` | string | Official `sam.gov` or `usaspending.gov` page |
| `sourceStatus`, `decision`, `ok`, `error`, `scrapedAt` | | Status, row type, success flag, failure reason, timestamp |

Sample opportunity row from the Actor's saved SAM.gov fixture:

```json
{
  "id": "abc123notice",
  "recordType": "opportunity",
  "source": "sam.gov",
  "agency": "GENERAL SERVICES ADMINISTRATION.PUBLIC BUILDINGS SERVICE",
  "subAgency": "",
  "title": "Historic Office Renovation",
  "naics": "236220",
  "value": 800620,
  "deadline": "2024-03-15T17:00:00-04:00",
  "awardee": "D.G. Beyer, Inc.",
  "contactName": "Casey Officer",
  "contactEmail": "co@example.com",
  "contactPhone": "2025550100",
  "uei": "025114695AST",
  "setAside": "SBA",
  "state": "WI",
  "noticeType": "Solicitation",
  "solicitationNumber": "47PF0018R0023",
  "postedDate": "2024-02-01",
  "periodStart": "",
  "url": "https://sam.gov/opp/abc123notice/view",
  "sourceStatus": "ok",
  "decision": "opportunity",
  "ok": true,
  "error": "",
  "scrapedAt": "2026-11-03T12:00:00+00:00"
}
```

## Input

```json
{
  "sources": ["opportunities", "awards"],
  "naics": ["541512", "541519"],
  "state": "VA",
  "setAside": "SBA",
  "postedFrom": "2026-08-01",
  "postedTo": "2026-10-31",
  "maxItems": 50,
  "samApiKey": "YOUR_SAM_GOV_API_KEY"
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `sources` | both | `opportunities` (SAM.gov), `awards` (USAspending), or both |
| `naics` | — | Up to 10 codes, 2 to 6 digits |
| `state` | all states | 2-letter USPS code. Set `naics`, `state`, or both |
| `setAside` | any | One SAM.gov set-aside code: `SBA`, `8A`, `HZC`, `SDVOSBC`, `WOSB`, `EDWOSB`, and others |
| `postedFrom`, `postedTo` | last 90 days | Date window (`YYYY-MM-DD`), up to 366 days |
| `maxItems` | 50 (max 200) | Rows returned per run |
| `samApiKey` | — | Your free SAM.gov public API key. Required for opportunities. Stored as a secret and never written to the output |
| `delaySeconds` | 1 (max 10) | Pause between requests |
| `maxSpendUsd` | 5 (max 100) | Hard cap on what one run can charge |

Without `samApiKey`, opportunities are skipped with one free `skipped` row and awards still run.

## How much does it cost?

Pay per event.

| Event | When it is charged | Price |
|-------|--------------------|-------|
| SAM.gov opportunity (`opportunity`) | An opportunity row is returned | $0.008 |
| USAspending award (`award`) | An award row is returned | $0.008 |

- **100 opportunities or awards:** 100 × $0.008 = **$0.80**
- **1,000 opportunities or awards:** 1,000 × $0.008 = **$8.00**

`skipped`, `not_found`, `blocked`, `robots`, `spend_capped`, and `error` rows are free. Apify adds its small per-run start event.

## Limits and data source

| Source | API | What is read |
|--------|-----|--------------|
| SAM.gov | Get Opportunities API v2 (`api.sam.gov`) | Open notices by NAICS, state, set-aside, and posted date |
| USAspending | Spending by Award API (`api.usaspending.gov`) | Prime contract awards (types A, B, C, D) by NAICS, place of performance, and action date |

- **SAM.gov key:** SAM.gov requires each caller's own free API key. Daily limits depend on your SAM.gov account role. This Actor does not share a key.
- **Awards:** prime contract awards only, sorted by amount, largest first. Grants and IDVs are not included. USAspending does not publish a contact person, so contact fields are empty on award rows.
- **Volume:** up to 5 pages of 100 records per query and 200 rows per run.
- **Matching:** SAM.gov matches each NAICS code exactly. USAspending matches codes that start with the value, so `5415` covers every 5415xx code.
- **Blocks:** on HTTP 401, 403, or 429 that source saves one `blocked` row and stops. The other source still runs. No proxy retry. A 5xx is retried once.
- **Public data:** all fields come from official federal APIs published for public use. Contacts are copied only when SAM.gov publishes them.

## FAQ

### How do I find federal contracts for my NAICS code?

Put your NAICS codes in `naics`, add your SAM.gov API key, and run with `sources: ["opportunities"]`. Each row is an open notice with its agency, deadline, set-aside, and contracting officer.

### How do I get a SAM.gov API key?

Sign in at SAM.gov, open **Account Details**, and request a public API key. It is free. Paste it into `samApiKey`.

### Can I search small-business set-asides only?

Yes. Set `setAside` to a code such as `SBA` (total small business), `8A`, `HZC` (HUBZone), `SDVOSBC`, or `WOSB`. SAM.gov accepts one set-aside per request.

### Who won past contracts in my market?

Run `sources: ["awards"]` with your NAICS and state. Each row has the awardee, UEI, amount, agency, and period of performance, which are useful for teaming and competitor research.

### Does this need a proxy?

No. SAM.gov and USAspending are official public APIs, so there is no proxy cost.

### What counts as a result?

One opportunity or award row. A skipped source, an empty search, and errors are free.

## Integrations and output

- **Dataset:** one row per opportunity or award plus status rows. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has counts (`found`, `billedOpportunities`, `billedAwards`, `skipped`, `blocked`, `errors`, `mergedDuplicates`, `truncated`), the filters, spend, and a report per source. It never contains your API key.
- **Automation:** schedule it daily for new solicitations and send them to Slack, email, Google Sheets, a CRM, Make, Zapier, or n8n.

## Related actors

- [New Business Leads](https://apify.com/staticxviper/new-business): newly registered LLCs and corporations by state.
- [Contractor License Lookup](https://apify.com/staticxviper/contractor-license): verify a California contractor's license.
- [ATS Jobs Feed](https://apify.com/staticxviper/ats-jobs): open jobs from Greenhouse, Lever, Ashby, and Workable boards.

## Changelog

Release notes are on the **Changelog** tab of this page.
