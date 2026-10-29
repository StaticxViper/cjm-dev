"""Abort Playwright routes for resource types a scraper does not need."""

from __future__ import annotations


def resource_type_blocked(resource_type, blocked_types):
    return resource_type in blocked_types


def continue_or_abort(route, blocked):
    if blocked:
        route.abort()
        return
    route.continue_()
