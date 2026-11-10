# ATS Jobs Feed – Greenhouse, Lever, Ashby & Workable Jobs

**ATS Jobs Feed returns every open job for a list of companies straight from their Greenhouse, Lever, Ashby, or Workable job boards, with title, location, remote flag, salary when published, department, posted date, and apply URL, for recruiters, job boards, and sales teams that track hiring.**

$0.002 per job ($2 per 1,000) on every plan. No proxy, no browser, and no CAPTCHA solving. Turn on `newSinceLastRun` and a scheduled run becomes a feed of only the jobs you have not seen.

## Who is it for?

- **Recruiters and sourcers** watching target companies for new openings.
- **Job boards and aggregators** pulling clean listings from company career pages.
- **Sales and RevOps teams** using new engineering, data, or GTM roles as buying signals.
- **Talent-intelligence and compensation analysts** collecting published salary ranges by role and location.
- **Job seekers** building an alert for remote roles at a shortlist of companies.

## What data do you get?

One dataset item per job.

| Field | Type | What it holds |
|-------|------|---------------|
| `ats` | string | `greenhouse`, `lever`, `ashby`, or `workable` |
| `company`, `companySlug` | string | Company name and job-board slug |
| `jobId` | string | The ATS job id |
| `title` | string | Job title |
| `location`, `locations` | string, array | Primary location and every listed location |
| `remote`, `workplaceType` | boolean, string | Remote flag and the workplace type the ATS publishes. Hybrid counts as not remote |
| `salary` | object | `min`, `max`, `currency`, `interval`, and the raw text. `null` when not published |
| `department` | string | Department or team |
| `postedDate` | string | When the job was posted (ISO UTC; Workable gives a date only) |
| `url` | string | Job posting URL |
| `firstSeen` | string | First time this Actor pushed the job, when tracking is on |
| `decision` | string | `new` the first time a job is pushed, `repeat` after |
| `sourceStatus`, `ok`, `error`, `scrapedAt` | | Status, success flag, failure reason, timestamp |

Sample row for an Airbnb Greenhouse job (job id masked):

```json
{
  "ats": "greenhouse",
  "company": "Airbnb",
  "companySlug": "airbnb",
  "jobId": "1234567",
  "title": "AirCover Specialist, Claims Experience",
  "location": "Canada",
  "locations": ["Canada"],
  "remote": true,
  "workplaceType": "remote",
  "salary": {
    "min": 58000,
    "max": 68000,
    "currency": "CAD",
    "interval": "year",
    "raw": "Canada Annual Pay Range: CAD 58,000 - CAD 68,000"
  },
  "department": "Community Support",
  "postedDate": "2026-10-28T14:52:05+00:00",
  "url": "https://careers.airbnb.com/positions/1234567?gh_jid=1234567",
  "firstSeen": "2026-11-02T12:00:00+00:00",
  "sourceStatus": "found",
  "decision": "new",
  "ok": true,
  "error": "",
  "scrapedAt": "2026-11-02T12:00:00+00:00"
}
```

## Input

