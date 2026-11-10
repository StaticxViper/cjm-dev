# Home Services Leads – Local Contractor Leads with Emails

**Home Services Leads builds a local lead list for one service niche and one area from Google Maps, returning each verified business with phone, website, rating, website email, a website-quality score, and an intent lead score, for agencies and freelancers who sell to local service businesses.**

$0.008 per accepted business ($8 per 1,000) on the free tier, lower on paid Apify plans. Optional email and score add-ons are billed only when they produce a value.

## Who is it for?

- **Web design and SEO agencies** looking for local businesses with weak or missing websites (`website_quality` near 100).
- **Marketing freelancers** prospecting pool services, appliance repair, septic, radon and mold, or hood-cleaning companies in one city.
- **Lead-gen sellers** who need a short, verified list per niche and area instead of a raw Maps dump.
- **SaaS sales teams** selling booking, CRM, or review tools to home-service and specialty-service businesses.

## What data do you get?

One dataset item per Maps listing considered. Accepted rows carry the enrichment.

| Field | Type | What it holds |
|-------|------|---------------|
| `business` | string | Business name from Maps |
| `phone`, `website` | string | Contact details from the listing |
| `rating`, `review_count` | number | Google rating and number of reviews |
| `email` | string | Validated email from the business's own website |
| `website_quality` | number | 0–100, higher is a weaker site. `100` means no website |
| `website_label` | string | Plain-language label for that score, such as `Poor` |
| `website_status` | string | `ok`, `none`, `robots_disallowed`, or `error` for the website check |
| `lead_score` | number | Intent lead score for the niche |
| `intent_signals` | array | Signals behind the score, each with `key`, `label`, and `points` |
| `decision` | string | `accepted`, `rejected`, `blocked`, or `error` |
| `match_score` | number | Name and location match score |
| `hardRejects` | array | Why a listing was rejected |
| `niche`, `area` | string, object | The niche id and the resolved city, county, and state |
| `search_term` | string | The Maps search text that found the listing |
| `sourceStatus`, `error`, `scrapedAt` | string | Run status, failure reason, timestamp |

Sample accepted row from the Actor's unit-test fixture:

```json
{
  "business": "Aqua Leak Pros",
  "phone": "(212) 555-0100",
  "website": "https://aqualeakpros.com/",
  "rating": 4.8,
  "review_count": 32,
  "email": "owner@aqualeakpros.com",
  "website_quality": 70,
  "website_label": "Poor",
  "lead_score": 45,
  "intent_signals": [
    {"key": "high_value_service", "label": "High-value specialty", "points": 10}
  ],
  "decision": "accepted",
  "match_score": 85,
  "hardRejects": [],
  "niche": "pool_specialists",
  "area": {"region": null, "city": "Rochester", "county": null, "state": "NY"},
  "sourceStatus": "ok",
  "scrapedAt": "2026-10-24T00:00:00+00:00"
}
```

### Which listings are accepted?

A listing is `accepted` only when its name and address score at least `minConfidence` (default 80) against the requested city, county, and state, with no hard reject. The niche keyword is the search text, never the business name, and the first Maps card is never used as a fallback. Listings in another city, chains on the niche's negative list (for example Leslie's for pool specialists), and weak matches are `rejected` and not billed.

## Input

