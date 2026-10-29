"""Retry wait used by browser fetches that already retry."""

from __future__ import annotations


def backoff_seconds(attempt, base):
    """Seconds to wait before retry. ``attempt`` is the zero-based failure index."""
    return base * (2 ** attempt)
