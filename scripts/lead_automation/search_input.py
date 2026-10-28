"""Free-text niche and keyword parsing, plus dated lead output names.

keywords.json is an optional preset list. A search does not need it.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re

EMPTY_NICHE_MESSAGE = (
    "Enter at least one business niche. Example: mobile dog grooming"
)
EMPTY_SEARCH_MESSAGE = (
    "Enter at least one business niche or keyword search string. "
    "Example: mobile dog grooming"
)
PRESETS_TOKEN = "presets"
_MAX_JOINED_NICHES = 3
_MAX_SLUG_LENGTH = 80
_STATE_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI",
    "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN",
    "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA",
    "WI", "WV", "WY",
})
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_CITY_RE_CACHE = {}


class EmptySearchInput(ValueError):
    """Raised when a required niche or keyword value is blank."""


def _clean_term(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _dedupe(terms):
    seen = set()
    out = []
    for term in terms:
        cleaned = _clean_term(term)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def parse_term_list(raw) -> list[str]:
    """Split comma-separated text, trim, drop blanks, and dedupe.

    A comma piece that is only a US state code stays with the previous
    term, so ``Cherry Hill, NJ`` remains one search string.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        merged = []
        for item in raw:
            merged.extend(parse_term_list(item))
        return _dedupe(merged)
    text = str(raw).replace(";", ",")
    parts = [part.strip() for part in text.split(",")]
    terms = []
    for part in parts:
        cleaned = _clean_term(part)
        if not cleaned:
            continue
        if terms and cleaned.upper() in _STATE_CODES and " " not in cleaned:
            terms[-1] = f"{terms[-1]}, {cleaned.upper()}"
            continue
        terms.append(cleaned)
    return _dedupe(terms)


def require_niches(raw) -> list[str]:
    """Return niche strings or raise EmptySearchInput."""
    niches = parse_term_list(raw)
    if not niches:
        raise EmptySearchInput(EMPTY_NICHE_MESSAGE)
    return niches


def is_presets_choice(raw) -> bool:
    return _clean_term(raw).casefold() == PRESETS_TOKEN


def slugify_lead_type(text) -> str:
    """Lowercase hyphen slug with letters and digits only."""
    return _SLUG_RE.sub("-", str(text or "").lower()).strip("-")


def lead_type_slug(niches, max_join=_MAX_JOINED_NICHES) -> str:
    """Filename slug for one or more niches.

    A few niches are joined. More than that, or a very long join, becomes
    ``multi-niche``.
    """
    names = [_clean_term(name) for name in niches or []]
    names = [name for name in names if name]
    if not names:
        return "leads"
    if len(names) > max_join:
        return "multi-niche"
    parts = []
    for name in names:
        slug = slugify_lead_type(name)
        if slug and slug not in parts:
            parts.append(slug)
    if not parts:
        return "leads"
    joined = "-".join(parts)
    if len(joined) > _MAX_SLUG_LENGTH:
        return "multi-niche"
    return joined


def _coerce_day(today):
    if today is None:
        return date.today()
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    return date.fromisoformat(str(today))


def output_basename(niches, today=None) -> str:
    day = _coerce_day(today)
    return f"leads_{day.isoformat()}_{lead_type_slug(niches)}"


def output_directory(json_output) -> Path:
    """Folder of the current JSON output path. Relative paths stay relative."""
    path = Path(str(json_output or "leads_output.json"))
    parent = path.parent
    if str(parent) in ("", "."):
        return Path(".")
    return parent


def allocate_output_paths(directory, niches, today=None):
    """Return ``(csv_path, json_path)`` that do not already exist."""
    directory = Path(directory)
    stem = output_basename(niches, today=today)
    suffix_n = None
    while True:
        candidate = stem if suffix_n is None else f"{stem}_{suffix_n}"
        csv_path = directory / f"{candidate}.csv"
        json_path = directory / f"{candidate}.json"
        if not csv_path.exists() and not json_path.exists():
            return csv_path, json_path
        suffix_n = 2 if suffix_n is None else suffix_n + 1
        if suffix_n > 99:
            stamp = datetime.now().strftime("%H%M%S")
            stamped = f"{stem}_{stamp}"
            csv_path = directory / f"{stamped}.csv"
            json_path = directory / f"{stamped}.json"
            if not csv_path.exists() and not json_path.exists():
                return csv_path, json_path
            stamped = f"{stem}_{stamp}_{suffix_n}"
            return directory / f"{stamped}.csv", directory / f"{stamped}.json"


def _is_located_query(text) -> bool:
    return " near " in f" {str(text or '').lower()} "


def places_keyword(query) -> str:
    """Search term before a ``near`` location clause."""
    text = _clean_term(query)
    marker = " near "
    index = text.lower().find(marker)
    if index > 0:
        return text[:index].strip()
    return text


def _mentions_city(query, city) -> bool:
    name = _clean_term(city)
    if not name:
        return False
    key = name.casefold()
    pattern = _CITY_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(rf"(?i)(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])")
        _CITY_RE_CACHE[key] = pattern
    return pattern.search(str(query or "")) is not None


def _mentions_state(query, state) -> bool:
    code = _clean_term(state).upper()
    if len(code) != 2:
        return False
    return re.search(rf"(?i)(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])", str(query or "")) is not None


def _mentions_location(query, city, state) -> bool:
    if not _mentions_city(query, city):
        return False
    if not _clean_term(state):
        return True
    return _mentions_state(query, state)


def build_search_queries(niches, keywords, locations) -> list[str]:
    """Exact strings to search.

    Typed keywords are kept as typed when they already include ``near``.
    Bare keywords, and niches when keywords are blank, become
    ``{term} near {city}, {state}`` for each selected location.
    """
    niches = parse_term_list(niches)
    keywords = parse_term_list(keywords)
    terms = keywords if keywords else niches
    if not terms:
        return []
    located = []
    bare = []
    for term in terms:
        if _is_located_query(term):
            located.append(term)
        else:
            bare.append(term)
    queries = []
    if bare and locations:
        for term in bare:
            for loc in locations:
                state, city = loc[0], loc[1]
                queries.append(f"{term} near {city}, {state}")
    else:
        queries.extend(bare)
    queries.extend(located)
    return _dedupe(queries)


def queries_for_location(queries, city, state, locations) -> list[str]:
    """Queries that should run at one city. Located queries are not repeated."""
    queries = _dedupe(queries or [])
    locations = list(locations or [])
    first = locations[0] if locations else None
    matched_any = False
    out = []
    for query in queries:
        if not _is_located_query(query):
            out.append(f"{query} near {city}, {state}" if city and state else query)
            continue
        hits = [
            loc for loc in locations
            if _mentions_location(query, loc[1], loc[0])
        ]
        if hits:
            matched_any = True
            if _mentions_location(query, city, state):
                out.append(query)
            continue
        if first is not None and str(first[1]).casefold() == str(city).casefold() and str(first[0]).casefold() == str(state).casefold():
            out.append(query)
        elif not locations:
            out.append(query)
    if not matched_any and not out and queries and first is None:
        return list(queries)
    return _dedupe(out)


def lead_types_for_filename(niches, keywords) -> list[str]:
    """Niche names when present, otherwise the keyword text before ``near``."""
    niches = parse_term_list(niches)
    if niches:
        return niches
    return _dedupe(places_keyword(keyword) for keyword in parse_term_list(keywords))
