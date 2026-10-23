# Lead automation

Local-business lead discovery, enrichment, and CRM ingest.

`leadgen.py` is the import and CLI facade. The implementation is split across `leadgen_config.py`, `places_api.py`, `lead_scoring.py`, `lead_pipeline.py`, `lead_persistence.py`, and `leadgen_cli.py`, which are executed into the `leadgen` module so existing imports keep working. Discovery is Google Places (`api_manager`) or Playwright Maps (`playwright`). `--mode new-business` reads registry and license sources. Niche search is `niche_search.py`.

`leadenrich.py` fills emails from Facebook via Apify. `leadenrich_playwright.py` researches the business on Google. `lead_automation.py` reads saved leads and calls CRM `create_lead`.

**Inputs:** `keywords.json`, `coords.json`, `franchises.json`, `leadgen_settings.json`, and CLI flags (`--defaults`, `--leadgen-type`, `--objective`, locations). **Outputs:** `*leads_output*.json`, search history, and CRM leads when the output mode includes the dashboard.

**Local run** from this directory:

```bash
python leadgen.py --defaults --leadgen-type playwright --state NJ
python leadenrich.py --json-path leads_output.json
python lead_automation.py
```

**Script Manager:** `leadgen`, `leadenrich`, `leadenrich-playwright`, and `lead-ingest` (ingest is marked broken). `leadgen-new-business` is a planned alias. Dispatch any registered name with [`.github/workflows/script_manager.yml`](../../.github/workflows/script_manager.yml). Schedules use [script_manager_schedule.yml](../../.github/workflows/script_manager_schedule.yml).

**Secrets:** `GOOGLE_API_KEY` for Places discovery. `APIFY_API_KEY` for Facebook enrichment. `CRM_MCP_MV_LLC` to upload leads, with optional `CRM_MCP_VENTURE`. Optional `MVLLC_LOGS_KEY`.

Longer guides: [leadgen](../../documentation/scripts/leadgen.md), [niche search](../../documentation/scripts/niche_search.md), [new-business sources](../../documentation/scripts/new_business_sources.md), [Facebook enrich](../../documentation/scripts/leadenrich.md), [Playwright enrich](../../documentation/scripts/leadenrich_playwright.md), [ingest](../../documentation/scripts/lead_automation.md).
