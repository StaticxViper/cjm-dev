# ATS Jobs Feed – Greenhouse, Lever, Ashby & Workable Job Listings

Open jobs for a list of companies, read straight from each company's public applicant-tracking-system job board. One dataset row per job with title, company, location, remote flag, salary when the employer publishes it, department, posted date, and the job URL. Turn on `newSinceLastRun` and a scheduled task becomes a feed of only the jobs it has not shown you before.

The Actor calls the official public job-board APIs that these ATS vendors publish for career pages. It does not scrape HTML, launch a browser, use a proxy, or solve CAPTCHAs. Requests run one at a time with a jittered 1–2 second pause.

## What it does

Every endpoint below was checked with a live request on 2026-11-02. An unknown slug answered HTTP 404 on all four.

| ATS | Endpoint called | Docs |
|-----|-----------------|------|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true&pay_transparency=true` | [Job Board API](https://developers.greenhouse.io/job-board.html) |
| Lever | `https://api.lever.co/v0/postings/{slug}?mode=json` | [lever/postings-api](https://github.com/lever/postings-api) |
| Lever (EU) | `https://api.eu.lever.co/v0/postings/{slug}?mode=json` | same README, EU instance links |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` | [Public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api) |
| Workable | `https://apply.workable.com/api/v1/widget/accounts/{slug}` | Not documented by Workable (see Limitations) |

Notes from that check:

- Greenhouse documents `pay_transparency=true` on the single-job endpoint only. On 2026-11-02 the list endpoint accepted it too and returned `pay_input_ranges` on all 213 Airbnb jobs, so one request per board still gets structured pay. When the ranges are empty, the Actor looks for a "$120,000 – $150,000" pattern in the job content.
- Lever returns the whole board in one response unless `limit` is passed. The Actor does not page. `createdAt` is epoch milliseconds and is converted to ISO UTC.
- Ashby's documented job object has no `id`, but the live response includes one. The Actor uses `id` and falls back to `jobUrl`. Jobs with `isListed: false` are skipped because Ashby says they are direct-link only.
- Workable's widget feed is the JSON its embeddable careers widget calls. It answered 200 for `huggingface` and 404 with plain text for an unknown slug. It has no salary field.

Rows are filtered by location, remote, and keyword, then deduped on `(ats, company slug, job id)`. The same job id at two companies stays two rows.

## Input

`fixtures/INPUT.json`:

```json
{
  "greenhouse": ["airbnb"],
  "lever": ["leverdemo"],
  "leverEu": [],
  "ashby": ["Ashby"],
  "workable": ["huggingface"],
  "location": "",
  "remote": "any",
  "keywords": ["engineer", "engineering"],
  "newSinceLastRun": true,
  "stateStoreName": "ats-jobs-state",
  "maxItems": 50,
  "delaySeconds": 1,
  "maxSpendUsd": 5
}
```

- Slugs are the last part of the public board URL: `boards.greenhouse.io/airbnb`, `jobs.lever.co/leverdemo`, `jobs.ashbyhq.com/Ashby`, `apply.workable.com/huggingface`. A full board URL is accepted and reduced to its slug. A `jobs.eu.lever.co` URL, or a name under `leverEu`, goes to Lever's EU API.
- `location` keeps a job when any of its locations contains the text (case-insensitive). Commas separate alternatives.
- `remote`: `any`, `remote` (fully remote only), or `exclude`. Hybrid counts as not remote.
- `keywords` keeps a job whose title or department contains any word. A single comma-separated `keyword` string is accepted too.
- `newSinceLastRun` skips jobs pushed by an earlier run. Seen keys and their `firstSeen` time live in the named key-value store `stateStoreName` (default `ats-jobs-state`), which persists between runs. Use a different store name per saved task to keep feeds apart.
- `maxItems` is an exact cap on job rows pushed (default 100, maximum 10,000). Status rows do not count. When the cap is reached, later boards are not requested.
- `maxSpendUsd` defaults to 5 and cannot exceed 100.

## Output

One dataset item per job, plus a status row for each board that was unknown, disallowed, or failed, and one `blocked` row if the run stopped. Key-value `SUMMARY` records counts (`found`, `newJobs`, `repeatJobs`, `billedJobs`, `notFound`, `blocked`, `errors`, `mergedDuplicates`, `filteredOut`, `skippedSeen`, `truncated`), spend, and one report per board (`ats`, `slug`, `status`, `fetched`, `kept`).

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

`salary` is `null` when the job lists nothing. `min`, `max`, `currency`, and `interval` are filled when the ATS publishes structured pay (Greenhouse pay ranges, Lever `salaryRange`, Ashby salary components) and are parsed from text otherwise. `interval` is one of `year`, `month`, `week`, `day`, `hour`, or null when the source does not say. `postedDate` is ISO UTC; Workable publishes a date only (`YYYY-MM-DD`). `decision` is `new` the first time a job is pushed and `repeat` after that (only when `newSinceLastRun` is off).

