# Federal Contract Leads – SAM.gov & USAspending

Contract opportunities from the SAM.gov Get Opportunities API and contract awards from the USAspending spending-by-award API. One dataset row per notice or award, with the id, agency, title, NAICS, value, deadline, awardee, published contact, and a link back to the official page.

The Actor calls two official JSON APIs over plain HTTP. It does not launch a browser, use a proxy, or solve CAPTCHAs. Requests run one at a time with a jittered pause.

## What it does

| Source | Endpoint | What is kept |
|--------|----------|----------------|
| SAM.gov opportunities | `GET https://api.sam.gov/opportunities/v2/search` | `noticeId`, title, agency path, NAICS, set-aside, response deadline, award amount and awardee when the notice includes them, primary point of contact |
| USAspending awards | `POST https://api.usaspending.gov/api/v2/search/spending_by_award/` | Contract awards only (types A, B, C, D): award id, recipient, amount, awarding agency, NAICS, description, start and end dates |

SAM.gov `postedFrom` and `postedTo` are sent as `MM/dd/yyyy`. The same inclusive dates are the USAspending action-date window. SAM.gov is queried once per NAICS code (`ncode`, exact). USAspending receives every code in one `naics_codes.require` filter, which matches codes that start with the value. `offset` on SAM.gov is the page index starting at 0, not a record offset.

Rows are deduped on `(source, recordType, id)`. For an award the id used for dedupe is `generated_internal_id` when USAspending sends one, and the public `Award ID` is what the row shows. A page whose ids were all seen already stops that query.

`maxItems` counts successful rows only. Once it is filled, later pages and the remaining source are not requested.

USAspending search does not publish a person, email, or phone. Those contact fields are empty on award rows. The recipient name and UEI are the published awardee fields. SAM.gov contact fields are copied from the primary point of contact when the notice includes one.

The public opportunity URL is `https://sam.gov/opp/{noticeId}/view`, built from the notice id. A `beta.sam.gov` `uiLink` is not stored. The award URL is `https://www.usaspending.gov/award/{generated_internal_id}` when that id matches a safe token. Award `state` is the place-of-performance filter you set, because this search response does not include a state field. An opportunity `state` is the notice's own place of performance.

## Input

`fixtures/INPUT.json` is the CI fixture:

```json
{
  "sources": ["awards"],
  "naics": ["541512"],
  "state": "VA",
  "postedFrom": "2024-01-01",
  "postedTo": "2024-03-31",
  "maxItems": 2,
  "delaySeconds": 1,
  "maxSpendUsd": 1
}
```

Awards only, so the Docker smoke does not call `api.sam.gov` and does not need a SAM key. SAM.gov parsing, the missing-key skip, and a SAM.gov block are covered by fixture unit tests (`unittests/apify_scripts/fixtures/gov_contracts/sam_page.json`), not by this smoke run. The fixture asks for two historical USAspending awards (NAICS 541512, Virginia, first quarter of 2024). `fixtures/budget.json` expects exactly two dataset rows and a $0.016 charge. A run that only pushes a status row fails that gate.

- `sources` is `opportunities`, `awards`, or both. Default is both. Order is preserved.
- `naics` is 2 to 6 digits, at most 10. `state` is a 2-letter USPS code, or empty for every state. At least one of the two is required.
- `setAside` is one SAM.gov set-aside code (`SBA`, `WOSB`, `8A`, and the rest of the GSA list). Empty means every set-aside. SAM.gov accepts one code per request.
- `postedFrom` and `postedTo` are `YYYY-MM-DD`. Both empty means the 90 days ending today. The span cannot exceed 366 days. A bad or one-sided range is one error row and no request.
- `maxItems` caps successful rows after dedupe (default 50, maximum 200). It also bounds the network: later pages are not requested once it is filled. `maxSpendUsd` is applied after the fetch, when rows are pushed.
- `samApiKey` is the SAM.gov public API key from Account Details. It is a secret input. It is sent only as `api_key` on `api.sam.gov` and is redacted from stored URLs, errors, the dataset, and `SUMMARY`. Leave it empty to skip opportunities: one free `skipped` row is saved and awards still run.
- `delaySeconds` is the base pause between requests after the first (default 1, maximum 10). The pause jitters upward by up to 1 second.
- `maxSpendUsd` defaults to 5 (minimum 0.01, maximum 100). A lead is pushed only when its `opportunity` or `award` charge fits. The feed then stops with one free `spend_capped` row.

## Output

One dataset item per opportunity or award, plus a status row when a source is skipped, blocked, disallowed, or failed. Key-value `SUMMARY` records counts (`found`, `billedOpportunities`, `billedAwards`, `heldBack`, `skipped`, `blocked`, `errors`, `robots`, `mergedDuplicates`, `truncated`, `chargeCapped`), the filters, spend, and one report per source (`source`, `status`, `fetched`, `kept`). `SUMMARY` does not contain the API key.

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

