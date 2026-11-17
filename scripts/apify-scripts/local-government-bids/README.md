# Local Government Bids – State & City RFP Leads

**Local Government Bids returns city and county RFP, IFB, and ITB leads from official open-data feeds, with the agency, posted date, due date, and solicitation link, for contractors and GovCon teams who need local bids.**

$0.008 per bid ($8 per 1,000) on every plan, plus a $0.00005 run start. Official public files only. No proxy and no CAPTCHA solving.

This is not SAM.gov and it is not a federal contract search. Federal opportunities and USAspending awards are in [Federal Contract Leads](https://apify.com/staticxviper/gov-contracts).

## Who is it for?

- **Local contractors** looking for city and county public works, facilities, and landscaping bids.
- **IT and services vendors** who want municipal RFP and ITB leads without a portal login.
- **GovCon business-development teams** who already track federal SAM.gov work and need the state and local half.
- **Bid coordinators** who want a scheduled municipal bid feed they can drop into a spreadsheet or CRM.

## What data do you get?

One dataset item per solicitation. Status rows are saved and are not billed.

| Field | Type | What it holds |
|-------|------|---------------|
| `source`, `sourceUrl` | string | Open-data host, and the opportunity link when the file publishes one |
| `agency`, `title`, `solicitationId` | string | Department, title, and the city's or county's solicitation number |
| `category`, `naics` | string | Bid type such as RFP or IFB. NAICS only when the file has it |
| `state`, `city` | string | Postal state. City when the feed is a single city. Countywide rows leave city blank |
| `postedDate`, `dueDate` | string | `YYYY-MM-DD`. The date filter uses the posted date, not the due date |
| `estimatedValue` | string | Dollar estimate when the file publishes one. Empty for the feeds in this version |
| `status` | string | The bid status on a lead, such as `Open` or `Closed`. On a free row: `unsupported`, `skipped`, `not_found`, `blocked`, `robots`, `spend_capped`, or `error` |
| `description` | string | Text the file publishes, cut at 500 characters. Empty when the file has no description |
| `contactName`, `contactEmail` | string | Copied only when that file publishes them. They are not looked up |
| `ok`, `decision`, `error`, `scrapedAt` | | Success flag, `opportunity` on a lead, failure reason, timestamp |

Feeds in this version: **Los Angeles** open bids and **Montgomery County, Maryland** solicitations.

Sample Los Angeles open bid from the public file (posted 2026-11-16):

```json
{
  "source": "data.lacity.org",
  "sourceUrl": "https://www.rampla.org/s/opportunity-details?id=006Ql00000ofgmUIAQ",
  "agency": "Water & Power",
  "title": "144510 VACUUM VALVES, AIR, COMBINATION, ROSCOE TL UNIT 2",
  "solicitationId": "233104",
  "category": "IFB - Invitation for Bid; Commodity",
  "naics": "",
  "state": "CA",
  "city": "Los Angeles",
  "postedDate": "2026-11-16",
  "dueDate": "2026-12-02",
  "estimatedValue": "",
  "status": "Open",
  "description": "",
  "contactName": "",
  "contactEmail": "",
  "decision": "opportunity",
  "ok": true,
  "error": "",
  "scrapedAt": "2026-11-16T18:00:00+00:00"
}
```

## Input

The fast Try input is Montgomery County, the last 14 days, and `maxItems: 5`.

```json
{
  "sources": ["montgomery_solicitations"],
  "maxItems": 5
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `sources` | `["montgomery_solicitations"]` (max 10) | Also `los_angeles_ramp`. Any other id returns one free `unsupported` row |
| `state` | empty | Two-letter code. A source in another state is a free `skipped` row and is not fetched |
| `keywords` | empty | Up to 8 words. Quotes and other symbols are removed before the query |
| `dateFrom`, `dateTo` | last 14 days | Posted or issuance date, inclusive, up to 92 days. Set both or leave both empty |
| `maxItems` | 25 (max 500) | Successful bids. The form's Try value is 5. Status rows do not count |
| `newSinceLastRun` | off | Skip bids this Actor already charged. A missing store is a first run |
| `stateStoreName` | `local-government-bids-state` | Named key-value store for that memory |
| `delaySeconds` | 1 (max 10) | Pause between requests. Both portals ask for a one-second crawl delay |
| `maxSpendUsd` | 0.50 (max 100) | Hard cap on the bid charge for this run |
| `appToken` | empty | Optional Socrata token. These two feeds do not need one |

Los Angeles is the current open and amended list, so a last-14-days window is a useful first run. Montgomery County keeps about seven years of issued solicitations, including closed ones. Filter `status` after the run when you only want `Active`.

## How much does it cost?

Pay per event. You pay for bids that are pushed. You do not pay for a source this Actor cannot read.

| Event | When it is charged | Price |
|-------|--------------------|-------|
| Actor start (`apify-actor-start`) | Once, when the run starts | $0.00005 |
| Local bid (`opportunity`) | A bid row is pushed | $0.008 |

- **100 bids:** 100 × $0.008 = **$0.80**, plus the $0.00005 start.
- **1,000 bids:** 1,000 × $0.008 = **$8.00**, plus the $0.00005 start.

One run accepts at most 500 bids ($4.00). The default `maxSpendUsd` of $0.50 covers 62 bids, which is more than the default 25. Raise it before you ask for a large pull. `unsupported`, `skipped`, `not_found`, `blocked`, `robots`, `spend_capped`, and `error` rows are free.

If these local bid leads were useful, a short Apify Store rating helps other contractors find this feed.

## Limits and data source

| Source id | File | What it is |
|-----------|------|------------|
| `los_angeles_ramp` | [RAMP Open Bid Opportunities](https://data.lacity.org/City-Infrastructure-Service-Requests/RAMP-Open-Bid-Opportunities/hf3r-utnq) (`hf3r-utnq`) | City of Los Angeles open and amended bids. Public domain (CC0). No description, contact, NAICS, or estimate column |
| `montgomery_solicitations` | [Solicitations](https://data.montgomerycountymd.gov/Government/Solicitations/eeq6-nnwe) (`eeq6-nnwe`) | Montgomery County, Maryland. Active and closed solicitations issued in the past 7 years. A department contact name when the county filled it in. No email, NAICS, or estimate |

Both portals allow `/resource/*.json` and ask for a one-second crawl delay. The OData paths are disallowed and are not called. Checked 2026-11-16.

The data made available here has been modified for use from its original source, which is Montgomery County, Maryland ("the County"). THE COUNTY MAKES NO REPRESENTATIONS OR WARRANTIES AS TO THE COMPLETENESS, ACCURACY, OR TIMELINESS OF ANY DATA. THE COUNTY EXPRESSLY DISCLAIMS ALL WARRANTIES, WHETHER EXPRESS OR IMPLIED, INCLUDING ANY IMPLIED WARRANTIES OF MERCHANTABILITY OR FITNESS FOR A PARTICULAR PURPOSE. THE COUNTY MAKES NO REPRESENTATION OR WARRANTY AS TO THE WEBSITE OR APPLICATION USING DATA DRAWN FROM DATA.MONTGOMERYCOUNTYMD.GOV OR FOR THE USEFULNESS OR INTEGRITY OF THE WEB SITE OR APPLICATION. The data is subject to change and possible deletion, temporarily or permanently. It is understood that the information contained in the web feed is being used at one's own risk.

- **Due dates go stale.** An addendum can move a deadline after this run. Schedule the Actor on the mornings you bid, and open `sourceUrl` before you submit. Los Angeles drops a bid from this file after it leaves the open list. Montgomery County's file is updated daily and still lists closed solicitations.
- **Not in this version:** SAM.gov, Bonfire, BidNet, PlanetBids, DemandStar, and any vendor login. Those return `unsupported` or are simply not called. This Actor does not open the RAMP or county web pages behind `sourceUrl`.
- **Coverage:** two feeds. A city or state that is not Los Angeles or Montgomery County is not in v1.
- **Pages:** each request asks for at most 100 JSON rows and the body is streamed. The read stops at `maxItems`. A full-file CSV is never downloaded. A single response is capped at 2 MB.
- **Blocks:** HTTP 401, 403, or 429 on a source saves one free `blocked` row and the other source still runs. There is no proxy retry.
- **Contacts:** a name or email is copied only from a column the official file already fills. Nothing is appended.
- **App token:** leave `appToken` empty. If a later feed requires one and the token is missing, that feed is a free `skipped` row and the run continues.

## FAQ

### Where are local government bids published?

On city and county open-data files and on the procurement page linked from each row. This Actor reads the official JSON for Los Angeles open bids and Montgomery County solicitations. It does not log in to a bid board.

### Is this a SAM.gov scraper?

No. SAM.gov is federal. Use [Federal Contract Leads](https://apify.com/staticxviper/gov-contracts) for SAM.gov opportunities and USAspending awards. Use this Actor for city and county bids.

### How do I get city RFP leads?

Set `sources` to `los_angeles_ramp` for Los Angeles, or `montgomery_solicitations` for Montgomery County RFP, IFB, and informal solicitations. Leave the dates empty for bids posted in the last 14 days. Add a keyword such as `landscaping` or `software` when you want a narrower list.

### What is a state procurement or municipal bid feed?

A scheduled pull of official solicitation rows: title, agency, solicitation number, posted date, and due date. This version is Los Angeles and Montgomery County. Other states return a free `unsupported` row until an official JSON feed is added.

### How do I search a public works bid list or a county ITB?

Put the trade in `keywords` and the postal code in `state`. An ITB or IFB shows up in `category` when the file labels it that way. Montgomery County uses `IFB` and `RFP`. Los Angeles uses labels such as `IFB - Invitation for Bid`.

### Does this need a proxy?

No. These are official public open-data files, so a blocked response stops that source instead of retrying through a proxy.

### What counts as a result?

One bid row. An unsupported source, a state that does not match, an empty window, a block, and an error are free.

### How often should I refresh due dates?

Re-run on the days you plan to bid. The due date in a row is whatever the file said at request time. Addenda are not a separate feed.

## Integrations and output

- **Dataset:** one row per bid, plus status rows. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has counts (`found`, `billedOpportunities`, `skippedSeen`, `unsupported`, `skipped`, `notFound`, `blocked`, `errors`, `truncated`), the date window, spend, and a report per source. It never contains an app token. After a run that pushed at least one bid, `SUMMARY.reviewAsk` asks for a Store rating.
- **Schedule:** run weekday mornings and send the dataset to Slack, email, Google Sheets, a CRM, Make, Zapier, or n8n.
- **API:** start a run from the API tab with the same input.

## Related actors

- [Federal Contract Leads](https://apify.com/staticxviper/gov-contracts): SAM.gov opportunities and USAspending awards. The federal complement to this city and county feed.
- [Building Permits](https://apify.com/staticxviper/permits): new city building permits for contractors.
- [Contractor License Lookup](https://apify.com/staticxviper/contractor-license): public contractor license records.
- [Home Services Leads](https://apify.com/staticxviper/home-services): local home-service businesses.

## Changelog

Release notes are on the **Changelog** tab of this page.
