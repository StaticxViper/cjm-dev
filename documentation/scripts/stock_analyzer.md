# Stock Analyzer

**Source:** `scripts/stock_analyzer/stock_analyzer.py`

## Purpose

Daily stock data pipeline: fetches the watchlist from Supabase, runs the Apify Yahoo Finance actor for OHLC data, ingests results to the dashboard API. On the first run of each calendar day, also runs Perplexity (`sonar-pro`) analysis per ticker and ingests that separately.

## Prerequisites

- Python 3.12+
- `APIFY_API_KEY`, `STOCK_INGEST_TOKEN`, `PERPLEXITY_API_KEY` in repo-root `.env`
- Apify account with access to the Yahoo Finance actor

## Configuration

| File | Description |
|------|-------------|
| `scripts/stock_analyzer/previous_run_date.txt` | Last run date (`YYYY-MM-DD`); read from repo-relative path |
| `previous_run_date.txt` | Updated in the **current working directory** on each run (repo root when run correctly) |
| `stock_tickers.json` | Present in folder; tickers are fetched from API, not this file |

## How to run

**From repo root** (required for config paths):

```bash
python scripts/stock_analyzer/stock_analyzer.py
```

CI (GitHub Actions) runs:

```bash
pip install -r requirements/requirements.txt
PYTHONPATH=$GITHUB_WORKSPACE python scripts/stock_analyzer/stock_analyzer.py
```

Scheduled weekdays at 9:00 AM EST via `.github/workflows/stock_analyzer-Automation.yml`.

## How it works

1. GET `/stock-data/tickers` from Supabase to obtain the watchlist.
2. Read `scripts/stock_analyzer/previous_run_date.txt` and compare to today.
3. Run Apify actor `Yahoo Finance` with date range and tickers.
4. Write today's date to `previous_run_date.txt` in CWD.
5. POST stock data to `/stock-data/ingest`.
6. If the calendar day changed: for each ticker, call Perplexity for earnings/news analysis, then POST analysis dict to the same ingest endpoint.

## Related scripts

- [api_manager.md](../helper_scripts/api_manager.md) — Apify and HTTP requests
