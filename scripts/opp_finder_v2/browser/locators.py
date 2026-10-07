"""Resolve ordered locator specs to the first Playwright locator that matches."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin


def _strategies(spec: Any) -> list[Any]:
    if spec is None:
        return []
    if isinstance(spec, str):
        return [{"css": spec}]
    if isinstance(spec, dict):
        return [spec]
    if isinstance(spec, list):
        return list(spec)
    return []


def _build(scope: Any, strategy: dict[str, Any]):
    if not isinstance(strategy, dict):
        return None
    if strategy.get("role"):
        name = strategy.get("name")
        if strategy.get("name_regex"):
            name = re.compile(strategy["name_regex"])
        if name is None:
            return scope.get_by_role(strategy["role"])
        return scope.get_by_role(strategy["role"], name=name)
    if strategy.get("test_id"):
        return scope.get_by_test_id(strategy["test_id"])
    if strategy.get("text"):
        return scope.get_by_text(strategy["text"])
    if strategy.get("css"):
        return scope.locator(strategy["css"])
    if strategy.get("attr"):
        return scope.locator(f"[{strategy['attr']}]")
    return None


def first_match(scope: Any, spec: Any):
    """Return (locator, strategy) for the first strategy that matches at least one node."""
    for strategy in _strategies(spec):
        if isinstance(strategy, str):
            strategy = {"css": strategy}
        locator = _build(scope, strategy)
        if locator is None:
            continue
        try:
            if locator.count() > 0:
                return locator, strategy
        except Exception:
            continue
    return None, None


def all_matches(scope: Any, spec: Any):
    """Return every node for the first strategy that matches, plus that strategy."""
    locator, strategy = first_match(scope, spec)
    if locator is None:
        return [], None
    try:
        return locator.all(), strategy
    except Exception:
        return [], strategy


def read_text(locator: Any, strategy: dict[str, Any] | None, base_url: str) -> str | None:
    strategy = strategy or {}
    try:
        if strategy.get("attr"):
            raw = locator.get_attribute(strategy["attr"])
        else:
            raw = locator.inner_text()
    except Exception:
        return None
    if raw is None:
        return None
    text = str(raw).strip()
    pattern = strategy.get("regex")
    if pattern:
        match = re.search(pattern, text)
        if not match:
            return None
        text = match.group(1) if match.groups() else match.group(0)
        text = text.strip()
    if strategy.get("absolute_url") and text:
        text = urljoin(base_url.rstrip("/") + "/", text)
    return text or None