```json
{
  "greenhouse": ["airbnb", "stripe"],
  "lever": ["leverdemo"],
  "ashby": ["Ashby"],
  "workable": ["huggingface"],
  "remote": "remote",
  "keywords": ["engineer", "engineering"],
  "newSinceLastRun": true,
  "maxItems": 100
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `greenhouse`, `lever`, `leverEu`, `ashby`, `workable` | — | Up to 50 company slugs each, or full board URLs |
| `location` | — | Keep jobs whose location contains this text. Commas separate alternatives. `Remote` also matches jobs flagged remote |
| `remote` | `any` | `any`, `remote` (fully remote only), or `exclude` |
| `keywords` | — | Keep jobs whose title or department contains any of these whole words |
| `newSinceLastRun` | false | Return only jobs not pushed by an earlier run |
| `stateStoreName` | `ats-jobs-state` | Named store that remembers seen jobs. Use one per saved task |
| `maxItems` | 100 (max 10,000) | Jobs returned per run |
| `delaySeconds` | 1 (max 10) | Pause between requests |
| `maxSpendUsd` | 5 (max 100) | Hard cap on what one run can charge |

The slug is the last part of the board URL: `boards.greenhouse.io/airbnb`, `jobs.lever.co/leverdemo`, `jobs.ashbyhq.com/Ashby`, `apply.workable.com/huggingface`.

## How much does it cost?

Pay per event.

| Event | When it is charged | Price |
|-------|--------------------|-------|
| Job row (`job`) | A job is returned | $0.002 |

- **100 jobs:** 100 × $0.002 = **$0.20**
- **1,000 jobs:** 1,000 × $0.002 = **$2.00**

Unknown boards, filtered-out jobs, blocked hosts, and errors are free. With `newSinceLastRun` on, jobs you have already received are skipped and not billed again. Apify adds its small per-run start event.

## Limits and data source

| ATS | Source |
|-----|--------|
| Greenhouse | Public Job Board API (`boards-api.greenhouse.io`), with pay ranges |
| Lever | Public Postings API (`api.lever.co`, and `api.eu.lever.co` for EU accounts) |
| Ashby | Public Job Posting API (`api.ashbyhq.com`), with compensation |
| Workable | The public JSON feed behind Workable's careers widget (`apply.workable.com`). No salary field |

- **Coverage:** these four ATSs only. Workday, iCIMS, SmartRecruiters, and others are not read.
- **Source:** official public job-board JSON over plain HTTP. No HTML scraping, browser, or login.
- **Salary:** structured pay is used when the ATS publishes it. Otherwise the first currency range in the job text is parsed.
- **Workable:** the widget feed is not formally documented and can change. Workable may rate-limit cloud IPs, which skips the remaining Workable boards with one `blocked` row.
- **Blocks:** on a block the Actor saves one `blocked` row for that host and skips its remaining boards. Other ATS hosts still run. No proxy retry.
- **Robots:** robots.txt is checked for every host before any request.
- **Content:** job content belongs to the employer. Link back with `url`.

## FAQ

### How do I scrape all jobs from a company's Greenhouse board?

Add the company's Greenhouse slug to `greenhouse`, for example `airbnb` from `boards.greenhouse.io/airbnb`, and run. Every open job comes back as one row.

### How do I get alerts for new jobs only?

Set `newSinceLastRun: true` and schedule the Actor daily. Each run returns only jobs that earlier runs have not pushed. Use a different `stateStoreName` for each saved task to keep feeds separate.

### Does it include salary ranges?

Yes, when the employer publishes them. Greenhouse pay ranges, Lever `salaryRange`, and Ashby compensation come through as structured `min`, `max`, `currency`, and `interval`. Workable does not publish salary.

### Can I filter for remote jobs?

Yes. Set `remote` to `remote` for fully remote roles, or add `Remote` to `location` to also catch jobs whose location text says Remote.

### Does this need a proxy?

No. These are public APIs that the ATS vendors publish for career sites, so there is no proxy cost.

### What counts as a result?

One job row. Status rows for unknown boards, blocks, and errors are free.

## Integrations and output

- **Dataset:** one row per job plus status rows. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has counts (`found`, `newJobs`, `repeatJobs`, `billedJobs`, `notFound`, `blocked`, `errors`, `skippedSeen`, `truncated`), spend, and a report per board.
- **Automation:** schedule it for a daily job feed and push new rows to Slack, Google Sheets, Airtable, a CRM, Make, Zapier, or n8n.

## Related actors

- [Federal Contract Leads](https://apify.com/staticxviper/gov-contracts): SAM.gov contract opportunities and USAspending awards by NAICS and state.
- [New Business Leads](https://apify.com/staticxviper/new-business): newly registered LLCs and corporations.
- [App Store Reviews Scraper](https://apify.com/staticxviper/app-reviews): iOS App Store reviews with rating and text.

## Changelog

Release notes are on the **Changelog** tab of this page.
