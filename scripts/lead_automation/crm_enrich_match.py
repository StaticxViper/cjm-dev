#!/usr/bin/env python3
"""Name, location, and category scoring for CRM lead enrichment.

Pure functions: no network, no Playwright, no MCP. A candidate is written only
when it clears the hard rejects and the confidence floor. There is no
"first listing" fallback.
"""
from __future__ import annotations

from pathlib import Path
import json
import re

from email_discovery import (
    NAME_STOPWORDS,
    is_directory_host,
    parse_address_parts,
)
from leadenrich import name_similarity, normalize_business_name
from website_quality import is_social_or_directory_url

DATA_DIR = Path(__file__).resolve().parent / "data"

LEGAL_SUFFIXES = (
    "llc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "ltd",
    "limited",
    "pllc",
    "lp",
    "llp",
    "pc",
    "pa",
)

GENERIC_TOKENS = frozenset({
    "construction",
    "services",
    "service",
    "group",
    "holdings",
    "holding",
    "management",
    "solutions",
    "solution",
    "enterprises",
    "enterprise",
    "realty",
    "consulting",
    "associates",
    "associate",
    "partners",
    "partner",
    "agency",
    "global",
    "international",
    "usa",
    "new",
    "business",
    "businesses",
    "limited",
    "liability",
    "professional",
    "domestic",
})

# Industry families seeded from keywords.json niche keys, plus "construction"
# which registrations use but keywords.json does not list on its own.
BUILDING = frozenset({
    "construction",
    "remodeling",
    "general contractor",
    "roofing",
    "home renovation",
    "painting",
    "flooring",
    "carpentry",
    "handyman",
    "drywall",
    "concrete",
    "masonry",
    "fencing",
    "deck building",
    "garage door",
    "window installation",
    "siding",
    "plumbing",
    "hvac",
    "electrician",
    "landscaping",
    "lawn care",
    "tree service",
})

CAMP_PHRASES = ("campground", "state park", "rv park")

CATEGORY_ALIASES = (
    ("remodel", "remodeling"),
    ("construct", "construction"),
    ("contractor", "general contractor"),
    ("plumb", "plumbing"),
    ("electric", "electrician"),
    ("roof", "roofing"),
    ("landscap", "landscaping"),
    ("hvac", "hvac"),
)

US_STATES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI",
    "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN",
    "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA",
    "WI", "WV", "WY",
})

TAG_IGNORE = frozenset({
    "no-email",
    "new-business",
    "enriched",
    "enrich_no_match",
    "enrich_low_confidence",
    "enrich_suspect",
    "active",
    "inactive",
    "domestic",
    "llc",
    "dllc",
    "open-data",
})

_DOTTED_SUFFIXES = (
    (r"\bp\s*\.\s*l\s*\.\s*l\s*\.\s*c\s*\.?", " pllc "),
    (r"\bl\s*\.\s*l\s*\.\s*c\s*\.?", " llc "),
    (r"\bl\s*\.\s*l\s*\.\s*p\s*\.?", " llp "),
    (r"\bl\s*\.\s*p\s*\.?", " lp "),
    (r"\bp\s*\.\s*c\s*\.?", " pc "),
    (r"\bp\s*\.\s*a\s*\.?", " pa "),
    (r"\bi\s*\.\s*n\s*\.\s*c\s*\.?", " inc "),
)

_STREET_REPLACEMENTS = (
    (r"\bst\b", "street"),
    (r"\bave\b", "avenue"),
    (r"\bblvd\b", "boulevard"),
    (r"\brd\b", "road"),
    (r"\bdr\b", "drive"),
    (r"\bln\b", "lane"),
    (r"\bw\b", "west"),
    (r"\be\b", "east"),
    (r"\bn\b", "north"),
    (r"\bs\b", "south"),
)

_KEYWORDS = None


def load_zip_county(path=None):
    path = Path(path) if path else DATA_DIR / "zip_county.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_npa_state(path=None):
    path = Path(path) if path else DATA_DIR / "npa_state.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(code): tuple(states) for code, states in raw.items()}


