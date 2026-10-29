#!/usr/bin/env python3
"""Fill a missing agent email or phone from Google and public pages.

A value is kept only when the agent name agrees and the brokerage or the
search area also agrees. Weaker matches stay blank.
"""
from __future__ import annotations

from pathlib import Path
import sys

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[1]
_SCRIPTS = _SCRIPT_DIR.parent
_LEAD = _SCRIPTS / "lead_automation"
for _entry in (_REPO_ROOT, _SCRIPTS, _LEAD):
    _text = str(_entry)
    if _text not in sys.path:
        sys.path.insert(0, _text)

import re

from crm_enrich_match import GENERIC_TOKENS, distinctive_token_missing, normalize_match_name
from email_discovery import (
    _domains_match,
    _host_from_url,
    build_google_queries,
    discover_business_website,
    extract_emails_from_html,
    extract_phones_from_html,
    inspect_website,
    is_valid_us_phone,
    validate_email,
)
from leadenrich import name_similarity, normalize_business_name
from leadenrich_playwright import classify_serp_results

from zillow_parse import agent_key


MIN_NAME_SIMILARITY = 0.72
MAX_GOOGLE_QUERIES = 4
MAX_PAGES = 3
SOURCE_WEBSITE = "website"


def needs_contact(agent):
    return not str((agent or {}).get("email") or "").strip() or not str((agent or {}).get("phone") or "").strip()


def agent_cache_id(agent, area):
    loc = normalize_match_name(area)
    return f"{agent_key(agent)}|{loc}"


def _comparison_name(value):
    norm = normalize_match_name(value)
    tokens = [token for token in norm.split() if token not in GENERIC_TOKENS]
    return " ".join(tokens) or norm


def name_agrees(expected, text):
    """True when the name's tokens are present and the similarity is strong."""
    expected_norm = _comparison_name(expected)
    page_norm = normalize_business_name(text or "")
    if not expected_norm or not page_norm:
        return False
    if distinctive_token_missing(expected_norm, page_norm):
        return False
    similarity = name_similarity(expected_norm, page_norm)
    if len(expected_norm.split()) < 2 and expected_norm in page_norm.split():
        similarity = 1.0
    return similarity >= MIN_NAME_SIMILARITY


def area_agrees(area, text):
    raw = (area or "").strip()
    if not raw:
        return False
    lowered = (text or "").lower()
    if re.fullmatch(r"\d{5}", raw):
        return raw in lowered
    for zip_code in re.findall(r"\b\d{5}\b", raw):
        if zip_code in lowered:
            return True
    cleaned = re.sub(r"\bcounty\b", " ", raw, flags=re.I)
    tokens = [token for token in normalize_match_name(cleaned).split() if len(token) > 2]
    if not tokens:
        return False
    page_tokens = set(normalize_business_name(text or "").split())
    return all(token in page_tokens for token in tokens)


def contact_confidence(agent, area, page_text, page_url=""):
    """100 when name, brokerage, and area agree; 80 when name plus one of them."""
    blob = f"{page_text or ''} {page_url or ''}"
    if not name_agrees((agent or {}).get("agent_name"), blob):
        return 0
    brokerage = (agent or {}).get("brokerage") or ""
    broker_ok = bool(brokerage) and name_agrees(brokerage, blob)
    area_ok = area_agrees(area, blob)
    if broker_ok and area_ok:
        return 100
    if broker_ok or area_ok:
        return 80
    return 0


def lead_from_agent(agent, area):
    return {
        "lead_id": agent_cache_id(agent, area),
        "business_name": (agent or {}).get("agent_name") or "",
        "address": area or "",
        "website": "",
        "phone": (agent or {}).get("phone") or "",
        "phone_google": (agent or {}).get("phone") or "",
        "email": (agent or {}).get("email") or "",
    }


def build_agent_queries(agent, area, max_queries=MAX_GOOGLE_QUERIES):
    name = ((agent or {}).get("agent_name") or "").strip()
    brokerage = ((agent or {}).get("brokerage") or "").strip()
    queries = []
    if name and brokerage:
        queries.append(f'"{name}" "{brokerage}" {area}'.strip())
    if name:
        queries.append(f'"{name}" {area} email'.strip())
    lead = lead_from_agent(agent, area)
    for query in build_google_queries(lead, max_queries=max_queries):
        if query not in queries:
            queries.append(query)
        if len(queries) >= max_queries:
            break
    return queries[:max_queries]


def _skip_url(url):
    host = _host_from_url(url)
    if not host:
        return True
    return host.endswith("zillow.com") or host.endswith("google.com") or host == "google.com"


def select_visit_urls(results, lead, agent, limit=MAX_PAGES):
    """Agent site, brokerage page, then at most one directory page."""
    classified = classify_serp_results(results, lead)
    websites = [item for item in classified if item.get("kind") == "website"]
    directories = [item for item in classified if item.get("kind") == "directory"]
    serp = [
        {
            "url": item.get("url"),
            "title": item.get("title") or "",
            "snippet": item.get("snippet") or "",
        }
        for item in websites
    ]
    official = discover_business_website(serp, lead)
    chosen = []

    def add(url):
        if not url or url in chosen or _skip_url(url):
            return
        chosen.append(url)

    add(official)
    brokerage = (agent or {}).get("brokerage") or ""
    for item in websites:
        blob = f"{item.get('title') or ''} {item.get('snippet') or ''} {item.get('url') or ''}"
        if brokerage and name_agrees(brokerage, blob):
            add(item.get("url"))
            break
    if len(chosen) < 2:
        for item in websites:
            add(item.get("url"))
            if len(chosen) >= 2:
                break
    for item in directories:
        add(item.get("url"))
        if len(chosen) >= limit:
            break
    return chosen[:limit]