`value` is null when the notice or award does not publish an amount. `deadline` is the SAM.gov response deadline, or the USAspending period-of-performance end date. `periodStart` is the award start date.

| sourceStatus | Meaning | Charged |
|--------------|---------|---------|
| `ok` | An opportunity or award was returned. Pushed only when `maxSpendUsd` covers that row's charge | yes |
| `skipped` | Opportunities were requested and `samApiKey` is empty. No SAM.gov request. Awards still run | no |
| `not_found` | Both sources returned no rows | no |
| `blocked` | HTTP 401, 403, or 429, or a challenge page. That source stops. The other source still runs | no |
| `spend_capped` | `maxSpendUsd` or the platform charge limit ended the feed | no |
| `robots` | robots.txt disallows the URL, or robots.txt could not be read (5xx or network). That host is skipped | no |
| `error` | Bad input, invalid JSON, or a 5xx / network error after one retry. The other source still runs | no |

## Limitations

- SAM.gov opportunities require the caller's own free API key. Daily limits depend on the SAM.gov account role. This Actor does not share a key.
- USAspending rows are prime contract awards (types A, B, C, and D), sorted by award amount descending. Grants and IDVs are not requested.
- At most 5 pages per query, 100 records per page, and 200 successful rows per run.
- A response larger than 32 MB is rejected for that request.
- On HTTP 401, 403, or 429 the Actor pushes one `blocked` row for that source and does not retry it. It does not send the request through a proxy.
- A 5xx or a dropped connection is tried once more. The second failure is an `error` row for that source.
- `maxSpendUsd` is checked before the row is pushed. A lead that would pass the cap is not pushed. The HTTP fetch has already finished by then, so the cap does not cancel a request that `maxItems` already allowed.
- If the platform charge raises after a row was pushed, that row stays in the dataset and is not billed. The feed stops. The row is not deleted and it is not charged again.

## Robots and terms

robots.txt is fetched once per host and evaluated with `scripts/lead_automation/crm_enrich_robots.py` (longest match, `User-agent: *`). A 4xx robots answer, including the 404 these API hosts return, means no rules. A 5xx or network failure skips that host for the run and records a `robots` row. A disallow is a `robots` row and the API URL is not fetched.

The data is published by SAM.gov and USAspending for public use. Contact fields are copied only when the API publishes them. Award rows do not invent a person, email, or phone.

## Pricing

Pay per event from `.actor/pay_per_event.json`.

| Event | Price | When it is charged |
|-------|-------|--------------------|
| `opportunity` (primary) | $0.008 | A SAM.gov opportunity row is pushed |
| `award` | $0.008 | A USAspending award row is pushed |

**$0.008 is $8 per 1,000 rows.** The brief suggested about $0.01, which is $10 per 1,000 and above the listing's affordability line. Both events use $0.008. No incumbent price was verified for this build. There is no `proxy` or `captcha` event, because an undeclared event is priced at $1 in the Docker smoke and this Actor never uses either.

`skipped`, `not_found`, `blocked`, `robots`, `spend_capped`, and `error` rows are saved and not billed. Dataset items are not a charge event. The platform still applies its start event. Memory default is 512 MB (minimum 256, maximum 2048) and the default timeout is 1,800 seconds.

### Deviation from the template contract

The template keeps `headless`, `maxProxyCostUsd`, `allowCaptcha`, `proxyConfiguration`, and `proxyGroups` in every input schema. This Actor drops them. It reads official JSON APIs with plain HTTP, never launches a browser, and stops a source on a block instead of spending to get past it. Only `maxSpendUsd` is kept.

The Dockerfile uses `apify/actor-python:3.12` instead of the shared Playwright image. It still leaves `WORKDIR` at `/usr/src/app`, copies only files inside this folder, and sets `CJM_REPO_ROOT=/usr/src/app/platform_bundle`. The slim image has no `xvfb-entrypoint.sh`.

`LeadLedger` counts micro-dollars and does not price `proxy` or `captcha`. $0.008 is 0.8 cents, so the shared cent ledger would round it to 1 cent. The micro-dollar ledger is what the push path checks before a row is saved.

## Categories

Set in the Apify Console, not in `actor.json`. Suggested: Lead generation, Business.

## Local run

```bash
cd scripts/apify-scripts/gov-contracts
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

That sample is the CI fixture: two USAspending awards, no SAM.gov call. Add `samApiKey` and include `opportunities` in `sources` to read SAM.gov.

Unit tests read fixtures only. They do not call `api.sam.gov`, `api.usaspending.gov`, or Apify.

```bash
python -m pytest unittests/apify_scripts/test_gov_contracts_actor.py -q
```

The Apify Actors workflow builds this image and runs `fixtures/INPUT.json` against `fixtures/budget.json`. Publish with `APIFY_TOKEN` (`apify push`) only after a listing is requested. See `scripts/apify-scripts/README.md`.