def keyword_keys():
    global _KEYWORDS
    if _KEYWORDS is None:
        path = Path(__file__).resolve().parent / "keywords.json"
        _KEYWORDS = list(json.loads(path.read_text(encoding="utf-8")))
    return _KEYWORDS


def _collapse_dotted_suffixes(text):
    out = text or ""
    for pattern, repl in _DOTTED_SUFFIXES:
        out = re.sub(pattern, repl, out, flags=re.I)
    return out


def split_dba_names(name):
    """Split a legal name and a DBA trade name. Returns at least one piece."""
    parts = re.split(r"\s+d\.?\s*b\.?\s*a\.?\s+", name or "", flags=re.I)
    cleaned = [part.strip(" ,") for part in parts if part and part.strip(" ,")]
    return cleaned or [""]


def strip_trailing_suffixes(name):
    """Drop trailing legal suffixes only. Interior words stay."""
    text = _collapse_dotted_suffixes(name or "").strip()
    text = re.sub(r"[,]+", " ", text)
    tokens = text.split()
    while tokens:
        last = re.sub(r"[^A-Za-z]", "", tokens[-1]).lower()
        if last not in LEGAL_SUFFIXES:
            break
        tokens.pop()
    return " ".join(tokens).strip(" ,")


def display_name(name):
    """Query form: original casing, DBA trade name when present, suffix removed."""
    parts = split_dba_names(name)
    primary = parts[-1] if len(parts) > 1 else parts[0]
    return strip_trailing_suffixes(primary).strip()


def normalize_match_name(name):
    """Lowercase comparison form. ``&`` becomes ``and``, then stopwords drop."""
    parts = split_dba_names(name)
    primary = parts[-1] if len(parts) > 1 else parts[0]
    primary = strip_trailing_suffixes(primary)
    return normalize_business_name(primary)


def distinctive_tokens(normalized):
    """Tokens that must appear exactly (or as a compound/plural) in a candidate."""
    found = []
    for token in (normalized or "").split():
        if len(token) <= 1:
            continue
        if token in NAME_STOPWORDS or token in GENERIC_TOKENS or token in LEGAL_SUFFIXES:
            continue
        found.append(token)
    return found


def _token_matches(token, candidate_tokens):
    forms = {token}
    if len(token) > 3 and token.endswith("s"):
        forms.add(token[:-1])
    elif len(token) > 2:
        forms.add(token + "s")
    cand = list(candidate_tokens or [])
    if forms & set(cand):
        return True
    for index in range(len(cand) - 1):
        joined = cand[index] + cand[index + 1]
        if joined in forms:
            return True
        if len(joined) > 3 and joined.endswith("s") and joined[:-1] in forms:
            return True
    return False


def distinctive_token_missing(lead_normalized, candidate_normalized):
    tokens = distinctive_tokens(lead_normalized)
    if not tokens:
        return False
    cand = (candidate_normalized or "").split()
    return not any(_token_matches(token, cand) for token in tokens)


def _norm_county(value):
    text = re.sub(r"\s+", " ", (value or "").strip().lower())
    if text.endswith(" county"):
        text = text[: -len(" county")]
    return text


def _norm_city(value):
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def norm_street(value):
    text = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    for pattern, repl in _STREET_REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    return " ".join(text.split())


def address_is_empty(value):
    """Blank, or only a 2-letter state code such as ``NY``."""
    text = (value or "").strip()
    if not text:
        return True
    return bool(re.fullmatch(r"[A-Za-z]{2}", text))


def field_is_empty(field, value):
    if field == "address":
        return address_is_empty(value)
    if field == "contact_name":
        return True
    if field == "rating":
        return value is None or value == ""
    if value is None:
        return True
    return not str(value).strip()


def _kv_description(description):
    found = {}
    for part in re.split(r"[;\n]", description or ""):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        found[key.strip().lower()] = value.strip()
    return found


def _clean_place(value):
    text = (value or "").strip(" .;")
    if not text:
        return None, None
    zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\b", text)
    zip_code = zip_match.group(1) if zip_match else None
    city = re.sub(r"\b\d{5}(?:-\d{4})?\b", "", text).strip(" ,.")
    return city or None, zip_code