def choose_email(emails, page_url):
    valid = []
    for email in emails or []:
        cleaned = validate_email(email)
        if cleaned and cleaned not in valid:
            valid.append(cleaned)
    if not valid:
        return ""
    host = _host_from_url(page_url)
    for email in valid:
        domain = email.rsplit("@", 1)[-1]
        if _domains_match(domain, host):
            return email
    return valid[0]


def choose_phone(page_text, agent_name, phones):
    valid = []
    for phone in phones or []:
        if is_valid_us_phone(phone) and phone not in valid:
            valid.append(phone)
    if not valid:
        return ""
    if len(valid) == 1:
        return valid[0]
    lowered = (page_text or "").lower()
    name_at = lowered.find((agent_name or "").lower()) if agent_name else -1
    best = valid[0]
    best_dist = None
    for phone in valid:
        digits = re.sub(r"\D", "", phone)
        area = digits[-10:-7] if len(digits) >= 10 else digits[:3]
        idx = (page_text or "").find(area) if area else -1
        dist = abs((idx if idx >= 0 else 10**9) - (name_at if name_at >= 0 else 0))
        if best_dist is None or dist < best_dist:
            best = phone
            best_dist = dist
    return best


def _apply_page(agent, area, inspected):
    page_url = (inspected or {}).get("page_url") or ""
    page_text = (inspected or {}).get("page_text") or ""
    score = contact_confidence(agent, area, page_text, page_url)
    if score < 80:
        return False
    changed = False
    if not str(agent.get("email") or "").strip():
        emails = list(inspected.get("emails") or [])
        if not emails and inspected.get("html"):
            emails = extract_emails_from_html(inspected.get("html"))
        email = choose_email(emails, page_url)
        if email:
            agent["email"] = email
            changed = True
    if not str(agent.get("phone") or "").strip():
        phones = list(inspected.get("phones") or [])
        if not phones and inspected.get("html"):
            phones = extract_phones_from_html(inspected.get("html"))
        phone = choose_phone(page_text, agent.get("agent_name"), phones)
        if phone:
            agent["phone"] = phone
            changed = True
    if changed:
        agent["enrichment_source"] = SOURCE_WEBSITE
        agent["enrichment_source_url"] = page_url
        agent["confidence"] = score
    return changed


def _cache_lead(agent, area):
    lead = lead_from_agent(agent, area)
    lead["email"] = agent.get("email") or ""
    lead["has_email"] = bool(lead["email"])
    lead["email_source"] = agent.get("enrichment_source") or ""
    lead["email_source_url"] = agent.get("enrichment_source_url") or ""
    confidence = agent.get("confidence")
    lead["email_confidence"] = "" if confidence in (None, "") else str(confidence)
    lead["phone_website"] = agent.get("phone") or ""
    return lead


def _apply_cached(agent, cached):
    if not cached:
        return
    if not str(agent.get("email") or "").strip() and cached.get("email"):
        agent["email"] = cached["email"]
    if not str(agent.get("phone") or "").strip() and cached.get("phone_website"):
        agent["phone"] = cached["phone_website"]
    if not agent.get("enrichment_source") and cached.get("email_source"):
        agent["enrichment_source"] = cached["email_source"]
    if not agent.get("enrichment_source_url") and cached.get("email_source_url"):
        agent["enrichment_source_url"] = cached["email_source_url"]
    if agent.get("confidence") in (None, "") and cached.get("email_confidence"):
        raw = str(cached["email_confidence"])
        agent["confidence"] = int(raw) if raw.isdigit() else raw


def enrich_agent(agent, area, session, inspect=None, max_pages=MAX_PAGES, before_visit=None):
    """Search and visit likely pages. Leave email and phone blank when unsure."""
    if agent is None or not needs_contact(agent):
        return agent
    if not agent_key(agent):
        return agent
    inspect = inspect or inspect_website
    lead = lead_from_agent(agent, area)
    cached = session.persistent_result(lead) if session is not None else None
    if cached is None and session is not None:
        cached = session.cache.get(agent_cache_id(agent, area))
    if cached is not None:
        _apply_cached(agent, cached)
        return agent
    if session is None or session.google_blocked:
        return agent

    found = False
    visited = set()
    for query in build_agent_queries(agent, area):
        if session.google_blocked or not needs_contact(agent):
            break
        results = session.search(query) or []
        for url in select_visit_urls(results, lead, agent, limit=max_pages):
            if url in visited or not needs_contact(agent):
                continue
            if len(visited) >= max_pages:
                break
            visited.add(url)
            if before_visit is not None and not before_visit(url):
                continue
            try:
                inspected = inspect(url)
            except Exception:
                continue
            if not isinstance(inspected, dict):
                continue
            if _apply_page(agent, area, inspected):
                found = True
    if found or not session.google_blocked:
        session.remember_result(_cache_lead(agent, area))
    return agent


def enrich_agents(agents, session, inspect=None, before_visit=None):
    """Enrich each agent that is still missing an email or phone."""
    enriched = 0
    for agent in agents or []:
        area = agent.get("area") or ""
        if not needs_contact(agent):
            continue
        before_email = str(agent.get("email") or "")
        before_phone = str(agent.get("phone") or "")
        enrich_agent(agent, area, session, inspect=inspect, before_visit=before_visit)
        email_filled = (not before_email) and str(agent.get("email") or "")
        phone_filled = (not before_phone) and str(agent.get("phone") or "")
        if email_filled or phone_filled:
            enriched += 1
    return enriched
