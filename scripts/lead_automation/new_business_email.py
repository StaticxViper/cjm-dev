"""New-business email enrichment. Never guesses an address."""
from __future__ import annotations

from urllib.parse import urlparse

from email_discovery import (
    NEW_BUSINESS_EMAIL_TEMPLATES,
    EmailDiscoverySession,
    _accept_confidence,
    _host_from_url,
    build_google_queries,
    cache_key,
    discover_business_website,
    extract_emails_from_html,
    inspect_website,
    is_directory_host,
    score_email_confidence,
    validate_email,
)
from website_quality import is_social_or_directory_url

_EMAIL_FIELDS = (
    "email",
    "has_email",
    "email_source",
    "email_confidence",
    "email_source_url",
    "email_evidence",
)


def _evidence_text(lead, email, city=None, state=None):
    return " ".join(
        part for part in (
            lead.get("email_evidence"),
            lead.get("business_name"),
            lead.get("city") or city,
            lead.get("state") or state,
            lead.get("phone") or lead.get("phone_google"),
            email,
        )
        if part
    )


def _apply_found(lead, email, source, confidence, source_url, evidence):
    lead["email"] = email
    lead["has_email"] = True
    lead["email_source"] = source
    lead["email_confidence"] = confidence
    lead["email_source_url"] = source_url or ""
    lead["email_evidence"] = (evidence or "")[:240]
    return lead


def _reject_email(lead):
    lead["email"] = ""
    lead["has_email"] = False
    lead["email_confidence"] = ""
    lead["email_source"] = ""
    lead["email_source_url"] = ""


def classify_email_source(page_url, html=""):
    url = (page_url or "").lower()
    body = html or ""
    if "mailto:" in body.lower() or url.startswith("mailto:"):
        return "website_mailto"
    if is_social_or_directory_url(page_url):
        if is_directory_host(page_url):
            return "directory"
        return "social_profile"
    path = urlparse(page_url).path.lower() if page_url else ""
    if "contact" in path:
        return "website_contact"
    if "about" in path:
        return "website_about"
    if "footer" in body.lower():
        return "website_footer"
    if page_url:
        return "website_contact" if "contact" in url else "other"
    return "other"


def _accept_source_email(lead, city, state, source_url, source_name):
    raw = lead.get("email") or ""
    email = validate_email(raw)
    if not email:
        if raw:
            _reject_email(lead)
        return False
    page_text = _evidence_text(lead, email, city, state)
    confidence = score_email_confidence(
        email,
        lead,
        page_url=source_url or lead.get("source_record_url") or "",
        page_text=page_text,
        website=lead.get("website"),
    )
    if not _accept_confidence(confidence):
        _reject_email(lead)
        return False
    _apply_found(
        lead,
        email,
        source_name,
        confidence,
        source_url or lead.get("source_record_url") or "",
        lead.get("email_evidence") or page_text,
    )
    return True


def _copy_cached(lead, cached):
    if not cached:
        return False
    for field in _EMAIL_FIELDS:
        if cached.get(field) and not lead.get(field):
            lead[field] = cached[field]
    if lead.get("email") and lead.get("email_confidence") in ("high", "medium"):
        lead["has_email"] = True
        return True
    return bool(lead.get("email_confidence") in ("high", "medium"))


