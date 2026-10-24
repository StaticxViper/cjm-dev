"""Pay-per-event prices and the run spend ledger.

Prices match ``.actor/pay_per_event.json``. Amounts are cents so a cap check
does not drift on binary floats. A charge is recorded only after the Actor
actually did the billable thing.
"""

from __future__ import annotations


PRICES_USD = {
    "business": 0.05,
    "enrichment": 0.03,
    "proxy": 0.01,
    "captcha": 1.00,
}

BUSINESS_EVENT = "business"
ENRICHMENT_EVENT = "enrichment"
PROXY_EVENT = "proxy"
CAPTCHA_EVENT = "captcha"


def to_cents(usd):
    return int(round(float(usd) * 100 + 1e-9))


PRICES_CENTS = {name: to_cents(amount) for name, amount in PRICES_USD.items()}


class Ledger:
    def __init__(self, max_spend_usd, max_proxy_usd):
        self.max_spend = max(0, to_cents(max_spend_usd))
        self.max_proxy = min(max(0, to_cents(max_proxy_usd)), self.max_spend)
        self.spent = 0
        self.proxy_spent = 0
        self.counts = {name: 0 for name in PRICES_USD}

    def can(self, event):
        price = PRICES_CENTS[event]
        if self.spent + price > self.max_spend:
            return False
        if event == PROXY_EVENT and self.proxy_spent + price > self.max_proxy:
            return False
        return True

    def commit(self, event):
        price = PRICES_CENTS[event]
        self.spent += price
        if event == PROXY_EVENT:
            self.proxy_spent += price
        self.counts[event] += 1

    @property
    def spend_usd(self):
        return round(self.spent / 100, 2)
