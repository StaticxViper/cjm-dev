# cjm-dev Documentation

Documentation for Python automation in `scripts/` and `helper_scripts/`, plus unit tests.

For first-time setup, see [setup.md](setup.md). The root [README.md](../README.md) has a shorter setup checklist.

## Scripts

| Script | Doc |
|--------|-----|
| Script manager | [scripts/script_manager.md](scripts/script_manager.md) |
| Script manager on GitHub Actions | [scripts/script_manager_actions.md](scripts/script_manager_actions.md) |
| Blog automation (Chikara Realms) | [scripts/blog_automation.md](scripts/blog_automation.md) |
| Lead generation | [scripts/leadgen.md](scripts/leadgen.md) |
| New-business sources | [scripts/new_business_sources.md](scripts/new_business_sources.md) |
| Niche lead search | [scripts/niche_search.md](scripts/niche_search.md) |
| Lead enrichment (Facebook) | [scripts/leadenrich.md](scripts/leadenrich.md) |
| Lead enrichment (Playwright / Google) | [scripts/leadenrich_playwright.md](scripts/leadenrich_playwright.md) |
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
| Grocery price sync | [scripts/grocery.md](scripts/grocery.md) |
| Opportunity finder v2 | [scripts/opp_finder_v2.md](scripts/opp_finder_v2.md) |
| Apify Actors (city-data, Google Maps) | [../scripts/apify-scripts/README.md](../scripts/apify-scripts/README.md) |

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
  leads --> enrichFb[leadenrich.py]
  leads --> enrichPw[leadenrich_playwright.py]
  crm[CRM Pipeline] -->|crm-leads-export| enrichPw
  enrichFb --> leads
  enrichPw --> leads
  leads --> ingest[lead_automation.py]
  ingest --> crm[CRM MCP create_lead]
  leadfilter[leadfilter.py] -.-> leadgen
```

## Environment variables

| Variable | Used by |
|----------|---------|
| `CHATGPT_API_KEY` | `blog_automation`, `api_manager` |
| `PERPLEXITY_API_KEY` | `blog_automation`, `stock_analyzer`, `api_manager` |
| `CHIKARA_REALMS_SECRET` | `blog_automation`, `api_manager` |
| `GOOGLE_API_KEY` | `leadgen`, `api_manager` |
| `LEAD_INGEST_KEY` | `leadenrich_playwright` (`--from-crm` export), `api_manager` |
| `CRM_MCP_MV_LLC` | `leadgen`, `lead_automation`, `leadenrich`, `leadenrich_playwright` (CRM upload) |
| `CRM_MCP_VENTURE` | CRM upload venture id, slug, or name (optional; default Web Dev - MV Software) |
| `APIFY_API_KEY` | `stock_analyzer`, `leadenrich`, `property_listing_gen`, `api_manager` (call Store Actors) |
| `APIFY_TOKEN` | Apify CLI `apify login` / `apify push` for Actors under `scripts/apify-scripts/` |
| `MVLLC_LOGS_KEY` | logger (all scripts), `api_manager` |
| `APIFY_USER_ID` | `api_manager` |
| `STOCK_INGEST_TOKEN` | `stock_analyzer`, `api_manager` |
| `LOVABLE_API_KEY` | `lovable_automation` |
| `LOVABLE_WORKSPACE_ID` | `lovable_automation` (optional) |
| `LOVABLE_CREDIT_THRESHOLD` | `lovable_automation` (optional, default `5`) |
| `MOTO_VIDS_BASE` | `clip_generator`, `montage_builder` (optional) |
| `SUPABASE_URL` | `grocery`, `grocery-sync` |
| `SUPABASE_SERVICE_ROLE_KEY` | `grocery`, `grocery-sync` |
| `SUPABASE_ANON_KEY` | `grocery` (optional), `grocery-sync` |
| `DEFAULT_SHOPRITE_ZIP` | `grocery`, `grocery-sync` (optional) |
| `GROCERY_MIN_DELAY_SECONDS` | `grocery`, `grocery-sync` (optional, default 2) |
| `GROCERY_TIMEOUT_MS` | `grocery`, `grocery-sync` (optional) |
| `GROCERY_BATCH_SIZE` | `grocery-sync` (optional, default 20) |
| `GROCERY_POLL_SECONDS` | `grocery` (optional, default 10) |

## Working directory cheat sheet

| Working directory | Scripts |
|-------------------|---------|
| `scripts/chikara_realms/` | `blog_automation.py` |
| `scripts/lead_automation/` | `leadgen.py`, `leadenrich.py`, `leadenrich_playwright.py`, `lead_automation.py` |
| `scripts/zillow_automation/` | `property_listing_gen.py` |
| `scripts/city_data/` | `city_data_scraper.py` |
| `scripts/apify-scripts/<actor>/` | `apify run` (see [apify-scripts README](../scripts/apify-scripts/README.md)) |
| `scripts/lovable_automation/` | `lovable_automation.py` |
| `scripts/json_formatter/` | `json_formatter.py` |
| `scripts/webhook_manager/` | `webhook_manager.py` |
| `scripts/video_editing/` | `clip_generator.py`, `montage_builder.py` |
| **Repo root** | `scripts/stock_analyzer/stock_analyzer.py` |
| `scripts/` | `python -m grocery.scraper`, `python -m grocery.sync`, `python -m opp_finder_v2` |

The script manager sets the working directory for you. From the repo root, `python -m scripts.script_manager run <name>` uses the cwd in the registry, including when your shell is not already in that folder. See [scripts/script_manager.md](scripts/script_manager.md).
