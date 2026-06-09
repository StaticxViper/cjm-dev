# API Manager

**Source:** `helper_scripts/api_manager/api_manager.py`

## Purpose

Central gateway for HTTP requests and Apify actor runs across cjm-dev scripts. Loads API keys from repo-root `.env`, builds authenticated requests (Bearer or `X-API-Key`), and fetches Apify dataset results.

## Prerequisites

- Python 3.12+
- `httpx`, `apify-client`, `python-dotenv`
- Relevant keys in `.env` for the APIs you call

## Configuration

### Environment variables (`API_KEYS`)

| API name (passed to methods) | Env variable |
|------------------------------|--------------|
| `Google` | `GOOGLE_API_KEY` |
| `Apify` | `APIFY_API_KEY` |
| `Stock Analyzer` | `STOCK_INGEST_TOKEN` |
| `ChatGPT` | `CHATGPT_API_KEY` |
| `Perplexity` | `PERPLEXITY_API_KEY` |
| `Chikara Realms` | `CHIKARA_REALMS_SECRET` |
| `Lead Ingest` | `LEAD_INGEST_KEY` |

Also: `APIFY_USER_ID` for Apify account context.

### Apify actors (`ACTORS`)

| Name | Actor ID |
|------|----------|
| `Yahoo Finance` | `architjn/yahoo-finance` |
| `Website Content Crawler` | `apify/website-content-crawler` |
| `Instagram Post Scraper` | `apify/instagram-post-scraper` |

## How to run

**Import in scripts:**

```python
from helper_scripts.api_manager import APIManager

api = APIManager()
api.build_request(
    base_url="https://example.com",
    endpoint="/path",
    method="POST",
    api="Stock Analyzer",
    json_body={"key": "value"},
)
```

**Test mode (no API keys):**

```bash
python helper_scripts/api_manager/api_manager.py
```

Runs `APIManager(test=True)` against `https://httpbin.org`.

## Key methods

### `build_request(base_url, endpoint, method, api, params, json_body, timeout)`

Generic HTTP client. Bearer auth for `Stock Analyzer` and `Perplexity`; `X-API-Key` for others. Returns parsed JSON.

### `get_api_key(api: str)`

Resolves env value by partial match on `API_KEYS` dict keys.

### `run_apify(actor, input, runtime)`

Runs a named Apify actor and returns dataset items.

### `get_apify_data(actor_call=None, dataset_id=None)`

Fetches items from an Apify dataset by run reference or dataset ID.

## Related scripts

Used by [blog_automation](../scripts/blog_automation.md), [lead_automation](../scripts/lead_automation.md), [stock_analyzer](../scripts/stock_analyzer.md), [lovable_automation](../scripts/lovable_automation.md), and others.
