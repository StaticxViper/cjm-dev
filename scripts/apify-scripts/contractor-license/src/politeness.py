"""Per-run delay and request cap.

Same shape as opp_finder_v2.politeness.Pacer: sleep between requests, stop
when the cap is hit. This Actor does not import SiteConfig.
"""

from __future__ import annotations

import random
import time
from typing import Callable


class Pacer:
    def __init__(
        self,
        *,
        min_s: float = 2.0,
        max_s: float | None = None,
        max_requests: int = 4,
        sleep: Callable[[float], None] | None = None,
        dry_run: bool = False,
    ):
        self.min_s = float(min_s)
        self.max_s = float(self.min_s if max_s is None else max_s)
        if self.max_s < self.min_s:
            self.max_s = self.min_s
        self.max_requests = int(max_requests)
        self.dry_run = dry_run
        self.made = 0
        self._sleep = sleep or time.sleep

    def acquire(self) -> bool:
        if self.made >= self.max_requests:
            return False
        if self.made > 0 and not self.dry_run:
            self._sleep(random.uniform(self.min_s, self.max_s))
        self.made += 1
        return True
