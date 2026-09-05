# cjm-dev Documentation

Documentation for Python automation in `scripts/` and `helper_scripts/`, plus unit tests.

For first-time setup, see [setup.md](setup.md). The root [README.md](../README.md) has a shorter setup checklist.

## Scripts

| Script | Doc |
|--------|-----|
| Blog automation (Chikara Realms) | [scripts/blog_automation.md](scripts/blog_automation.md) |
| Lead generation | [scripts/leadgen.md](scripts/leadgen.md) |
| Lead enrichment (Facebook) | [scripts/leadenrich.md](scripts/leadenrich.md) |
| Lead ingest | [scripts/lead_automation.md](scripts/lead_automation.md) |
| Lead filter (library) | [scripts/leadfilter.md](scripts/leadfilter.md) |
| Stock analyzer | [scripts/stock_analyzer.md](scripts/stock_analyzer.md) |
| Webhook manager | [scripts/webhook_manager.md](scripts/webhook_manager.md) |
| Lovable automation | [scripts/lovable_automation.md](scripts/lovable_automation.md) |
| Clip generator | [scripts/clip_generator.md](scripts/clip_generator.md) |
| Montage builder | [scripts/montage_builder.md](scripts/montage_builder.md) |
| JSON formatter | [scripts/json_formatter.md](scripts/json_formatter.md) |
| Email manager (library) | [scripts/email_manager.md](scripts/email_manager.md) |
| Zillow property listing | [scripts/property_listing_gen.md](scripts/property_listing_gen.md) |
| City-data scraper | [scripts/city_data_scraper.md](scripts/city_data_scraper.md) |
| Property city-data lookup | [scripts/property_city_lookup.md](scripts/property_city_lookup.md) |

## Helper scripts

| Module | Doc |
|--------|-----|
| API manager | [helper_scripts/api_manager.md](helper_scripts/api_manager.md) |
| Logger | [helper_scripts/logger.md](helper_scripts/logger.md) |
| Update manager (legacy) | [helper_scripts/update_manager.md](helper_scripts/update_manager.md) |

## Testing

| Topic | Doc |
|-------|-----|
| Unit tests | [testing/unittests.md](testing/unittests.md) |

## Lead pipeline

```mermaid
flowchart LR
  leadgen[leadgen.py] --> leads[leads_output.json]
  leads --> enrich[leadenrich.py]
  enrich --> leads
  leads --> ingest[lead_automation.py]
  ingest --> supabase[Supabase leads-ingest]
  leadfilter[leadfilter.py] -.-> leadgen
```

## Environment variables

| Variable | Used by |
|----------|---------|
| `CHATGPT_API_KEY` | `blog_automation`, `api_manager` |
| `PERPLEXITY_API_KEY` | `blog_automation`, `stock_analyzer`, `api_manager` |
| `CHIKARA_REALMS_SECRET` | `blog_automation`, `api_manager` |
| `GOOGLE_API_KEY` | `leadgen`, `api_manager` |
| `LEAD_INGEST_KEY` | `lead_automation`, `leadenrich`, `api_manager` |
| `APIFY_API_KEY` | `stock_analyzer`, `leadenrich`, `property_listing_gen`, `api_manager` |
| `MVLLC_LOGS_KEY` | logger (all scripts), `api_manager` |
| `APIFY_USER_ID` | `api_manager` |
| `STOCK_INGEST_TOKEN` | `stock_analyzer`, `api_manager` |
| `CITY_DATA_INGEST_KEY` | `property_city_lookup`, `api_manager` (required for ingest POST) |
| `CITY_DATA_INGEST_BASE_URL` | `property_city_lookup` (optional URL override) |
| `CITY_DATA_INGEST_ENDPOINT` | `property_city_lookup` (optional, default `/api/public/city-data`) |
| `LOVABLE_API_KEY` | `lovable_automation` |
| `LOVABLE_WORKSPACE_ID` | `lovable_automation` (optional) |
| `LOVABLE_CREDIT_THRESHOLD` | `lovable_automation` (optional, default `5`) |
| `MOTO_VIDS_BASE` | `clip_generator`, `montage_builder` (optional) |

## Working directory cheat sheet

| Working directory | Scripts |
|-------------------|---------|
| `scripts/chikara_realms/` | `blog_automation.py` |
| `scripts/lead_automation/` | `leadgen.py`, `leadenrich.py`, `lead_automation.py` |
| `scripts/zillow_automation/` | `property_listing_gen.py` |
| `scripts/city_data/` | `city_data_scraper.py`, `property_city_lookup.py` |
| `scripts/lovable_automation/` | `lovable_automation.py` |
| `scripts/json_formatter/` | `json_formatter.py` |
| `scripts/webhook_manager/` | `webhook_manager.py` |
| `scripts/video_editing/` | `clip_generator.py`, `montage_builder.py` |
| **Repo root** | `scripts/stock_analyzer/stock_analyzer.py` |
