"""Pay-per-event prices for the Shopify store Actor.

Amounts match ``.actor/pay_per_event.json``. The shared ``SpendLedger`` counts
whole cents, so a $0.002 product would round to 0 and maxSpendUsd would never
stop the feed. ``CatalogLedger`` keeps the same can() / commit() contract in
micro-dollars. There is no proxy event and no CAPTCHA event.
"""

from __future__ import annotations

try:
    from .runtime import SpendLedger
except ImportError:
    from runtime import SpendLedger


PRODUCT_EVENT = "product"
STORE_EVENT = "store"

PRICES_USD = {
    PRODUCT_EVENT: 0.002,
    STORE_EVENT: 0.01,
}

_MICROS = 1_000_000


def to_micros(usd):
    return int(round(float(usd) * _MICROS + 1e-9))


class CatalogLedger(SpendLedger):
    """Run spend in micro-dollars. No proxy or CAPTCHA events exist here."""

    def __init__(self, max_spend_usd, prices_usd=None):
        prices = dict(PRICES_USD)
        if prices_usd:
            prices.update(prices_usd)
        self.prices = {name: to_micros(amount) for name, amount in prices.items()}
        self.max_spend = max(0, to_micros(max_spend_usd))
        self.max_proxy = 0
        self.spent = 0
        self.proxy_spent = 0
        self.counts = {name: 0 for name in self.prices}

    @property
    def spend_usd(self):
        return round(self.spent / _MICROS, 6)

    @property
    def proxy_spend_usd(self):
        return 0.0