| sourceStatus | Meaning | job event |
|--------------|---------|-----------|
| `found` | A job was returned | yes, while `maxSpendUsd` still covers it |
| `not_found` | The ATS has no board with that slug (HTTP 404), or nothing matched the filters | no |
| `blocked` | HTTP 401, 403, or 429 after retries, or a challenge page instead of JSON. The run stops | no |
| `robots_disallowed` | robots.txt disallows the board URL | no |
| `error` | Bad slug, invalid JSON, a 5xx after retries, or robots.txt could not be read | no |

## Limitations

- Coverage is the four ATSs above. Workday, iCIMS, SmartRecruiters, and others are not read.
- A board is read in full in one request. Lever and Workable boards are not paged, and a very large board is capped at 32 MB.
- Workable does not document the widget endpoint. Its [documented API](https://help.workable.com/hc/en-us/articles/115013356548-Workable-API-Documentation) needs an employer token. The widget feed can change without notice, and Workable sits behind Cloudflare, which may answer 429 from cloud IPs. That ends the run with a `blocked` row.
- Remote is the ATS's own workplace field when it has one (Greenhouse "Workplace Type" metadata, Lever and Ashby `workplaceType`, Workable `telecommuting`), else the word "remote" in a location.
- Text salary parsing reads the first currency range it finds. A `$` amount is reported as USD.
- `newSinceLastRun` state keeps up to 200,000 keys per store and drops the oldest first.
- On a block the Actor pushes one `blocked` row, writes `SUMMARY`, and exits 0. Jobs already collected from earlier boards are still pushed. It does not retry through a proxy.

## Robots and terms

robots.txt is fetched once per host and evaluated with `scripts/lead_automation/crm_enrich_robots.py` (longest match, `User-agent: *`). A 4xx robots answer means no rules (RFC 9309). A 5xx or network failure skips that host for the run. On 2026-11-02, `boards-api.greenhouse.io` disallowed only `/embed/`, `api.lever.co` and `api.eu.lever.co` allowed `/` with Crawl-delay 1, `apply.workable.com` allowed everything, and `api.ashbyhq.com/robots.txt` answered 401.

Greenhouse says job board data is publicly available with no auth on GET. Lever and Ashby publish these endpoints for customers' own career sites. Job content belongs to the employer. Use it to link back to the original posting.

## Pricing

Pay per event from `.actor/pay_per_event.json`.

| Event | Price | When it is charged |
|-------|-------|--------------------|
| `job` (primary) | $0.002 (placeholder) | A job row is pushed |

**The $0.002 price is a placeholder pending a pricing decision.** Apify Store, read on 2026-11-02:

- [fantastic-jobs/career-site-job-listing-api](https://apify.com/fantastic-jobs/career-site-job-listing-api): "from $4.00 / 1,000 jobs", pay per event, 1,649 monthly users, 4.11 stars.
- [fantastic-jobs/greenhouse-jobs-api](https://apify.com/fantastic-jobs/greenhouse-jobs-api): "from $1.20 / 1,000 jobs".
- [fantastic-jobs/lever-co-jobs-api](https://apify.com/fantastic-jobs/lever-co-jobs-api): "from $0.80 / 1,000 jobs".

"From" is the lowest Store-discount tier. The undiscounted per-event price was not visible on those pages, so it is unverified. A third-party tracker (apifystats.com) lists the Career Site API at $12 / 1,000. That figure is not confirmed.

There are no `proxy` or `captcha` events because this Actor never uses either. `not_found`, `blocked`, `robots_disallowed`, and `error` rows are saved and not billed. Once `maxSpendUsd` cannot cover the next job, later jobs are saved without a charge. Dataset items are not a charge event. The platform still applies its start event. Memory default is 512 MB and the default timeout is 1,800 seconds.

### Deviation from the template contract

The template keeps `headless`, `maxProxyCostUsd`, `allowCaptcha`, `proxyConfiguration`, and `proxyGroups` in every input schema. This Actor drops them. It reads public JSON APIs with plain HTTP, never launches a browser, and stops on a block instead of spending to get past it. That is the same stop-on-challenge path `contractor-license` takes. Only `maxSpendUsd` is kept.

Two further differences:

- The shared `SpendLedger` counts whole cents, so $0.002 would round to 0 and the cap would never stop charging. `src/spend.py` subclasses it as `JobLedger` in micro-dollars with the same `can()` / `commit()` contract, and `push_charged_rows` uses it.
- The Dockerfile uses `apify/actor-python:3.12` instead of the shared Playwright image. It keeps the same user, workdir, `COPY --chown`, and `CJM_REPO_ROOT` layout.

## Categories

Set in the Apify Console, not in `actor.json`. Suggested: Jobs, Lead generation, Automation.

## Local run

```bash
cd scripts/apify-scripts/ats-jobs
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

`--purge` clears the default stores only. The named `ats-jobs-state` store under `storage/key_value_stores/` survives, so a second local run with `newSinceLastRun: true` returns only new jobs. Delete that folder to start fresh.

Unit tests read fixtures only:

```bash
python -m pytest unittests/apify_scripts/test_ats_jobs_actor.py -q
```

Publish with `APIFY_TOKEN` (`apify push`) only after a listing is requested. See `scripts/apify-scripts/README.md`.
