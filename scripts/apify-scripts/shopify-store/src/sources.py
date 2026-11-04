"""Public Shopify storefront URLs. No admin API and no token.

``/products.json`` and ``/collections.json`` are the catalog feeds Shopify
themes request without auth. The homepage is read only for ``Shopify.theme``
and script URLs. ``/meta.json`` is not a stable public catalog route, so it
is not requested.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


PAGE_LIMIT = 250
MAX_PRODUCT_PAGES = 20
MAX_COLLECTION_PAGES = 4
MAX_COLLECTIONS = 500
MAX_DOMAINS = 100

STATE_STORE = "shopify-store-state"
_STORE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")


def normalize_domain(value):
    """Return a lowercase host, or ``""`` when the value is not a public host."""
    text = str(value or "").strip()
    if not text or any(char.isspace() for char in text):
        return ""
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.username or parsed.password:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host or ".." in host:
        return ""
    if any(char in host for char in ("/", "?", "#", "@", " ")):
        return ""
    return host


def origin(domain):
    return f"https://{domain}"


def products_url(domain, page, limit):
    return f"{origin(domain)}/products.json?limit={int(limit)}&page={int(page)}"


def collections_url(domain, page, limit):
    return f"{origin(domain)}/collections.json?limit={int(limit)}&page={int(page)}"


def homepage_url(domain):
    return f"{origin(domain)}/"


def product_url(domain, handle):
    handle = str(handle or "").strip().strip("/")
    if not handle:
        return origin(domain)
    return f"{origin(domain)}/products/{handle}"


def state_store_name(value):
    text = str(value or "").strip()
    if _STORE_NAME.fullmatch(text):
        return text
    return STATE_STORE
