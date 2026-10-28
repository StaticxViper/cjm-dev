# Helper scripts

Shared code used by more than one tool. Tool-specific orchestration stays under [`scripts/`](../scripts/).

| Package | Role |
|---------|------|
| [`api_manager/`](api_manager/) | HTTP and Apify actor gateway. Reads keys from the repo-root `.env`. |
| [`http/`](http/) | `requests` / `urllib` session, timeouts, and an opt-in `RetryPolicy`. Callers that do not retry stay single-attempt. |
| [`web/`](web/) | Website URL normalization and shared HTML signals (title, viewport, meta, CTA, HTTPS). |
| [`text/`](text/) | Business-name similarity (CRM/Facebook and registry/filing variants) and US phone checks. |
| [`maps/`](maps/) | Google Maps profile URL and place-id normalization. |
| [`crm/`](crm/) | JSON-RPC transport for the CRM MCP server. Lead ingest and opp finder keep their own handshake and payload wrappers. |
| [`browser/`](browser/) | Google Playwright close/sleep base, block-page check, backoff math, and route abort. |
| [`utils/logger/`](utils/logger/) | Colored console logs, a DEBUG file log, and optional upload. Package import: `helper_scripts.utils.logger.setup_logger`. |

**Local run:** these are libraries. The one registered entry is `api-manager-selftest` (`python helper_scripts/api_manager/api_manager.py` from the repo root, or `python -m scripts.script_manager run api-manager-selftest`).

**Secrets:** whichever API the caller names. The logger uploads only when `MVLLC_LOGS_KEY` is set. See [API manager](../documentation/helper_scripts/api_manager.md) and [logger](../documentation/helper_scripts/logger.md).

The old Raspberry Pi update manager was removed. Its historical note is [update_manager.md](../documentation/helper_scripts/update_manager.md).
