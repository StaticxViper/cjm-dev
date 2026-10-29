# Changelog

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
