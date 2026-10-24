# Contractor License Lookup

Public-record contractor license lookup for one state per run. Issue #155. California reads the Contractors State License Board open master file over HTTP. Arizona, New Jersey, and Pennsylvania each have a small adapter. A Cloudflare or Turnstile challenge, and a portal that does not publish an open file, push one status row and exit 0. This Actor does not launch Chromium, rotate proxies, or solve CAPTCHAs.

Sheriff-sale, foreclosure, and probate feeds are out of scope.

Low-volume research. The California file is about 21 MB. Keep `delaySeconds` at 2 or higher.

## What it does

| State | Board | What the adapter does |
|-------|--------|------------------------|
| CA | Contractors State License Board | Downloads `MasterLicenseData.csv` from the public data portal and filters it. No license-check form. |
| AZ | Registrar of Contractors | Reads the posting-list page and the dated "All Current Contractors" CSV when that HTML is served. A Cloudflare challenge stops the run. The Salesforce search is not used. |
| NJ | Department of Community Affairs | Checks the registered new-home builder page. That page now links a service portal that does not return records anonymously, so the adapter returns `unsupported` and does not open the portal. Consumer Affairs mylicense (home-improvement registrations) is a different board and is not requested. |
| PA | Attorney General, Home Improvement Consumer Protection Act | Confirmed board: there is no statewide general-contractor license. The HIC search page loads Cloudflare Turnstile. The adapter returns `captcha` and does not submit the form. PALS and municipal licenses are not included. |

A name search ignores punctuation and company suffixes such as LLC. A license number matches exactly after spaces and leading zeros are removed. A trade matches a classification code (`B-1` and `B1` are the same code) or every word of a class description. When more than one of license number, name, and trade is set, all of them must match. Results are the first matches in the public file, capped by `maxResults`.

## Input

`fixtures/INPUT.json`:

```json
{
  "state": "CA",
  "licenseNo": "99999999",
  "name": "",
  "trade": "",
  "maxResults": 5,
  "maxRequests": 4,
  "delaySeconds": 2,
  "headless": true
}
```

`state` is required (`CA`, `AZ`, `NJ`, or `PA`). Provide `licenseNo`, `name`, `trade`, or a combination. `license_no` is accepted as an alias of `licenseNo`. `maxResults` defaults to 25 and cannot exceed 50. `maxRequests` defaults to 4 (robots.txt counts) and cannot exceed 8. `headless` is kept for the shared Actor contract and has no effect, because no browser is launched. The sample license number is a miss against the live master file, so a local run of this fixture is a free `not_found`.

## Output

One dataset item per found license, or one status row when nothing is billed. Key-value `SUMMARY` has pushed, found, notFound, unsupported, captcha, and billed counts.

Found license (shape only; these values are not a live record):

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

`status` is the board's own license status when a row is found. `sourceStatus` is the run result:

| sourceStatus | Meaning | Billed |
|--------------|---------|--------|
| `found` | A license row was matched | yes, event `license` |
| `not_found` | The public file answered and nothing matched | no |
| `unsupported` | No open file for this state, or the state has no adapter | no |
| `captcha` | The source returned a challenge. The run stopped | no |
| `robots_disallowed` | robots.txt disallows the URL | no |
| `error` | The fetch failed, the request cap was hit, or the input was incomplete | no |

Dates stay in the format the board published. Bond and insurance are blank when that file does not publish them. Arizona's current-contractor CSV has no bond or insurance columns, and qualifying-party names are not copied into the dataset.

## Limitations

- California's master file includes renewed licenses and licenses that are expired but still renewable. Cancelled, revoked, and expired-nonrenewable licenses are absent. A `not_found` is not proof that a license never existed.
- One California download per run, capped at 80 MB. The file observed while packaging was about 21 MB.
- Arizona's posting-list URL changes with the file date. The adapter reads the link from the page. If that page is a Cloudflare challenge, status is `captcha` and the CSV is not requested.
- Arizona's current file is active contractors only.
- New Jersey returns `unsupported` until DCA publishes a verified open file. The service portal is not scraped.
- Pennsylvania returns `captcha` while Turnstile is on the HIC search. The form is not submitted even if a later page omits the widget; that path stays `unsupported` until it is verified as open data.
- `maxResults` stops a broad trade search. `truncated` in `SUMMARY` is true when more matches existed than the cap.
- Empty, failed, not-found, unsupported, and captcha runs do not emit the `license` event.
- No proxy rotation and no CAPTCHA solving.

## Robots and terms

California's `robots.txt` returned 404 while packaging, so the master-file URL is requested. The Actor still fetches `robots.txt` for each host and skips a disallowed path. Arizona's robots response was itself a Cloudflare challenge; that is returned as `captcha` and the file is not downloaded. New Jersey's robots file does not disallow the builders page. Pennsylvania's search page is fetched only to detect Turnstile and is not submitted.

CSLB asks readers to use Instant License Check for the newest status. The Registrar of Contractors asks readers to confirm a posting with the office before acting on it. Registration under Pennsylvania's Home Improvement Consumer Protection Act is not an endorsement by the Attorney General.

## Pricing

Pay per event. The primary event is `license` at $0.05, charged only when `sourceStatus` is `found` and `license_no` is set. `not_found`, `unsupported`, `captcha`, `robots_disallowed`, and `error` rows are stored and are not a success charge. Dataset items are not a charge event. The platform still applies its start event. Prices are the starting Store rates in `.actor/pay_per_event.json`. Memory default is 1024 MB and the default timeout is 600 seconds.

## Categories

Set in the Apify Console, not in `actor.json`. Suggested: Business, Other.

## Local run

```bash
cd scripts/apify-scripts/contractor-license
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

Publish with `APIFY_TOKEN` (`apify push`). That token is not `APIFY_API_KEY`. See `scripts/apify-scripts/README.md`.
