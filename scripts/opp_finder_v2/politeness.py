"""Per-site delay and request caps. One site is paced at a time by the pipeline."""

from __future__ import annotations

import random
import time
from typing import Callable

from opp_finder_v2.models import SiteConfig


class Pacer:
    def __init__(
        self,
        site: SiteConfig,
        *,
        dry_run: bool = False,
        max_per_site: int | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        limits = site.rate_limit or {}
        self.min_s = float(limits.get("min_delay_s", 3))
        self.max_s = float(limits.get("max_delay_s", self.min_s))
        if self.max_s < self.min_s:
            self.max_s = self.min_s
        self.max_requests = int(limits.get("max_requests", 20))
        self.max_results = int(limits.get("max_results", 50))
        if max_per_site is not None:
            self.max_results = min(self.max_results, int(max_per_site))
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


def retry_delay(attempt: int, retry_after: str | None = None) -> float:
    """Backoff for attempt 0 -> ~5s, later attempts -> ~15s, plus jitter.

    A numeric Retry-After header wins.
    """
    if retry_after:
        try:
            parsed = float(retry_after)
        except ValueError:
            parsed = None
        if parsed is not None and parsed >= 0:
            return parsed
    base = 5.0 if attempt == 0 else 15.0
    return base + random.uniform(0, 1.5)
