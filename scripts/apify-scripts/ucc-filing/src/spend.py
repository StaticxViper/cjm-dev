"""Pay-per-event prices for UCC filings.

Amounts match ``.actor/pay_per_event.json``. The shared cent ledger would
round $0.008 badly, so this ledger uses micro-dollars and the same
``fits()`` / ``commit()`` contract as the other HTTP Actors. There is no
proxy or CAPTCHA price.
"""

from __future__ import annotations

try:
    from .runtime import SpendLedger
except ImportError:
    from runtime import SpendLedger


FILING_EVENT = "filing"

PRICES_USD = {
    FILING_EVENT: 0.008,
}

_MICROS = 1_000_000


def to_micros(usd):
    return int(round(float(usd) * _MICROS + 1e-9))


class FilingLedger(SpendLedger):
    """Run spend in micro-dollars. Status rows are not an event."""

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

    def fits(self, events):
        """True when every event in ``events`` still fits under the cap together."""
        total = 0
        for event in events:
            price = self.prices.get(event)
            if price is None:
                return False
            total += price
        return self.spent + total <= self.max_spend
