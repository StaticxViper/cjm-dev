"""Route one license query to the state adapter."""

from __future__ import annotations

try:
    from .adapters import ADAPTERS
    from .adapters.base import LicenseQuery, status_row
except ImportError:
    from adapters import ADAPTERS
    from adapters.base import LicenseQuery, status_row


def run_lookup(config, fetch):
    query = config.get("query") or LicenseQuery("", "", "", "", 25)
    if config.get("error"):
        return [status_row(query, "error", config["error"])], False
    adapter = ADAPTERS.get(query.state)
    if adapter is None:
        return [
            status_row(
                query,
                "unsupported",
                f"No adapter for {query.state}. Supported states are CA, AZ, NJ, and PA.",
            ),
        ], False
    result = adapter(query, fetch)
    return result["rows"], bool(result.get("truncated"))
