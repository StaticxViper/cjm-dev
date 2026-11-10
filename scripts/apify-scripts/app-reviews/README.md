# App Store Reviews Scraper – iOS Ratings & Review Text

**App Store Reviews Scraper exports iOS App Store customer reviews for any list of apps from Apple's public iTunes feeds, with star rating, title, review text, app version, date, author, and optional sentiment, for product managers, app marketers, and analysts who track what users say.**

$0.001 per review ($1 per 1,000) on every plan. Optional sentiment adds $0.0005 per review. No proxy, no browser, and no CAPTCHA solving.

## Who is it for?

- **Product managers** reading the latest reviews after each release, filtered by `since` date.
- **App marketers and ASO specialists** tracking star ratings and complaints for their app and competitors.
- **Customer-support and QA teams** spotting bug reports by app version.
- **Market and competitive analysts** comparing review sentiment across apps and countries.
- **Agencies** building review dashboards for clients in Google Sheets or BI tools.

## What data do you get?

One dataset item per review.

| Field | Type | What it holds |
|-------|------|---------------|
| `app`, `appId` | string | App name and numeric App Store id |
| `store`, `country` | string | `appstore` and the 2-letter storefront |
| `reviewId` | string | Apple's review id |
| `rating` | integer | Stars, 1 to 5 |
| `title`, `text` | string | Review title and body |
| `version` | string | App version the review was written for |
| `date` | string | Review date as published by Apple |
| `author` | string | Reviewer's display name |
| `url` | string | Link back to the review, or to the app page |
| `sentiment`, `sentimentScore` | string, number | `positive`, `neutral`, or `negative`, and a score from -1 to 1. Only when `sentiment` is on |
| `sourceStatus` | string | `ok`, `not_found`, `blocked`, `spend_capped`, `robots`, or `error` |
| `decision`, `ok`, `error`, `scrapedAt` | | Row type, success flag, failure reason, timestamp |

Sample row from the Actor's saved RSS fixture:

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

With `sentiment` on, the row also has `"sentiment": "positive"` and `"sentimentScore": 1.0`.

## Input

```json
{
  "appStoreIds": ["284882215", "https://apps.apple.com/us/app/instagram/id389801252"],
  "country": "us",
  "since": "2026-10-01",
  "maxItems": 100,
  "sentiment": false
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `appStoreIds` | — | Up to 20 ids, `idNNNN` tokens, or App Store URLs |
| `country` | `us` | 2-letter App Store storefront, such as `gb`, `de`, or `jp` |
| `since` | — | Only reviews on or after this date (`YYYY-MM-DD`) |
| `maxItems` | 100 (max 1,000) | Reviews returned per run |
| `sentiment` | false | Add a positive, neutral, or negative label to each review |
| `delaySeconds` | 1 (max 10) | Pause between requests |
| `maxSpendUsd` | 5 (max 100) | Hard cap on what one run can charge |
| `playIds` | — | Reserved for Google Play. Not fetched yet, see Limits |

## How much does it cost?

Pay per event.

| Event | When it is charged | Price |
|-------|--------------------|-------|
| Review row (`review`) | A review is returned | $0.001 |
| Sentiment add-on (`sentiment`) | `sentiment` is on, for that same review | $0.0005 |

- **100 reviews:** **$0.10**, or $0.15 with sentiment
- **1,000 reviews:** **$1.00**, or $1.50 with sentiment

`not_found`, `blocked`, `robots`, `spend_capped`, and `error` rows are free. Apify adds its small per-run start event. Once `maxSpendUsd` cannot cover the next review, the feed stops with one free `spend_capped` row.

## Limits and data source

- **Source:** Apple's public iTunes lookup API and customer-reviews RSS feed (`itunes.apple.com`), over plain HTTP. No login, no browser, no proxy.
- **Depth:** Apple's feed returns the most recent reviews, up to 10 pages per app and country. Older reviews past that depth are not available from this feed.
- **iOS only:** Google Play is not covered yet. Its reviews load through a browser session with no stable public feed. Any `playIds` you pass return one free `blocked` row after the App Store apps run.
- **Sentiment:** a small built-in word list, not an AI model. Nothing is sent to a third party.
- **Blocks:** on HTTP 401, 403, 429, or a challenge page the Actor saves one `blocked` row and stops. It does not retry through a proxy. A 5xx or dropped connection is retried once.
- **Robots:** robots.txt is checked for every host before any request.
- **Content:** review text belongs to the reviewer. Link back to the original with `url`.

## FAQ

### How do I export App Store reviews to CSV?

Add the app's App Store id or URL to `appStoreIds` and run. Open the dataset tab and download it as CSV or Excel.

### How do I find an app's App Store id?

It is the number after `id` in the App Store URL. For `https://apps.apple.com/us/app/facebook/id284882215` it is `284882215`. You can also paste the full URL.

### Can I get reviews from other countries?

Yes. Set `country` to the storefront code, such as `gb`, `ca`, `de`, or `jp`. Run once per country.

### Does it scrape Google Play reviews?

Not yet. This Actor covers the iOS App Store only.

### Does this need a proxy?

No. Apple's feeds are public and answer direct, so there is no proxy cost.

### What counts as a result?

One review row. Apps with no reviews, unknown ids, and errors are free.

## Integrations and output

- **Dataset:** one row per review plus status rows. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has counts (`found`, `billedReviews`, `billedSentiment`, `notFound`, `blocked`, `errors`, `mergedDuplicates`, `truncated`), spend, and a report per app.
- **Automation:** schedule it daily with `since` set to yesterday for a review feed, or send rows to Slack, Google Sheets, Make, Zapier, or n8n.

## Related actors

- [ATS Jobs Feed](https://apify.com/staticxviper/ats-jobs): open jobs from Greenhouse, Lever, Ashby, and Workable boards, for competitor hiring signals.
- [Google Maps Business Leads](https://apify.com/staticxviper/google-business-lead-generation): a business's Google rating, review count, phone, and website.
- [Federal Contract Leads](https://apify.com/staticxviper/gov-contracts): SAM.gov opportunities and USAspending awards.

## Changelog

Release notes are on the **Changelog** tab of this page.
