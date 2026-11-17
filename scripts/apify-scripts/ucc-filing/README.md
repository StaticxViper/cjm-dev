# UCC Filing Leads – New UCC-1 Debtor Feed

**UCC Filing Leads returns new UCC-1 financing statements from the Connecticut and Oregon Secretary of State open-data files, with the debtor, secured party, filing date, and lapse date, for MCA shops, equipment lenders, and B2B sellers who watch fresh commercial filings.**

$0.008 per filing ($8 per 1,000) on every plan, plus a $0.00005 run start. Official public files only. No proxy and no CAPTCHA solving.

These are public commercial filings. This is not a credit report, and it does not skip-trace, append phones, or append emails.

## Who is it for?

- **MCA and alternative lenders** watching for a business that just pledged collateral.
- **Equipment finance and leasing teams** looking for a new UCC-1 in their states.
- **B2B sellers** who treat a fresh financing statement as a timing signal.
- **Collections and portfolio teams** tracking continuations and terminations (`UCC-3`) on commercial filings.
- **Researchers** who want the Secretary of State file, not a 50-state portal scraper.

## What data do you get?

One dataset item per filing. Several debtor or secured-party lines in the state file are folded into that one row.

| Field | Type | What it holds |
|-------|------|---------------|
| `state` | string | `CT` or `OR` on a filing. The code you asked for on a status row |
| `filingNumber` | string | State filing number |
| `filingType` | string | `UCC-1` or `UCC-3` |
| `filingDate`, `lapseDate` | string | `YYYY-MM-DD`. A lapse year of 9999 is left blank |
| `debtorName`, `debtorAddress` | string | Passed through from the filing. Several names are joined with `; ` |
| `securedPartyName`, `securedPartyAddress` | string | Passed through from the filing |
| `collateral` | string | Collateral text when the file has it, cut at 2,000 characters. Connecticut and Oregon's open files do not include it, so this is empty |
| `source`, `sourceUrl` | string | `data.ct.gov` or `data.oregon.gov`, and the public record or dataset page |
| `status` | string | `ok` on a filing. `unsupported`, `not_found`, `blocked`, `robots`, `spend_capped`, or `error` on a free status row |
| `ok`, `decision`, `error`, `scrapedAt` | | Success flag, row type, failure reason, timestamp |

Supported states in this version: **Connecticut** and **Oregon**.

Sample Connecticut UCC-1 from the public file (filed 2026-11-14):

```json
{
  "state": "CT",
  "filingNumber": "0005421756",
  "filingType": "UCC-1",
  "filingDate": "2026-11-14",
  "lapseDate": "2031-11-14",
  "debtorName": "American Poly Concrete Floor Refinishing LLC",
  "debtorAddress": "214 Camp Moween Rd, Lebanon, CT 06249",
  "securedPartyName": "Sheila Rittman",
  "securedPartyAddress": "210 Mooreland Rd, Berlin, CT 06037",
  "collateral": "",
  "source": "data.ct.gov",
  "sourceUrl": "https://data.ct.gov/Business/Uniform-Commercial-Code-UCC-Lien-Filings/xfev-8smz",
  "status": "ok",
  "decision": "filing",
  "ok": true,
  "error": "",
  "scrapedAt": "2026-11-16T18:00:00+00:00"
}
```

## Input

The fast Try input is Connecticut, the last 7 days, `filingTypes: ["UCC-1"]`, and `maxItems: 5`.

