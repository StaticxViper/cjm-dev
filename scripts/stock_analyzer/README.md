# Stock analyzer

Daily watchlist pipeline. It loads tickers from the dashboard, runs the Apify Yahoo Finance actor for OHLC, and posts the bars back. The first run of a calendar day also asks Perplexity for a short earnings and news note per ticker.

**Inputs:** the remote watchlist (`stock_tickers.json` is the local reference list) and `previous_run_date.txt`. **Outputs:** ingested bars and, once per day, ingested analysis. The run date file is updated in this folder.

**Local run** from the repo root (the registry working directory is the root):

```bash
python scripts/stock_analyzer/stock_analyzer.py
python -m scripts.script_manager run stock-analyzer
```

**Actions:** no stock-specific workflow. Dispatch `stock-analyzer` through [script_manager.yml](../../.github/workflows/script_manager.yml).

**Secrets:** `STOCK_INGEST_TOKEN`, `APIFY_API_KEY`, `PERPLEXITY_API_KEY`. Optional `MVLLC_LOGS_KEY`. The script does not read Discord webhook variables.

Longer guide: [documentation/scripts/stock_analyzer.md](../../documentation/scripts/stock_analyzer.md).