def enrich_new_business_lead(
    lead,
    city=None,
    state=None,
    session=None,
    inspect_fn=None,
    allow_google=True,
):
    """Run the new-business email steps. Mutates and returns lead.

    Order: enrichment cache, source record, website, then Google templates.
    LOW confidence and junk addresses are discarded. Nothing is invented.
    """
    if lead is None:
        return lead
    own_session = session is None
    if session is None:
        session = EmailDiscoverySession()
    city = city or lead.get("city")
    state = state or lead.get("state")
    if not lead.get("phone_google") and lead.get("phone"):
        lead["phone_google"] = lead.get("phone")
    try:
        cached = None
        if hasattr(session, "persistent_result"):
            cached = session.persistent_result(lead, city, state)
        if cached is None:
            cached = session.cache.get(cache_key(lead, city, state))
        if _copy_cached(lead, cached):
            return lead

        if lead.get("email") and not lead.get("email_confidence"):
            if _accept_source_email(
                lead,
                city,
                state,
                lead.get("source_record_url"),
                "source_record",
            ):
                if hasattr(session, "remember_result"):
                    session.remember_result(lead, city, state)
                return lead

        website = (lead.get("website") or "").strip()
        if website and not is_social_or_directory_url(website) and not lead.get("email"):
            inspector = inspect_fn or inspect_website
            inspected = inspector(website)
            accepted = _pick(inspected.get("emails") or [], lead, inspected, website)
            if accepted:
                email, confidence = accepted
                page_url = inspected.get("page_url") or website
                source = classify_email_source(page_url, inspected.get("html") or "")
                if source in ("directory", "social_profile", "other") and "contact" in (page_url or "").lower():
                    source = "website_contact"
                _apply_found(
                    lead,
                    email,
                    source,
                    confidence,
                    page_url,
                    inspected.get("page_text") or "",
                )
                if hasattr(session, "remember_result"):
                    session.remember_result(lead, city, state)
                return lead

        if (
            allow_google
            and not lead.get("email")
            and not getattr(session, "google_blocked", False)
            and hasattr(session, "search")
        ):
            queries = build_google_queries(
                lead,
                city=city,
                state=state,
                templates=NEW_BUSINESS_EMAIL_TEMPLATES,
            )
            inspector = inspect_fn or inspect_website
            visited_hosts = set()
            known_host = _host_from_url(lead.get("website"))
            if known_host:
                visited_hosts.add(known_host)
            for query in queries:
                if getattr(session, "google_blocked", False) or lead.get("email"):
                    break
                results = session.search(query) or []
                for result in results:
                    if lead.get("email"):
                        break
                    page_url = result.get("url") or ""
                    snippet = result.get("snippet") or ""
                    page_text = f"{result.get('title') or ''} {snippet}"
                    seen_emails = []
                    for raw in list(result.get("emails") or []) + extract_emails_from_html(page_text):
                        if raw in seen_emails:
                            continue
                        seen_emails.append(raw)
                        email = validate_email(raw)
                        if not email:
                            continue
                        confidence = score_email_confidence(
                            email,
                            lead,
                            page_url=page_url,
                            page_text=page_text,
                            website=lead.get("website"),
                        )
                        if not _accept_confidence(confidence):
                            continue
                        source = "google_result"
                        if is_social_or_directory_url(page_url):
                            source = "directory" if is_directory_host(page_url) else "social_profile"
                        _apply_found(lead, email, source, confidence, page_url, snippet or page_text)
                        if hasattr(session, "remember_result"):
                            session.remember_result(lead, city, state)
                        return lead
                    if lead.get("email"):
                        break
                    found_site = discover_business_website([result], lead)
                    if not found_site or is_directory_host(found_site) or is_social_or_directory_url(found_site):
                        continue
                    host = _host_from_url(found_site)
                    if not host or host in visited_hosts:
                        continue
                    visited_hosts.add(host)
                    try:
                        inspected = inspector(found_site) or {}
                    except Exception:
                        continue
                    if not (lead.get("website") or "").strip():
                        lead["website"] = found_site
                        lead["website_search_ran"] = True
                    accepted = _pick(inspected.get("emails") or [], lead, inspected, found_site)
                    if not accepted:
                        continue
                    email, confidence = accepted
                    found_page = inspected.get("page_url") or found_site
                    _apply_found(
                        lead,
                        email,
                        classify_email_source(found_page, inspected.get("html") or ""),
                        confidence,
                        found_page,
                        inspected.get("page_text") or "",
                    )
                    if hasattr(session, "remember_result"):
                        session.remember_result(lead, city, state)
                    return lead
        if hasattr(session, "remember_result"):
            session.remember_result(lead, city, state)
        return lead
    finally:
        if own_session:
            session.close()


def _pick(emails, lead, inspected, website):
    ranked = []
    page_url = inspected.get("page_url") or website
    page_text = inspected.get("page_text") or ""
    for raw in emails:
        email = validate_email(raw)
        if not email:
            continue
        confidence = score_email_confidence(
            email,
            lead,
            page_url=page_url,
            page_text=page_text,
            website=website,
        )
        if _accept_confidence(confidence):
            ranked.append((email, confidence))
    if not ranked:
        return None
    ranked.sort(key=lambda item: 0 if item[1] == "high" else 1)
    return ranked[0]