def _state_from_tags(tags):
    for tag in tags or []:
        code = str(tag).strip().upper()
        if code in US_STATES:
            return code
    return None


def _city_from_tags(tags):
    cities = []
    for tag in tags or []:
        text = str(tag).strip()
        if not text or text.lower() in TAG_IGNORE:
            continue
        if text.upper() in US_STATES:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", text.lower()) and "-" not in text:
            cities.append(text)
    if len(cities) == 1:
        return cities[0]
    return None


def parse_candidate_address(address):
    parts = parse_address_parts(address)
    street = parts.get("street")
    state = (parts.get("state") or "").upper() or None
    if street and re.fullmatch(r"[A-Za-z]{2}", street.strip()):
        state = state or street.strip().upper()
        street = None
    zip_code = parts.get("zip")
    city = parts.get("city")
    if city:
        city = re.sub(r"\s+\d{5}(?:-\d{4})?$", "", city).strip() or None
    return {"street": street, "city": city, "state": state, "zip": zip_code}


def parse_lead_location(lead, zip_county=None):
    """Pull state, county, city, zip, and street from a CRM lead.

    Reads both ``key=value`` registration text and the prose
    ``Formed ... (CO) / County: / City:`` form. Falls back to tags.
    """
    description = (lead or {}).get("business_description") or ""
    address = (lead or {}).get("address") or ""
    tags = (lead or {}).get("tags") or []
    kv = _kv_description(description)

    state = (kv.get("state") or "").strip().upper() or None
    if state and state not in US_STATES:
        state = None
    if not state:
        formed = re.search(r"Formed[^(]{0,40}\(([A-Za-z]{2})\)", description, flags=re.I)
        if formed and formed.group(1).upper() in US_STATES:
            state = formed.group(1).upper()

    county = (kv.get("county") or "").strip() or None
    if not county:
        prose_county = re.search(r"\bCounty:\s*([A-Za-z][A-Za-z .'-]*)", description)
        if prose_county:
            county = prose_county.group(1).strip(" .;") or None

    city = (kv.get("city") or "").strip() or None
    zip_code = None
    if city:
        city, zip_code = _clean_place(city)
    if not city:
        prose_city = re.search(r"\bCity:\s*([^.;\n]+)", description, flags=re.I)
        if prose_city:
            city, prose_zip = _clean_place(prose_city.group(1))
            zip_code = zip_code or prose_zip

    parsed = parse_candidate_address(address) if address and not address_is_empty(address) else {
        "street": None, "city": None, "state": None, "zip": None,
    }
    if address_is_empty(address) and re.fullmatch(r"[A-Za-z]{2}", (address or "").strip() or ""):
        state = state or address.strip().upper()
    state = state or parsed.get("state") or _state_from_tags(tags)
    city = city or parsed.get("city") or _city_from_tags(tags)
    zip_code = zip_code or parsed.get("zip")
    street = parsed.get("street")
    if county:
        county = re.sub(r"\s+county$", "", county.strip(), flags=re.I).strip()

    if not county and zip_code and zip_county:
        row = zip_county.get(str(zip_code))
        if row:
            county = row.get("county") or county
            state = state or row.get("state")

    return {
        "state": state,
        "county": county or None,
        "city": city or None,
        "zip": zip_code or None,
        "street": street or None,
    }


def build_search_queries(lead, location=None):
    """``<display name> <city or County> <state>`` plus an optional legal-name query.

    Does not use the ``near`` form. The second query is the full legal name
    and is only meant to run when the first returns nothing.
    """
    location = location or parse_lead_location(lead)
    raw_name = (lead or {}).get("business_name") or ""
    display = display_name(raw_name)
    if location.get("city"):
        place = location["city"]
    elif location.get("county"):
        place = f"{location['county']} County"
    else:
        place = ""
    state = location.get("state") or ""
    primary = " ".join(part for part in (display, place, state) if part).strip()
    legal = " ".join(raw_name.split())
    secondary = " ".join(part for part in (legal, place, state) if part).strip()
    queries = []
    for query in (primary, secondary):
        if query and query not in queries:
            queries.append(query)
    return queries


