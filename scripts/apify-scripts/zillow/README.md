# Zillow Real Estate Agent Scraper – Listing Agents by ZIP

**Zillow Real Estate Agent Scraper searches Zillow by ZIP code and returns one row per listing agent, with brokerage, phone, email, license number, profile URL, and the addresses of their listings, for mortgage lenders, title reps, and real estate service providers who prospect active agents.**

$0.008 per agent ($8 per 1,000) on the free tier, lower on paid Apify plans. Agents are de-duplicated across listings, so you pay once per agent.

## Who is it for?

- **Mortgage loan officers and lenders** building referral lists of agents with active listings in their market.
- **Title, escrow, and home-inspection reps** prospecting agents by ZIP.
- **Real estate photographers, stagers, and marketers** finding agents who list often.
- **Brokerage recruiters** mapping who is active in a territory and which brokerage they are with.
- **Proptech sales teams** selling CRM, lead, or transaction tools to agents.

## What data do you get?

One dataset item per unique agent.

| Field | Type | What it holds |
|-------|------|---------------|
| `agent_name` | string | Listing agent name |
| `brokerage` | string | Brokerage shown on the listing |
| `phone` | string | Phone from the listing, or from enrichment |
| `email` | string | Email from the listing, or from enrichment |
| `license` | string | License number when the page shows one |
| `profile_url` | string | Zillow agent profile URL |
| `enrichment_source` | string | `website` when a missing contact was filled from a public page |
| `enrichment_source_url` | string | The page the contact came from |
| `confidence` | string | `100` when name, brokerage, and area agree. `80` when name plus brokerage or area agree. Blank when weaker |
| `listing_addresses` | array | Addresses of this agent's listings found in the run |

Sample row from the Actor's saved Zillow test pages (a fictional agent). The listing already showed a phone and email, so enrichment did not run:

```json
{
  "agent_name": "Jane Smith",
  "brokerage": "Compass",
  "phone": "(856) 555-0101",
  "email": "jane.smith@compass.com",
  "license": "NJ-12345",
  "profile_url": "https://www.zillow.com/profile/jane-smith",
  "enrichment_source": "",
  "enrichment_source_url": "",
  "confidence": "",
  "listing_addresses": ["1 Main St, Cherry Hill, NJ 08002", "2 Oak Ave, Cherry Hill, NJ 08002"]
}
```

When enrichment fills a missing contact, `enrichment_source` is `website`, `enrichment_source_url` is the page it came from, and `confidence` is `100` or `80`.

An enriched contact is kept only when the agent name matches and the brokerage or search area also matches. A weaker match is left blank rather than guessed.

## Input

```json
{
  "zip_codes": ["08002", "08003"],
  "max_listings": 25,
  "max_agents": 10
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `zip_codes` | required | Up to 50 ZIP codes |
| `max_listings` | 25 (max 1,000) | Total listings across every ZIP |
| `max_agents` | 10 (max 500) | Total unique agents returned |
| `forSaleByAgent`, `forSaleByOwner`, `forRent`, `sold` | agent listings only | Listing types to search |
| `priceMin`, `priceMax` | — | Price filter |
| `enrich` | true | Fill a missing phone or email from the agent's or brokerage's public pages |
| `proxyConfiguration` | Apify residential, US | Change the proxy group or country if needed |

The run stops as soon as `max_listings` or `max_agents` is reached, and agents past `max_agents` are not enriched.

## How much does it cost?

Pay per event. You pay for agent rows that have a name.

| Event | Free tier | Bronze | Silver | Gold and up |
|-------|-----------|--------|--------|-------------|
| Listing agent (`result`) | $0.008 | $0.007 | $0.006 | $0.005 |

- **100 agents:** 100 × $0.008 = **$0.80**
- **1,000 agents:** 1,000 × $0.008 = **$8.00** (as low as $5.00 on Gold)

A blocked ZIP adds no agent rows and costs nothing. There is no CAPTCHA charge. The price is per agent, and the residential proxy this Actor uses is not a separate per-request event. Apify adds its small per-run start event.

## Limits and data source

- **Source:** public Zillow search and listing pages, read as HTML through Apify residential proxy (US exit). Listing data comes from the page's embedded JSON, so no browser is needed for those pages. Enrichment may open a browser to read the agent's or brokerage's public site.
- **Blocks:** if a ZIP's search page is a block or "are you a robot" page, it is retried once on a fresh proxy session. If it is still blocked, that ZIP is listed in `blocked_zips` and the next ZIP runs. No CAPTCHA solving.
- **Resume:** progress is checkpointed, so a migrated or restarted run continues where it stopped.
- **Markup changes:** Zillow changes its pages from time to time. Parsers prefer the embedded listing JSON and fall back to visible fields.
- **Known issue:** some recent Store runs reached their time limit before finishing. Until a fix ships, start with one or two ZIP codes and the default caps, then scale up.
- **Personal data:** results can include names, phone numbers, and emails from public listing pages. Store and use them only when you have a lawful reason, and follow the TCPA, CAN-SPAM, and local rules for outreach.

## FAQ

### How do I get a list of real estate agents in a ZIP code?

Put the ZIP code in `zip_codes`, set `max_agents` to the number you want, and run. Each row is one agent with their brokerage, contact details, and the listings found for them.

### Can I get agent phone numbers and emails?

Yes. Contacts shown on the listing are copied as-is. When one is missing and `enrich` is on, the Actor looks for it on the agent's or brokerage's public pages and records the source URL and a confidence score.

### Does this need a proxy?

Yes, and it is built in. Zillow blocks datacenter traffic, so the Actor uses Apify residential proxy by default. You do not need to configure anything.

### What counts as a result?

One unique agent with a name. Listings themselves are saved to the key-value store at no charge.

### Can I search for-sale-by-owner, rentals, or sold homes?

Yes. Turn on `forSaleByOwner`, `forRent`, or `sold` in the input. Agent listings are on by default.

## Integrations and output

- **Dataset:** one row per agent. Export as JSON, CSV, Excel, or HTML.
- **Key-value store:** `LISTINGS` (every listing collected), `SUMMARY` (`listings_found`, `agents_found`, `agents_enriched`, `blocked_zips`), and `CHECKPOINT` (resume state).
- **Automation:** run it from the Apify API, on a schedule, or through Make, Zapier, n8n, a CRM, or Google Sheets.

## Related actors

- [City Data Scraper](https://apify.com/staticxviper/city-data-scraper): population, income, housing, and crime stats for the towns you farm.
- [Building Permits Scraper](https://apify.com/staticxviper/permits): new roofing, solar, and pool permits in Chicago, Seattle, Austin, and Los Angeles.
- [New Business Leads](https://apify.com/staticxviper/new-business): newly registered LLCs and corporations.

## Changelog

Release notes are on the **Changelog** tab of this page.
