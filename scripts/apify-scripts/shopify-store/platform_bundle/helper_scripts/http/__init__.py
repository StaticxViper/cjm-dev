"""Shared HTTP GET helpers. Retries are opt-in."""

from helper_scripts.http.client import (
    CHROME_USER_AGENT,
    HTML_ACCEPT,
    HTML_JSON_ACCEPT,
    RetryPolicy,
    actor_text_delay,
    fetch_url_text,
    html_headers,
    html_json_headers,
    polite_delay,
    requests_get,
)

__all__ = [
    "CHROME_USER_AGENT",
    "HTML_ACCEPT",
    "HTML_JSON_ACCEPT",
    "RetryPolicy",
    "actor_text_delay",
    "fetch_url_text",
    "html_headers",
    "html_json_headers",
    "polite_delay",
    "requests_get",
]