def _phone_digits(phone):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def _npa(phone):
    digits = _phone_digits(phone)
    return digits[:3] if digits else None


def _phones_equal(left, right):
    a, b = _phone_digits(left), _phone_digits(right)
    return bool(a) and a == b


def _websites_equal(left, right):
    def host(url):
        text = (url or "").strip().lower()
        text = re.sub(r"^https?://", "", text)
        text = text.split("/")[0].split("?")[0]
        if text.startswith("www."):
            text = text[4:]
        return text
    a, b = host(left), host(right)
    return bool(a) and a == b


def _domain_has_token(website, tokens):
    text = (website or "").strip().lower()
    text = re.sub(r"^https?://", "", text).split("/")[0]
    if text.startswith("www."):
        text = text[4:]
    label = re.sub(r"[^a-z0-9]", "", text.split(".")[0] if text else "")
    return any(token and token in label for token in tokens)


def _county_for_zip(zip_code, zip_county):
    if not zip_code or not zip_county:
        return None, None
    row = zip_county.get(str(zip_code))
    if not row:
        return None, None
    return row.get("state"), row.get("county")


def _keyword_hits(text, keywords):
    haystack = (text or "").lower()
    hits = set()
    for key in keywords:
        if key and key in haystack:
            hits.add(key)
    for needle, alias in CATEGORY_ALIASES:
        if needle in haystack:
            hits.add(alias)
    return hits


def category_points(normalized_name, listing_category, keywords=None):
    """+10 compatible, +5 partial, 0 unknown, -15 contradiction."""
    category = (listing_category or "").strip().lower()
    if not category:
        return 0
    keywords = keywords if keywords is not None else keyword_keys()
    name_hits = _keyword_hits(normalized_name, keywords)
    if "construction" in (normalized_name or "").split():
        name_hits.add("construction")
    if not name_hits:
        return 0
    cat_hits = _keyword_hits(category, keywords)
    camp = any(phrase in category for phrase in CAMP_PHRASES)
    name_building = bool(name_hits & BUILDING)
    cat_building = bool(cat_hits & BUILDING)
    if name_building and camp:
        return -15
    if name_hits & cat_hits:
        return 10
    if name_building and cat_building:
        return 5
    return 0


def _candidate_name(candidate):
    return (
        (candidate or {}).get("business_name")
        or (candidate or {}).get("name")
        or ""
    )


def _candidate_phone(candidate):
    return (candidate or {}).get("phone") or (candidate or {}).get("phone_google") or ""


def _candidate_website(candidate):
    return (candidate or {}).get("website") or ""


