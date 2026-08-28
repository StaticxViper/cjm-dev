#!/usr/bin/env python3
"""
leadenrich.py

Facebook Email Enrichment for Google Places Leads

Most leads from leadgen.py have no email on their website (or have no website at
all), but the business usually publishes one on its Facebook Page. For every
lead missing an email this script resolves a Facebook Page URL -- from the
lead's own website when that website is already a Facebook Page, otherwise from
a Facebook page search -- then pulls the contact email off that page.

Run: python leadenrich.py --json-path leads_output.json
"""
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from helper_scripts.api_manager import APIManager
from helper_scripts.utils.logger.logger import setup_logger

load_dotenv()

# -----------------------------
# Configurable constants
# -----------------------------
APIFY_API_KEY = os.getenv("APIFY_API_KEY")
SEARCH_ACTOR = "Facebook Search"  # danek/facebook-search-ppr
PAGES_ACTOR = "Facebook Pages Scraper"  # apify/facebook-pages-scraper
PAGE_SCRAPE_BATCH = 25  # startUrls per Facebook Pages Scraper run
DEFAULT_JSON_PATH = "leads_output.json"

ENRICHMENT_SOURCE = "facebook"
STATUS_ENRICHED = "enriched"
STATUS_NO_PAGE = "no_page_match"
STATUS_NO_EMAIL = "no_email_on_page"
STATUS_SCRAPE_FAILED = "scrape_failed"
# Only transient failures are re-attempted on a later run; a page that simply
# has no email will not grow one, and re-running costs Apify credits.
RETRYABLE_STATUSES = frozenset({STATUS_SCRAPE_FAILED})

FACEBOOK_HOSTS = frozenset({"facebook.com", "m.facebook.com", "web.facebook.com", "fb.com", "fb.me"})
NON_PAGE_SEGMENTS = frozenset({
    "groups", "events", "marketplace", "watch", "reel", "video", "story",
    "people", "search", "hashtag", "login", "help", "policies", "sharer",
})
COUNTRY_ALIASES = {"USA": "United States", "US": "United States"}

# Search results and page items come from two different actors, so read the
# name/URL through the key variants each one uses rather than a single field.
SEARCH_NAME_KEYS = ("name", "title", "pageName", "page_name")
SEARCH_URL_KEYS = (
    "url", "profile_url", "profileUrl", "pageUrl", "page_url",
    "facebookUrl", "facebook_url", "link",
)
PAGE_URL_KEYS = ("pageUrl", "facebookUrl", "url")

NAME_APOSTROPHE_RE = re.compile(r"['\u2018\u2019\u02bc]")
NAME_PUNCTUATION_RE = re.compile(r"[^a-z0-9]+")
NAME_STOPWORDS = frozenset({
    "the", "a", "an", "and", "of", "llc", "inc", "incorporated", "co", "corp",
    "corporation", "ltd", "limited", "company", "pllc", "lp", "llp",
})

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_DOMAIN_BLOCKLIST = ("facebook.com", "fb.com", "sentry", "wixpress", "example.com")
EMAIL_EXTENSION_BLOCKLIST = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

logger = setup_logger(
    name="leadenrich",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)


@dataclass
class EnrichConfig:
    json_path: str = DEFAULT_JSON_PATH
    output_path: str = None
    limit: int = 0
    min_similarity: float = 0.72
    max_search_results: int = 5
    max_workers: int = 4
    retry_all: bool = False
    dry_run: bool = False
    dashboard: bool = False


