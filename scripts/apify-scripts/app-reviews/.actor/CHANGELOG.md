# Changelog

## Unreleased

- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated. Title is now "App Store Reviews Scraper – iOS Ratings & Review Text".

## 0.1

- Read public iTunes lookup and customer-reviews RSS (most recent) for a list of App Store ids. The app-info entry without `im:rating` is skipped. Pages stop when a page is empty, a page repeats review ids, `maxItems` is filled, or the oldest review on the page is before `since`.
- Google Play is deferred. There is no stable public unproxied reviews document that can be fixture-tested without a browser, cookies, or a batchexecute session. A non-empty `playIds` list pushes one `blocked` row and the run stops without calling Play.
- One row per review with rating, title, text, version, original date, author, and URL. Dedupe on `(store, appId, reviewId)`.
- Optional local lexicon sentiment (`sentiment`, `sentimentScore`). No network and no model API. The fields are omitted when the add-on is off.
- Charge `review` ($0.001, primary) only when a review row is pushed. Charge `sentiment` ($0.0005) only when the add-on is on and that same row was pushed. $0.001 is the top of the brief's unverified $0.0005–0.001 range. thewolves Store comps were not confirmed for this build.
- A review is pushed only when both charges that apply still fit under `maxSpendUsd`. The shared cent ledger would round $0.001 to 0, so `ReviewLedger` counts micro-dollars. Misses, blocks, robots, not_found, errors, and spend_capped rows are saved and not billed.
- Direct HTTP only. No proxy, no CAPTCHA solver, no browser. HTTP 401, 403, 429, or a consent/challenge page pushes one `blocked` row and stops the run. 5xx and network errors are retried once; a second failure is an error row for that app and the run continues.
