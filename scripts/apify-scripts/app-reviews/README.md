# App Store Reviews – iTunes Customer Reviews RSS

Customer reviews for a list of iOS apps, read from Apple's public iTunes lookup and customer-reviews RSS feeds. One dataset row per review with the app name, star rating, title, text, version, date, author, and a link back to the review.

The Actor calls two public JSON endpoints over plain HTTP. It does not launch a browser, use a proxy, or solve CAPTCHAs. Requests run one at a time with a jittered pause. Google Play is not called.

## What it does

| Source | Endpoint | What is kept |
|--------|----------|----------------|
| iTunes lookup | `https://itunes.apple.com/lookup?id={id}&country={country}` | `trackName` (or the id) and `trackViewUrl` |
| Customer reviews RSS | `https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={id}/sortby=mostrecent/json` | Entries that have `im:rating` |

The RSS feed is most recent first. Its first entry is often the app itself and has no `im:rating`; that entry is skipped. Pages start at 1 and stop at 10. A page also stops the crawl when it is empty, when it repeats review ids already seen in this run, when `maxItems` is filled, or when the oldest review on the page is before `since` (later pages are older).

`since` compares calendar dates. A timestamp with an offset uses the calendar date in that offset. A timestamp with no offset is treated as UTC. The stored `date` is the original string from the feed.

Rows are deduped on `(store, appId, reviewId)`, so an RSS page that overlaps the previous page does not emit a second row.

Google Play packages in `playIds` are not fetched. The Play details page is a JavaScript shell and its reviews are loaded through a batchexecute session. There is no stable public unproxied document this Actor can fixture-test without a browser or cookies. When `playIds` is non-empty, App Store apps are read first, then the Actor pushes one `blocked` row and stops.

## Input

`fixtures/INPUT.json`:

```json
{
  "appStoreIds": ["284882215"],
  "playIds": [],
  "country": "us",
  "maxItems": 3,
  "sentiment": false,
  "delaySeconds": 1,
  "maxSpendUsd": 1
}
```

This file is the CI fixture: Facebook for iOS (`284882215`), United States storefront, three reviews, sentiment off. `since` is omitted. `playIds` is empty so the smoke run does not depend on Play.

- `appStoreIds` accepts a numeric id, an `idNNNN` token, or a store URL that contains `id=NNNN` or `/idNNNN`. At most 20.
- `playIds` accepts Play package names. At most 20. Any non-empty list ends the run with one free `blocked` row and no request to `play.google.com`.
- `country` is a 2-letter storefront. It is lowercased. `US` becomes `us`. Anything else is one error row and the run stops before fetching.
- `since` is an optional `YYYY-MM-DD`. A bad value is one error row and the run stops before fetching.
- `maxItems` caps successful review rows after the date filter and dedupe (default 100, maximum 1,000). Status rows do not count. Later apps and later RSS pages are not requested once the cap is filled.
- `sentiment` adds `sentiment` (`positive`, `neutral`, or `negative`) and `sentimentScore` (a number from -1 to 1) from a local word list. Nothing is sent to a model. When it is off, those fields are omitted.
- `delaySeconds` is the base pause between requests after the first (default 1, maximum 10). The pause jitters upward by up to 1 second.
- `maxSpendUsd` defaults to 5 (minimum 0.01, maximum 100). A review is pushed only when the `review` charge and, if sentiment is on, the `sentiment` charge both fit. The feed then stops with one free `spend_capped` row.

## Output

One dataset item per review, plus a status row when an app is missing, disallowed, or failed. A block is one `blocked` row and the run stops. A spend cap adds one `spend_capped` row. Key-value `SUMMARY` records counts (`found`, `billedReviews`, `billedSentiment`, `heldBackReviews`, `notFound`, `blocked`, `errors`, `robots`, `mergedDuplicates`, `filteredOut`, `truncated`, `chargeCapped`), spend, and one report per app (`store`, `appId`, `status`, `fetched`, `kept`).

```json
{
  "app": "Facebook",
  "appId": "284882215",
  "store": "appstore",
  "country": "us",
  "reviewId": "1001",
  "rating": 5,
  "title": "Love this app",
  "text": "Really great and helpful every day.",
  "version": "532.0",
  "date": "2026-10-20T08:15:00-07:00",
  "author": "Alex Rivera",
  "url": "https://itunes.apple.com/us/review?id=284882215&type=Purple%20Software",
  "sourceStatus": "ok",
  "decision": "review",
  "ok": true,
  "error": "",
  "scrapedAt": "2026-11-03T12:00:00+00:00"
}
```

