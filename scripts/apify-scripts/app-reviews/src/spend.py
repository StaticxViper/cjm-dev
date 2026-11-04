"""Pay-per-event prices for the app reviews Actor.

Amounts match ``.actor/pay_per_event.json``. The shared ``SpendLedger`` in
``scripts/apify-scripts/access.py`` counts whole cents, so a $0.001 review
would round to 0 and maxSpendUsd would never stop the feed. ``ReviewLedger``
keeps the same can() / commit() contract in micro-dollars.

$0.001 is the top of the brief's unverified $0.0005–0.001 range. thewolves
Store comps were not confirmed for this build.
"""

from __future__ import annotations

try:
    from .runtime import SpendLedger
except ImportError:
    from runtime import SpendLedger


REVIEW_EVENT = "review"
SENTIMENT_EVENT = "sentiment"

PRICES_USD = {
    REVIEW_EVENT: 0.001,
    SENTIMENT_EVENT: 0.0005,
}

_MICROS = 1_000_000


def to_micros(usd):
    return int(round(float(usd) * _MICROS + 1e-9))


class ReviewLedger(SpendLedger):
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

    def fits(self, events):
        """True when every event in ``events`` still fits under the cap together."""
        total = 0
        for event in events:
            price = self.prices.get(event)
            if price is None:
                return False
            total += price
        return self.spent + total <= self.max_spend

    def affordable(self, events, wanted):
        """How many repetitions of ``events`` still fit under the cap."""
        total = 0
        for event in events:
            price = self.prices.get(event)
            if not price:
                return 0
            total += price
        room = max(0, self.max_spend - self.spent)
        return min(wanted, room // total)
