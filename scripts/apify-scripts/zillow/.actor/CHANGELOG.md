# Changelog

## Unreleased

- A run no longer crashes on shutdown when the image's Playwright has no private `Connection.cleanup`. It falls back to the public `stop()`.
- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated. Adds a key-value store schema for `LISTINGS`, `SUMMARY`, and `CHECKPOINT`.
- `max_listings` now defaults to 25 (max 1000) and `max_agents` to 10 (max 500). `zip_codes` accepts up to 50 ZIPs. Inputs that set these values are unchanged.
- The image builds from this folder only.

## 0.1.1

- On Apify, Zillow search and listing pages use a Chrome impersonation session through residential proxy in the US. The search is pinned to the ZIP's Zillow region so the proxy exit city does not replace it. The search document is the first request on a session. A block retries once on a second session and then stops.
- Listing pages are read from the embedded client cache, which is where the agent name is published.
- The sample fixture collects two listings and skips enrichment so a smoke run stays small.

## 0.1

- Search Zillow by ZIP code and return deduped listing agents.
- `max_listings` caps listings across every ZIP. `max_agents` caps unique agents.
- On Apify, Zillow requests use `Actor.create_proxy_configuration` (residential by default). A local run does not use a proxy.
- A block or captcha page is recorded for that ZIP and the run moves on. There is no CAPTCHA solver.
- Dataset items are agents. `LISTINGS`, `SUMMARY`, and `CHECKPOINT` are key-value records.