With `sentiment` on, the same row also includes `"sentiment": "positive"` and `"sentimentScore": 1.0`. `url` is the review link from the feed, or the app's `trackViewUrl` when the feed has none. `rating` is an integer from 1 to 5.

| sourceStatus | Meaning | review event |
|--------------|---------|----------------|
| `ok` | A review was returned. Pushed only when `maxSpendUsd` covers the charges that apply | yes |
| `not_found` | Lookup `resultCount` is 0, or the app has no customer reviews. The run continues | no |
| `blocked` | HTTP 401, 403, or 429 (not retried), or a consent / CAPTCHA / challenge page. The run stops after this one row. Also the Play-deferred row | no |
| `spend_capped` | `maxSpendUsd` or the platform charge limit ended the review feed | no |
| `robots` | robots.txt disallows the URL, or robots.txt could not be read (5xx or network). That host is skipped. The run continues | no |
| `error` | Bad id, invalid country or `since`, invalid JSON, or a 5xx / network error after one retry. The run continues with the next app | no |

## Limitations

- Coverage is the public iTunes customer-reviews RSS. Google Play is deferred on purpose.
- At most 10 RSS pages per app. Apple's feed is most-recent and about one page of reviews at a time.
- A response larger than 32 MB is rejected for that URL.
- Sentiment is a small local lexicon, not a model. Words are matched whole. Unlisted wording scores neutral.
- On HTTP 401, 403, 429, or a challenge page the Actor pushes one `blocked` row and does not fetch later apps. It does not retry those statuses and does not send the request through a proxy.
- A 5xx or a dropped connection is tried once more. The second failure is an `error` row for that app and the next app still runs.
- `maxSpendUsd` is checked in micro-dollars. A review that would pass the cap is not pushed.

## Robots and terms

robots.txt is fetched once per host and evaluated with `scripts/lead_automation/crm_enrich_robots.py` (longest match, `User-agent: *`). A 4xx robots answer means no rules (RFC 9309). A 5xx or network failure skips that host for the run and records a `robots` row. A disallow is a `robots` row for that app and the reviews URL is not fetched. It is not a block and it is not retried through a proxy.

The customer-reviews RSS and the lookup endpoint are public Apple feeds used by iTunes storefront pages. Review text belongs to the reviewer. Use the URL to link back to the original review.

## Pricing

Pay per event from `.actor/pay_per_event.json`.

| Event | Price | When it is charged |
|-------|-------|--------------------|
| `review` (primary) | $0.001 | A review row is pushed |
| `sentiment` | $0.0005 | `sentiment` is on and that same review row was pushed |

**$0.001 is the top of the brief's unverified $0.0005–0.001 range.** thewolves Store comps were not confirmed for this build. There is no `proxy` or `captcha` event, because an undeclared event is priced at $1 in the Docker smoke and this Actor never uses either.

`not_found`, `blocked`, `robots`, `spend_capped`, and `error` rows are saved and not billed. Sentiment is never charged for a status row, and never charged when the add-on is off. If the sentiment charge fails after the review was pushed, no further reviews are pushed. Dataset items are not a charge event. The platform still applies its start event. Memory default is 512 MB (minimum 256, maximum 2048) and the default timeout is 1,800 seconds.

### Deviation from the template contract

The template keeps `headless`, `maxProxyCostUsd`, `allowCaptcha`, `proxyConfiguration`, and `proxyGroups` in every input schema. This Actor drops them. It reads public JSON with plain HTTP, never launches a browser, and stops on a block instead of spending to get past it. Only `maxSpendUsd` is kept.

Two further differences:

- The shared `SpendLedger` counts whole cents, so $0.001 would round to 0 and the cap would never stop the feed. `src/spend.py` subclasses it as `ReviewLedger` in micro-dollars with the same `can()` / `commit()` contract. A review is pushed only when every charge that applies still fits.
- The Dockerfile uses `apify/actor-python:3.12` instead of the shared Playwright image. It still leaves `WORKDIR` at `/usr/src/app`, copies only files inside this folder, and sets `CJM_REPO_ROOT=/usr/src/app/platform_bundle`. The slim image has no `xvfb-entrypoint.sh`.

## Categories

Set in the Apify Console, not in `actor.json`. Suggested: Social media, E-commerce, Lead generation.

## Local run

```bash
cd scripts/apify-scripts/app-reviews
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

Unit tests read fixtures only. They do not call `itunes.apple.com`, `play.google.com`, or Apify.

```bash
python -m pytest unittests/apify_scripts/test_app_reviews_actor.py -q
```

Publish with `APIFY_TOKEN` (`apify push`) only after a listing is requested. See `scripts/apify-scripts/README.md`.