def _iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _first_string(item, keys):
    """Return the first non-empty string value among keys."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_facebook_url(url):
    """Return a canonical facebook.com page URL, or None if it is not a page URL."""
    if not isinstance(url, str) or not url.strip():
        return None

    candidate = url.strip()
    if "://" not in candidate:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host not in FACEBOOK_HOSTS:
        return None

    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None

    # New pages have no vanity slug and are only reachable by numeric id.
    if segments[0] == "profile.php":
        page_id = (parse_qs(parsed.query).get("id") or [""])[0].strip()
        return f"https://www.facebook.com/profile.php?id={page_id}" if page_id.isdigit() else None

    # Legacy pages keep their id in the path: /pages/<name>/<id>
    if segments[0] == "pages" and len(segments) >= 3:
        return f"https://www.facebook.com/pages/{segments[1]}/{segments[2]}"

    if segments[0] == "pg" and len(segments) > 1:
        segments = segments[1:]

    slug = segments[0]
    if slug.lower() in NON_PAGE_SEGMENTS or slug.lower().endswith(".php"):
        return None
    return f"https://www.facebook.com/{slug}"


def normalize_business_name(name):
    """Lowercase and strip punctuation plus legal suffixes so names compare cleanly."""
    lowered = (name or "").lower().replace("&", " and ")
    # Apostrophes are dropped rather than split on, so "Joe's" stays one token.
    tokens = NAME_PUNCTUATION_RE.sub(" ", NAME_APOSTROPHE_RE.sub("", lowered)).split()
    return " ".join(token for token in tokens if token not in NAME_STOPWORDS)


def name_similarity(left, right):
    """Return 0.0-1.0 similarity between two normalized business names."""
    if not left or not right:
        return 0.0

    ratio = SequenceMatcher(None, left, right).ratio()
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    smaller = min(len(left_tokens), len(right_tokens))
    if smaller < 2:
        return ratio

    # Facebook Pages often append a location or service list to the business
    # name, so full containment of the shorter name is a strong signal.
    containment = len(left_tokens & right_tokens) / smaller
    return max(ratio, containment * 0.95)


def location_hint(address):
    """Return a 'City, Country' hint for the search actor, or None if unparseable."""
    parts = [part.strip() for part in (address or "").split(",") if part.strip()]
    if len(parts) < 3:
        return None
    country = COUNTRY_ALIASES.get(parts[-1].upper(), parts[-1])
    return f"{parts[-3]}, {country}"


def clean_emails(values):
    """Return lowercase deduped emails found in arbitrary strings, minus known junk."""
    found = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        for match in EMAIL_RE.findall(value):
            email = match.strip().lower().rstrip(".")
            if email in seen:
                continue
            if email.endswith(EMAIL_EXTENSION_BLOCKLIST):
                continue
            domain = email.rsplit("@", 1)[-1]
            if any(blocked in domain for blocked in EMAIL_DOMAIN_BLOCKLIST):
                continue
            seen.add(email)
            found.append(email)
    return found


def extract_page_email(page):
    """Return the best email from a Facebook Pages Scraper item, or None."""
    if not isinstance(page, dict):
        return None

    about = page.get("about_me") if isinstance(page.get("about_me"), dict) else {}
    fields = [page.get("email"), page.get("intro"), about.get("text")]
    fields.extend(page.get("info") or [])
    fields.extend(page.get("websites") or [])
    fields.extend(about.get("urls") or [])

    emails = clean_emails(fields)
    return emails[0] if emails else None


def best_page_match(business_name, results, min_similarity):
    """Return (url, score, matched_name) for the closest page above the threshold."""
    target = normalize_business_name(business_name)
    best_url = None
    best_score = 0.0
    best_name = None

    for item in results or []:
        if not isinstance(item, dict):
            continue
        # The search actor tags each result; drop places/posts that slip through.
        item_type = item.get("type")
        if isinstance(item_type, str) and item_type.strip().lower() != "page":
            continue
        url = normalize_facebook_url(_first_string(item, SEARCH_URL_KEYS))
        if not url:
            continue
        name = _first_string(item, SEARCH_NAME_KEYS) or ""
        score = name_similarity(target, normalize_business_name(name))
        if score > best_score:
            best_url, best_score, best_name = url, score, name

    if best_score < min_similarity:
        return None, best_score, best_name
    return best_url, best_score, best_name


def search_facebook_page(business_name, address=None, max_results=5):
    """Run the Facebook search actor restricted to pages and return raw result items."""
    run_input = {
        "query": business_name,
        "search_type": "pages",
        "max_posts": max_results,
    }
    location = location_hint(address)
    if location:
        run_input["location"] = location

    try:
        return APIManager().run_apify(actor=SEARCH_ACTOR, input=run_input) or []
    except Exception as e:
        logger.error("Facebook page search failed for %s: %s", business_name, e)
        return []


def scrape_facebook_pages(urls, batch_size=PAGE_SCRAPE_BATCH):
    """Run the Facebook Pages Scraper in batches; returns {canonical_url: page_item}."""
    pages = {}
    urls = sorted(set(urls))
    for batch in _chunked(urls, batch_size):
        logger.critical("Scraping %d Facebook Pages", len(batch))
        run_input = {"startUrls": [{"url": url} for url in batch]}
        try:
            items = APIManager().run_apify(actor=PAGES_ACTOR, input=run_input) or []
        except Exception as e:
            logger.error("Facebook page scrape failed for %d pages: %s", len(batch), e)
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            # The scraper echoes the requested URL and also returns the page's
            # canonical URL and slug; index all of them so lookups always hit.
            keys = [normalize_facebook_url(item.get(key)) for key in PAGE_URL_KEYS]
            page_name = item.get("pageName")
            if isinstance(page_name, str) and page_name.strip():
                keys.append(f"https://www.facebook.com/{page_name.strip()}")
            for key in keys:
                if key:
                    pages.setdefault(key, item)

    return pages


def lead_has_email(lead):
    return bool((lead.get("email") or "").strip())


def needs_enrichment(lead, retry_all=False):
    """True when a lead has no email and has not already been through enrichment."""
    if lead_has_email(lead):
        return False
    enrichment = lead.get("enrichment") or {}
    if retry_all or enrichment.get("source") != ENRICHMENT_SOURCE:
        return True
    return enrichment.get("status") in RETRYABLE_STATUSES


def resolve_page_urls(leads, config):
    """Return {lead_index: (facebook_url, source)} using the lead website, then search."""
    resolved = {}
    needs_search = []
    for index, lead in enumerate(leads):
        url = normalize_facebook_url(lead.get("website"))
        if url:
            resolved[index] = (url, "website")
        else:
            needs_search.append(index)

    if not needs_search:
        return resolved

    logger.critical("Running Facebook page search for %d leads", len(needs_search))
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        future_map = {
            executor.submit(
                search_facebook_page,
                leads[index].get("business_name"),
                leads[index].get("address"),
                config.max_search_results,
            ): index
            for index in needs_search
        }
        for future in as_completed(future_map):
            index = future_map[future]
            business_name = leads[index].get("business_name")
            try:
                results = future.result()
            except Exception as e:
                logger.error("Facebook page search failed for %s: %s", business_name, e)
                continue

            url, score, matched_name = best_page_match(
                business_name,
                results,
                config.min_similarity,
            )
            if url:
                logger.info(
                    "Matched '%s' to '%s' %s (similarity %.2f)",
                    business_name,
                    matched_name,
                    url,
                    score,
                )
                resolved[index] = (url, "search")
            else:
                logger.info(
                    "No confident Facebook match for '%s' (best similarity %.2f)",
                    business_name,
                    score,
                )

    return resolved


def apply_enrichment(lead, url, page, source):
    """Write Facebook findings onto a lead in place and return the enrichment status."""
    if not url:
        status = STATUS_NO_PAGE
    elif page is None:
        status = STATUS_SCRAPE_FAILED
    else:
        email = extract_page_email(page)
        if email:
            lead["email"] = email
            lead["has_email"] = True
            status = STATUS_ENRICHED
        else:
            status = STATUS_NO_EMAIL

    if url:
        lead["facebook_url"] = url
    lead["enrichment"] = {
        "source": ENRICHMENT_SOURCE,
        "status": status,
        "url_source": source,
        "checked_at": _iso_now(),
    }
    return status


def load_leads(json_path):
    """Load a leadgen JSON array; returns [] when the file is missing or malformed."""
    if not os.path.exists(json_path):
        logger.error("Leads file not found: %s", json_path)
        return []

    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read leads from %s: %s", json_path, e)
        return []

    if not isinstance(data, list):
        logger.error("Expected a JSON array of leads in %s", json_path)
        return []
    return [row for row in data if isinstance(row, dict)]


def save_leads(leads, json_path):
    """Write leads back out atomically so a failed run cannot truncate the file."""
    path = Path(json_path)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)
    logger.critical("Saved %d leads to %s", len(leads), path)


def _apify_key_missing():
    if APIFY_API_KEY:
        return False
    logger.error("Please set APIFY_API_KEY in .env before running.")
    return True


def enrich_leads(leads, config=None):
    """Enrich a list of lead rows in place; returns the rows that gained an email.

    This is the entry point used by leadgen at the end of a run. run_enrichment
    wraps it with JSON file loading and saving for standalone use.
    """
    config = config or EnrichConfig()
    if _apify_key_missing():
        return []

    # Candidates are references into leads, so enrichment mutates both.
    candidates = [lead for lead in leads if needs_enrichment(lead, config.retry_all)]
    if config.limit > 0:
        candidates = candidates[:config.limit]
    if not candidates:
        logger.critical("No leads need Facebook enrichment")
        return []

    logger.critical(
        "Enriching %d of %d leads with no email",
        len(candidates),
        len(leads),
    )

    resolved = resolve_page_urls(candidates, config)
    from_website = sum(1 for _, source in resolved.values() if source == "website")
    logger.critical(
        "Resolved %d Facebook Pages (%d from lead website, %d from search)",
        len(resolved),
        from_website,
        len(resolved) - from_website,
    )

    if config.dry_run:
        for index, (url, source) in sorted(resolved.items()):
            logger.critical(
                "[dry run] %s -> %s (%s)",
                candidates[index].get("business_name"),
                url,
                source,
            )
        return []

    pages = scrape_facebook_pages(url for url, _ in resolved.values())

    enriched = []
    status_counts = {}
    for index, lead in enumerate(candidates):
        url, source = resolved.get(index, (None, None))
        status = apply_enrichment(lead, url, pages.get(url) if url else None, source)
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == STATUS_ENRICHED:
            enriched.append(lead)
            logger.info("Found %s for %s", lead["email"], lead.get("business_name"))

    for status, count in sorted(status_counts.items()):
        logger.critical("%s: %d", status, count)

    return enriched


def run_enrichment(config):
    """Enrich a leads JSON file in place with the given configuration."""
    if _apify_key_missing():
        return

    if config.dashboard and not os.getenv("LEAD_INGEST_KEY"):
        logger.error("LEAD_INGEST_KEY is required for dashboard ingest.")
        return

    leads = load_leads(config.json_path)
    if not leads:
        return

    enriched = enrich_leads(leads, config)
    if config.dry_run:
        return

    save_leads(leads, config.output_path or config.json_path)

    if config.dashboard and enriched:
        # Imported here so leadgen can import this module without a cycle.
        from leadgen import send_to_dashboard

        send_to_dashboard(enriched)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enrich leads that have no email using Facebook Pages",
    )
    parser.add_argument(
        "--json-path",
        default=DEFAULT_JSON_PATH,
        help=f"Leads JSON produced by leadgen (default {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--output-path",
        help="Write results here instead of overwriting the input file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum leads to enrich this run; 0 means no limit",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.72,
        help="Minimum business name similarity to accept a page match (default 0.72)",
    )
    parser.add_argument(
        "--max-search-results",
        type=int,
        default=5,
        help="Facebook search results to consider per lead (default 5)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Concurrent Facebook searches (default 4)",
    )
    parser.add_argument(
        "--retry-all",
        action="store_true",
        help="Re-attempt every email-less lead, including ones already checked",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and report page matches only; skip page scraping and writes",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Bulk-ingest newly enriched leads to the dashboard",
    )
    return parser.parse_args()


def config_from_args(args):
    return EnrichConfig(
        json_path=args.json_path,
        output_path=args.output_path,
        limit=args.limit,
        min_similarity=args.min_similarity,
        max_search_results=args.max_search_results,
        max_workers=args.max_workers,
        retry_all=args.retry_all,
        dry_run=args.dry_run,
        dashboard=args.dashboard,
    )


def main():
    run_enrichment(config_from_args(parse_args()))


if __name__ == "__main__":
    main()