def score_candidate(lead, candidate, zip_county=None, npa_state=None, location=None):
    """Score one listing. Hard rejects do not change the numeric breakdown."""
    zip_county = zip_county if zip_county is not None else load_zip_county()
    npa_state = npa_state if npa_state is not None else load_npa_state()
    location = location or parse_lead_location(lead, zip_county)
    lead_norm = normalize_match_name((lead or {}).get("business_name"))
    cand_name = _candidate_name(candidate)
    cand_norm = normalize_match_name(cand_name)
    similarity = name_similarity(lead_norm, cand_norm) if lead_norm and cand_norm else 0.0
    name_pts = int(round(50 * similarity))

    hard = []
    if distinctive_token_missing(lead_norm, cand_norm):
        hard.append("distinctive_token_missing")

    cand_addr = parse_candidate_address((candidate or {}).get("address"))
    zip_state, zip_county_name = _county_for_zip(cand_addr.get("zip"), zip_county)
    cand_state = cand_addr.get("state") or zip_state
    loc_pts = 0
    if location.get("state") and cand_state:
        if cand_state != location["state"]:
            hard.append("state_mismatch")
        else:
            loc_pts += 10
    cand_county = zip_county_name
    county_match = False
    if location.get("county") and cand_county:
        if _norm_county(cand_county) == _norm_county(location["county"]):
            county_match = True
        else:
            hard.append("county_mismatch")
    city_match = bool(
        location.get("city")
        and cand_addr.get("city")
        and _norm_city(location["city"]) == _norm_city(cand_addr["city"])
    )
    if county_match or city_match:
        loc_pts += 25

    if location.get("street") and (cand_addr.get("street") or cand_addr.get("zip")):
        street_diff = bool(cand_addr.get("street")) and norm_street(cand_addr["street"]) != norm_street(
            location["street"]
        )
        zip_diff = bool(location.get("zip") and cand_addr.get("zip") and location["zip"] != cand_addr["zip"])
        if street_diff or zip_diff:
            hard.append("address_mismatch")

    phone = _candidate_phone(candidate)
    npa = _npa(phone)
    if npa and location.get("state") and npa in npa_state:
        if location["state"] not in npa_state[npa]:
            hard.append("area_code_state_mismatch")

    status = str((candidate or {}).get("business_status") or "").strip().lower().replace(" ", "_")
    blob = f"{cand_name} {(candidate or {}).get('category') or ''}".lower()
    if status in {"closed_permanently", "permanently_closed"} or "permanently closed" in blob:
        hard.append("permanently_closed")

    website = _candidate_website(candidate)
    if website and (is_directory_host(website) or is_social_or_directory_url(website)):
        hard.append("website_is_directory")

    cat_pts = category_points(lead_norm, (candidate or {}).get("category"))
    tokens = distinctive_tokens(lead_norm)
    corr = 0
    if "distinctive_token_missing" not in hard:
        if (
            _domain_has_token(website, tokens)
            or _phones_equal((lead or {}).get("phone"), phone)
            or _websites_equal((lead or {}).get("website"), website)
        ):
            corr = 5

    total = max(0, name_pts + loc_pts + cat_pts + corr)
    # Preserve caller order while dropping duplicates.
    seen = []
    for item in hard:
        if item not in seen:
            seen.append(item)
    return {
        "name": cand_name,
        "phone": phone or None,
        "website": website or None,
        "address": (candidate or {}).get("address"),
        "place_id": (candidate or {}).get("place_id"),
        "profile_url": (candidate or {}).get("profile_url"),
        "category": (candidate or {}).get("category"),
        "rating": (candidate or {}).get("rating"),
        "user_ratings_total": (candidate or {}).get("user_ratings_total"),
        "business_status": (candidate or {}).get("business_status"),
        "score": total,
        "breakdown": {
            "name": name_pts,
            "location": loc_pts,
            "category": cat_pts,
            "corroboration": corr,
        },
        "hard_rejects": seen,
        "similarity": similarity,
    }


def decide(score, hard_rejects, min_confidence=80, low_floor=60):
    if hard_rejects:
        return "no_match"
    if score >= min_confidence:
        return "write"
    if score >= low_floor:
        return "low_confidence"
    return "no_match"


def select_match(candidates, lead, zip_county=None, npa_state=None, min_confidence=80, low_floor=60, location=None):
    """Pick the best eligible candidate. Never falls back to the first result."""
    location = location or parse_lead_location(lead, zip_county if zip_county is not None else load_zip_county())
    scored = [
        score_candidate(lead, candidate, zip_county, npa_state, location=location)
        for candidate in (candidates or [])
    ]
    eligible = [item for item in scored if not item["hard_rejects"]]
    if not scored:
        return {
            "decision": "no_match",
            "best": None,
            "winner": None,
            "candidates": [],
            "location": location,
        }
    pool = eligible or scored
    best = max(pool, key=lambda item: (item["score"], item["breakdown"]["name"], -scored.index(item)))
    if not eligible:
        decision = "no_match"
        winner = None
    else:
        decision = decide(best["score"], best["hard_rejects"], min_confidence, low_floor)
        winner = best if decision == "write" else None
    note_best = best
    if not eligible:
        note_best = max(scored, key=lambda item: (item["score"], item["breakdown"]["name"]))
    return {
        "decision": decision,
        "best": note_best,
        "winner": winner,
        "candidates": scored,
        "location": location,
    }


def name_prefilter_pass(lead, candidate):
    lead_norm = normalize_match_name((lead or {}).get("business_name"))
    cand_norm = normalize_match_name(_candidate_name(candidate))
    return not distinctive_token_missing(lead_norm, cand_norm)
