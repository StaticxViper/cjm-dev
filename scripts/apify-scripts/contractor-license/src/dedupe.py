"""One row per state plus license number. A later row fills empty fields.

The merge follows opp_finder_v2.dedupe: keep a known value, and prefer the
longer text when both sides have a name, class, address, or status.
"""

from __future__ import annotations

try:
    from .adapters.base import license_key
except ImportError:
    from adapters.base import license_key


_LONGER = ("name", "status", "class", "address", "bond", "insurance")
_FILL = _LONGER + ("issue_date", "expiry_date", "source_url", "license_no")


def _text(row, field):
    return (row.get(field) or "").strip()


def merge_license_rows(existing, incoming):
    merged = dict(existing)
    for field in _FILL:
        current = _text(existing, field)
        new = _text(incoming, field)
        if not current and new:
            merged[field] = incoming.get(field) or ""
        elif field in _LONGER and new and len(new) > len(current):
            merged[field] = incoming.get(field) or ""
    return merged


def dedupe_licenses(rows):
    """Collapse found rows that share a license number. Other statuses pass through."""
    by_key = {}
    order = []
    rest = []
    for row in rows or []:
        if row.get("sourceStatus") != "found":
            rest.append(row)
            continue
        key = (row.get("state") or "", license_key(row.get("license_no")))
        if not key[1]:
            rest.append(row)
            continue
        if key not in by_key:
            by_key[key] = dict(row)
            order.append(key)
            continue
        by_key[key] = merge_license_rows(by_key[key], row)
    return [by_key[key] for key in order] + rest
