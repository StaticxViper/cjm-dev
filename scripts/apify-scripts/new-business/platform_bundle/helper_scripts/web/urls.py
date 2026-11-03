"""Website URL normalization shared by lead scripts."""

from __future__ import annotations

from urllib.parse import urlparse


def ensure_http_url(url):
    """Add https:// when a URL has no scheme. Falsy values are returned as given."""
    if not url:
        return url
    if str(url).startswith("//"):
        url = "https:" + url
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def normalize_website_url(url):
    """Strip and normalize. Missing values become an empty string."""
    if not url:
        return ""
    return ensure_http_url(str(url).strip())