```json
{
  "niche": "pool_specialists",
  "area": "Rochester, NY",
  "maxItems": 10,
  "includeEmail": true,
  "includeWebsiteQuality": true,
  "includeScore": true
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `niche` | `pool_specialists` | One of 20 niches, including `premium_appliance_repair`, `commercial_hood_cleaning`, `radon_mold_specialists`, `septic_well_drainage`, `premium_mobile_auto_detailers`, `mobile_notaries`, and `professional_organizers` |
| `area` | — | `City, ST`, `Monroe County, NY`, or a named region. `city`, `county`, and `state` override it |
| `mapsDataset` | — | Up to 500 listings you already have. Scores them without opening Google Maps |
| `maxItems` | 10 (max 25) | Accepted leads per run |
| `maxSearches` | 5 (max 20) | Maps searches per run |
| `maxResults` | 5 (max 10) | Listings opened per search |
| `minConfidence`, `lowConfidenceFloor` | 80, 60 | Match thresholds |
| `includeEmail`, `includeWebsiteQuality`, `includeScore` | true | Turn off an add-on to skip it and its charge |

A state-only area usually returns few accepted rows, because a city or county match is what lifts a listing over 80. Use `City, ST` for the best results.

## How much does it cost?

Pay per event. Every charge is tied to a value in your dataset.

| Event | When it is charged | Free tier | Gold and up |
|-------|--------------------|-----------|-------------|
| Accepted place (`place`) | `decision` is `accepted` | $0.008 | $0.005 |
| Email found (`email-found`) | That accepted row has a validated `email` | $0.008 | $0.008 |
| Lead score (`score`) | That accepted row has a `lead_score` | $0.004 | $0.004 |

- **100 accepted places, no add-ons:** 100 × $0.008 = **$0.80**
- **100 accepted places, email found on 40 and scored on all:** $0.80 + 40 × $0.008 + 100 × $0.004 = **$1.52**
- **1,000 accepted places, no add-ons:** **$8.00**. With every add-on producing a value on every row, the most it can cost is $20.00.

`rejected`, `blocked`, and `error` rows, a website with no email, and a score that was not produced are free. Apify adds its small per-run start event.

## Limits and data source

- **Source:** public Google Maps search and place pages in a real Chromium browser, then each accepted business's own website. This is not the Google Places API.
- **Never requested:** Google web search (`/search`). Emails are never guessed.
- **Volume:** one Maps results page per keyword, up to `maxResults` place pages each, and at most 25 accepted leads per run.
- **Robots:** Google's robots.txt and each business website's robots.txt are checked before any fetch. A disallowed website is skipped, the place is still saved, and no email is charged.
- **Blocks:** if Google shows a block page, that search is saved as `blocked`, later searches are skipped, and the run ends cleanly. This Actor does not retry through a proxy and does not solve CAPTCHAs.
- **Website signals:** signals such as a broken site or missing contact form are added only when the website-quality check actually loaded the page.
- **Terms:** Google's terms restrict automated extraction. Use this Actor for occasional, targeted prospecting.

## FAQ

### How do I find pool service companies in my city?

Set `niche` to `pool_specialists` and `area` to your city, for example `Rochester, NY`. Each accepted row is a verified local business with phone, website, and, when found, email.

### How do I find local businesses with bad websites?

Keep `includeWebsiteQuality` on and sort the dataset by `website_quality`, highest first. A `100` means the business has no website.

### Can I score a list of businesses I already have?

Yes. Pass them in `mapsDataset` with fields like `business`, `phone`, `website`, `address`, and `rating`. The Actor matches and enriches them without opening Google Maps.

### Does this need a proxy or a Google API key?

No. It reads public Maps pages directly and needs no Google API key. A blocked search ends the run instead of buying proxy traffic.

### What counts as a result?

One `accepted` place. Emails and lead scores are separate, smaller charges that apply only when a value is returned.

## Integrations and output

- **Dataset:** one row per listing considered, with Overview and Detail views. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `SUMMARY` has `accepted`, `rejected`, `blocked`, `errors`, `pushed`, `emailsFound`, and `scoresProduced`.
- **Automation:** run it from the Apify API, on a schedule, or through Make, Zapier, n8n, or Google Sheets.

## Related actors

- [Google Maps Business Leads](https://apify.com/staticxviper/google-business-lead-generation): match a known business name to its Maps listing.
- [Building Permits Scraper](https://apify.com/staticxviper/permits): homeowners who just pulled a roofing, solar, or pool permit.
- [Contractor License Lookup](https://apify.com/staticxviper/contractor-license): check a California contractor's license before you call.

## Changelog

Release notes are on the **Changelog** tab of this page.