```json
{
  "states": ["CT"],
  "filingTypes": ["UCC-1"],
  "maxItems": 5
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `states` | `["CT"]` (max 10) | Verified: `CT`, `OR`. Any other code returns one free `unsupported` row |
| `dateFrom`, `dateTo` | last 7 days | `YYYY-MM-DD`, inclusive, up to 92 days. Set both or leave both empty |
| `filingTypes` | `["UCC-1"]` | `UCC-1`, `UCC-3`, or both |
| `maxItems` | 25 (max 500) | Successful filings. The form's Try value is 5. Status rows do not count |
| `newSinceLastRun` | off | Skip filings this Actor already charged. A missing store is a first run |
| `stateStoreName` | `ucc-filing-state` | Named key-value store for that memory |
| `delaySeconds` | 1 (max 10) | Pause between requests. Both portals ask for a one-second crawl delay |
| `maxSpendUsd` | 0.50 (max 100) | Hard cap on the filing charge for this run |

Oregon's official file is titled "UCC List of Filings Entered Last Month." A last-7-days run returns a free `not_found` row for Oregon unless that month overlaps the window. Set `dateFrom` and `dateTo` to the previous month when you want Oregon.

## How much does it cost?

Pay per event. You pay for filings that are pushed. You do not pay for a state this Actor cannot read.

| Event | When it is charged | Price |
|-------|--------------------|-------|
| Actor start (`apify-actor-start`) | Once, when the run starts | $0.00005 |
| UCC filing (`filing`) | A filing row is pushed | $0.008 |

- **100 filings:** 100 × $0.008 = **$0.80**, plus the $0.00005 start.
- **1,000 filings:** 1,000 × $0.008 = **$8.00**, plus the $0.00005 start.

One run accepts at most 500 filings ($4.00). The default `maxSpendUsd` of $0.50 covers 62 filings, which is more than the default 25. Raise it before you ask for a large pull. `unsupported`, `not_found`, `blocked`, `robots`, `spend_capped`, and `error` rows are free.

If these UCC filings were useful, a short Apify Store rating helps other lenders find this feed.

## Limits and data source

| State | File | What a UCC-1 is in that file |
|-------|------|------------------------------|
| Connecticut | [Uniform Commercial Code (UCC) Lien Filings](https://data.ct.gov/Business/Uniform-Commercial-Code-UCC-Lien-Filings/xfev-8smz) (`xfev-8smz`) | `ORIG FIN STMT` with description `OFS`. IRS, municipal, labor, vessel, and aircraft liens are excluded |
| Oregon | [UCC List of Filings Entered Last Month](https://data.oregon.gov/business/UCC-List-of-Filings-Entered-Last-Month/snfi-f79b) (`snfi-f79b`) | `lien_type` `UCC` and `file_type` `INITIAL` |

Both files are public domain on the state open-data portals. `robots.txt` allows `/resource/*.json` and asks for a one-second crawl delay. The OData paths are disallowed and are not called. Checked 2026-11-16.

- **Connecticut** keeps active liens and liens less than one year past lapse. It is a current file, so the last 7 days is a useful window.
- **Oregon** is replaced with the previous calendar month. It is not a live seven-day feed.
- **Not in this version:** Colorado's open UCC file has dates and types and no party names. Florida Sunbiz and New Jersey are search portals. Kentucky's bulk UCC file is a paid subscription. Those return `unsupported`. A CAPTCHA or a paid search is not attempted.
- **Pages:** each request asks for at most 100 JSON rows and the body is streamed. The read stops at `maxItems`. A statewide CSV is never downloaded. A single response is capped at 2 MB.
- **Blocks:** HTTP 401, 403, or 429 on a state saves one free `blocked` row and the other state still runs. There is no proxy retry.
- **Personal data:** debtor and secured-party names and addresses are whatever the state published on a public filing. They are copied through. This Actor does not add a phone, an email, or a credit attribute.
- **Collateral:** when a future file includes it, the text is cut at 2,000 characters. It is empty for Connecticut and Oregon today.

## FAQ

### What does a new UCC-1 filing mean?

A UCC-1 is a financing statement. A business (the debtor) has given a lender or lessor (the secured party) a public claim on collateral. Lenders and sellers use the filing date as a timing signal. The filing is not a credit score and it does not say the loan was approved, funded, or repaid.

### Which states have a UCC lien feed here?

Connecticut and Oregon. Pick any other state and you get one free `unsupported` row that says why. The list will grow only when a state publishes a JSON, CSV, or bulk file that includes the debtor and the secured party.

### How do I get new UCC filings by state?

Set `states` to `CT`, leave the dates empty for the last 7 days, and schedule the Actor each morning. Turn on `newSinceLastRun` after the first run so the next run returns filings that were not charged last time. For Oregon, set the dates to the previous month.

### How do I search by secured party?

Every filing row includes `securedPartyName`. Filter the dataset after the run. This Actor is a new-filings feed, not a name lookup across a state's history.

### Does this need a proxy?

No. Connecticut and Oregon publish these files as open data, so a blocked response stops that state instead of retrying through a proxy.

### What counts as a result?

One UCC filing row. An unsupported state, an empty window, a block, and an error are free. Several party lines on the same filing count as one result.

### Is this a credit report or a skip-trace?

No. It is the public financing statement. It does not score credit and it does not find a phone number or a personal email.

## Integrations and output

- **Dataset:** one row per filing, plus status rows. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has counts (`found`, `billedFilings`, `skippedSeen`, `unsupported`, `notFound`, `blocked`, `errors`, `truncated`), the date window, spend, and a report per state. After a run that pushed at least one filing, `SUMMARY.reviewAsk` asks for a Store rating.
- **Schedule:** run Connecticut each weekday. Send the dataset to Slack, email, Google Sheets, a CRM, Make, Zapier, or n8n.
- **API:** start a run from the API tab with the same input.

## Related actors

- [New Business Leads](https://apify.com/staticxviper/new-business): newly registered LLCs and corporations by state.
- [Contractor License Lookup](https://apify.com/staticxviper/contractor-license): public contractor license records.
- [Federal Contract Leads](https://apify.com/staticxviper/gov-contracts): SAM.gov opportunities and USAspending awards.

## Changelog

Release notes are on the **Changelog** tab of this page.
