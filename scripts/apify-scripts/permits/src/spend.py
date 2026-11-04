"""Pay-per-event prices for the permit Actor.

Local cap schedule. Store billing is ``.actor/pay_per_event.json``. The shared spend ledger in
``scripts/apify-scripts/access.py`` records a charge only after the run
actually did the billable thing.
"""

from __future__ import annotations


PRICES_USD = {
    "permit": 0.05,
    "proxy": 0.01,
    "captcha": 1.00,
}

PERMIT_EVENT = "permit"
