#!/usr/bin/env python3
"""RFC 9309 longest-match robots.txt evaluation.

Python's urllib.robotparser applies rules in file order, so Google's
``Disallow: /maps/`` hides the later ``Allow: /maps/search/`` and
``Allow: /maps/place/`` lines. This module follows the longest-match rule
instead. robots.txt is not permission to automate Google Maps.
"""
from __future__ import annotations

from urllib.parse import urlparse
import re

MAPS_SEARCH_URL = "https://www.google.com/maps/search/x"
MAPS_PLACE_URL = "https://www.google.com/maps/place/x"
GOOGLE_WEB_SEARCH_URL = "https://www.google.com/search?q=x"

ACCESS_OK = "ok"
ACCESS_ROBOTS = "robots_disallowed"


def _compile_pattern(pattern):
    """Return a regex and the specificity length of a robots path pattern."""
    if pattern is None:
        return None, 0
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    specificity = len(body.replace("*", ""))
    parts = []
    for piece in re.split(r"(\*)", body):
        if piece == "*":
            parts.append(".*")
        elif piece:
            parts.append(re.escape(piece))
    regex = "".join(parts)
    if not regex:
        return None, 0
    if anchored:
        regex += "$"
    return re.compile(regex), specificity


def parse_robots(text):
    """Parse robots.txt into groups of user-agents and allow/disallow rules."""
    groups = []
    current = None
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current is None or current["rules"]:
                current = {"agents": [], "rules": []}
                groups.append(current)
            current["agents"].append(value.lower())
        elif key in {"allow", "disallow"} and current is not None:
            current["rules"].append((key == "allow", value))
    return groups


def _select_group(groups, user_agent):
    ua = (user_agent or "*").lower()
    best = None
    best_len = -1
    star = None
    for group in groups:
        for agent in group["agents"]:
            if agent == "*":
                if star is None:
                    star = group
                continue
            if ua == agent or (agent != "*" and agent in ua):
                if len(agent) > best_len:
                    best = group
                    best_len = len(agent)
    return best if best is not None else star


def robots_allowed(robots_txt, url, user_agent="*"):
    """Return True when ``url`` is allowed for ``user_agent`` under RFC 9309.

    The longest matching Allow/Disallow pattern wins. Equal lengths prefer
    Allow. No matching rule means allowed. An empty Disallow pattern is ignored
    (it means "allow all" and has no specific path).
    """
    path = urlparse(url).path or "/"
    if not path.startswith("/"):
        path = "/" + path
    group = _select_group(parse_robots(robots_txt), user_agent)
    if group is None:
        return True
    best_len = -1
    best_allow = True
    for allow, pattern in group["rules"]:
        if pattern == "":
            continue
        compiled, specificity = _compile_pattern(pattern)
        if compiled is None or compiled.match(path) is None:
            continue
        if specificity > best_len or (specificity == best_len and allow and not best_allow):
            best_len = specificity
            best_allow = allow
    return True if best_len < 0 else best_allow


def google_maps_allowed(robots_txt, user_agent="*"):
    """True when both Maps search and Maps place URLs are allowed."""
    return robots_allowed(robots_txt, MAPS_SEARCH_URL, user_agent) and robots_allowed(
        robots_txt, MAPS_PLACE_URL, user_agent
    )


def apply_robots_gate(robots_txt, sources, user_agent="*"):
    """Disable sources robots.txt disallows. Google web search is never enabled.

    Returns ``(enabled_sources, status)``. ``status['google_web_search']`` is
    reported even though this tool does not request /search.
    """
    status = {}
    search_ok = robots_allowed(robots_txt, GOOGLE_WEB_SEARCH_URL, user_agent)
    status["google_web_search"] = ACCESS_OK if search_ok else ACCESS_ROBOTS
    maps_ok = google_maps_allowed(robots_txt, user_agent)
    enabled = []
    for source in sources or []:
        if source == "maps_playwright":
            if maps_ok:
                enabled.append(source)
                status[source] = ACCESS_OK
            else:
                status[source] = ACCESS_ROBOTS
        elif source in {"website", "places_api"}:
            enabled.append(source)
            status[source] = ACCESS_OK
        else:
            status[source] = ACCESS_ROBOTS
    return enabled, status
