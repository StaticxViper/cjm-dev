"""Cross-source dedupe for new-business discovery.

Name-only matches never merge. Exact and strong matches collapse through
union-find, including transitive links.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from email_discovery import _registrable_domain, is_directory_host
from leadfilter import _phone_digits, identity_keys_from_row
from playwright_discovery import normalize_profile_url
from website_quality import is_social_or_directory_url

SHARED_THRESHOLD = 3
NAME_SIMILARITY = 0.85
LEGAL_SUFFIXES = (
    "limited liability company",
    "incorporated",
    "corporation",
    "company",
    "pllc",
    "llc",
    "l l c",
    "inc",
    "corp",
    "ltd",
    "limited",
    "llp",
    "lp",
    "pc",
    "pa",
    "co",
)
DBA_RE = re.compile(r"\b(?:d\s*/\s*b\s*/\s*a|d\.?\s*b\.?\s*a\.?|dba|t\s*/\s*a)\b", re.I)
UNIT_RE = re.compile(r"\b(?:suite|ste|unit|apt|apartment|#)\s*[a-z0-9-]*\b", re.I)
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
STREET_ABBREV = {
    "street": "st",
    "avenue": "ave",
    "road": "rd",
    "boulevard": "blvd",
    "drive": "dr",
    "lane": "ln",
    "court": "ct",
    "place": "pl",
    "terrace": "ter",
    "parkway": "pkwy",
    "highway": "hwy",
}
DATE_PRIORITY = (
    "registration_date",
    "formation_date",
    "filing_date",
    "opening_date",
)
REGISTRY_CATEGORIES = frozenset({
    "County government business-registration databases",
    "State business / entity search databases",
    "Secretary of State / entity databases",
    "County clerk / public-record business listings",
    "Public new-business / new-license lists",
    "Local government business-license databases",
    "Other publicly accessible business-registration or new-business sources",
})
PHONE_RANK = {"website": 4, "maps": 3, "registry": 2, "directory": 1, "": 0}
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}


def _clean_text(value):
    text = (value or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_suffixes(text):
    changed = True
    while changed and text:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            if text == suffix:
                return ""
            tail = " " + suffix
            if text.endswith(tail):
                text = text[: -len(tail)].strip()
                changed = True
                break
    return text


def normalize_business_name(name):
    """Lowercase, expand &, drop punctuation and a trailing legal suffix."""
    text = _clean_text(name)
    if text.startswith("the "):
        text = text[4:].strip()
    return _strip_suffixes(text)


def split_dba_names(name):
    """Return normalized names for the legal name and each d/b/a / dba / t/a."""
    raw = str(name or "").strip()
    if not raw:
        return []
    parts = [part.strip(" ,") for part in DBA_RE.split(raw) if part and part.strip(" ,")]
    names = []
    seen = set()
    for part in parts:
        normalized = normalize_business_name(part)
        if normalized and normalized not in seen:
            seen.add(normalized)
            names.append(normalized)
    if not names:
        normalized = normalize_business_name(raw)
        if normalized:
            names.append(normalized)
    return names


def name_similarity(left, right):
    """Max of SequenceMatcher ratio and a token-set ratio. No extra dependencies."""
    a = normalize_business_name(left) if left else ""
    b = normalize_business_name(right) if right else ""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequence = SequenceMatcher(None, a, b).ratio()
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        token_score = 0.0
    else:
        shared = len(a_tokens & b_tokens)
        token_score = (2.0 * shared) / (len(a_tokens) + len(b_tokens))
    return max(sequence, token_score)


def normalize_street(address):
    text = UNIT_RE.sub(" ", str(address or ""))
    text = _clean_text(text)
    text = ZIP_RE.sub(" ", text)
    tokens = []
    for token in text.split():
        tokens.append(STREET_ABBREV.get(token, token))
    return " ".join(tokens).strip()


def zip5(value):
    match = ZIP_RE.search(str(value or ""))
    return match.group(1) if match else ""


def _domain_of(row):
    website = (row.get("website") or "").strip()
    if not website:
        return ""
    if is_social_or_directory_url(website) or is_directory_host(website):
        return ""
    host = website
    if "://" not in host:
        host = "http://" + host
    try:
        from urllib.parse import urlparse
        hostname = (urlparse(host).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""
    return _registrable_domain(hostname)


def _source_category(row):
    return (row.get("source_category") or row.get("category_source") or "").strip()


def _is_registry(row):
    if row.get("entity_id"):
        return True
    return _source_category(row) in REGISTRY_CATEGORIES


def identity_key_tuples(row):
    """Normalized keys used for exact/strong matching and the seen-cache."""
    keys = []
    state = str(row.get("state") or "").strip().upper()
    entity_id = str(row.get("entity_id") or "").strip()
    if state and entity_id:
        keys.append(("entity", state, entity_id.lower()))
    place_id = str(row.get("place_id") or "").strip()
    if place_id:
        keys.append(("place_id", place_id.lower()))
    profile = normalize_profile_url(row.get("maps_url") or row.get("profile_url") or "")
    if profile:
        keys.append(("profile_url", profile.lower()))
    domain = _domain_of(row)
    if domain:
        keys.append(("domain", domain))
    for name in _all_names(row):
        keys.append(("name", name))
    phone = _phone_digits(row.get("phone") or row.get("phone_google"))
    if phone:
        keys.append(("phone", phone))
    street = normalize_street(row.get("address"))
    postal = zip5(row.get("zip") or row.get("address"))
    if street:
        keys.append(("street", street, postal))
    if postal:
        keys.append(("zip", postal))
    city = str(row.get("city") or "").strip().lower()
    if city:
        keys.append(("city", city))
    return keys


def _all_names(row):
    names = []
    seen = set()
    for raw in [row.get("business_name")] + list(row.get("alternate_names") or []):
        for name in split_dba_names(raw or ""):
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _preferred_lead_id(row):
    state = str(row.get("state") or "").strip().upper()
    entity_id = str(row.get("entity_id") or "").strip()
    if state and entity_id:
        return f"reg:{state}:{entity_id}"
    place_id = str(row.get("place_id") or "").strip()
    if place_id:
        return f"place:{place_id}"
    domain = _domain_of(row)
    if domain:
        return f"dom:{domain}"
    name = (_all_names(row) or [""])[0]
    postal = zip5(row.get("zip") or row.get("address"))
    phone = _phone_digits(row.get("phone") or row.get("phone_google"))
    digest = hashlib.sha1(f"{name}|{postal}|{phone}".encode("utf-8")).hexdigest()[:16]
    return f"h:{digest}"


def _key_token(key):
    return json.dumps(list(key), separators=(",", ":"))


class SeenCache:
    """Maps every identity key to the first lead_id assigned to that business."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.data = {"businesses": {}, "key_index": {}}
        self.load()

    def load(self):
        if self.path is None or not self.path.exists():
            return self.data
        try:
            with open(self.path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return self.data
        if isinstance(loaded, dict):
            self.data["businesses"] = dict(loaded.get("businesses") or {})
            self.data["key_index"] = dict(loaded.get("key_index") or {})
        return self.data

    def save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2)
            handle.write("\n")

    def lead_id_for_keys(self, keys):
        index = self.data.get("key_index") or {}
        for key in keys:
            found = index.get(_key_token(key))
            if found:
                return found
        return None

    def assign(self, row, keys):
        existing = self.lead_id_for_keys(keys)
        lead_id = existing or _preferred_lead_id(row)
        self.remember(lead_id, keys, row)
        return lead_id

    def remember(self, lead_id, keys, row):
        today = datetime.now(timezone.utc).date().isoformat()
        businesses = self.data.setdefault("businesses", {})
        entry = businesses.get(lead_id) or {
            "lead_id": lead_id,
            "keys": [],
            "first_seen": today,
            "last_seen": today,
            "last_output_at": None,
            "newness_date": row.get("newness_date"),
        }
        entry["last_seen"] = today
        if row.get("newness_date"):
            entry["newness_date"] = row.get("newness_date")
        known = set(entry.get("keys") or [])
        index = self.data.setdefault("key_index", {})
        for key in keys:
            token = _key_token(key)
            known.add(token)
            index[token] = lead_id
        entry["keys"] = sorted(known)
        businesses[lead_id] = entry
        return entry

    def already_output(self, lead_id):
        entry = (self.data.get("businesses") or {}).get(lead_id) or {}
        return bool(entry.get("last_output_at"))

    def mark_output(self, lead_id, newness_date=None):
        today = datetime.now(timezone.utc).date().isoformat()
        entry = (self.data.setdefault("businesses", {})).get(lead_id)
        if entry is None:
            entry = {
                "lead_id": lead_id,
                "keys": [],
                "first_seen": today,
                "last_output_at": today,
            }
            self.data["businesses"][lead_id] = entry
        entry["last_seen"] = today
        entry["last_output_at"] = today
        if newness_date:
            entry["newness_date"] = newness_date
        return entry

    def seen_dates(self, lead_id):
        entry = (self.data.get("businesses") or {}).get(lead_id) or {}
        return entry.get("first_seen"), entry.get("last_seen")


class _UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))
        self.strength = ["none"] * size

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left, right, strength):
        a = self.find(left)
        b = self.find(right)
        if a == b:
            if strength == "exact":
                self.strength[a] = "exact"
            return
        self.parent[b] = a
        if strength == "exact" or self.strength[b] == "exact" or self.strength[a] == "exact":
            self.strength[a] = "exact"
        else:
            self.strength[a] = "strong"


def _names_similar(left_names, right_names):
    best = 0.0
    for left in left_names:
        for right in right_names:
            best = max(best, name_similarity(left, right))
    return best


def _same_name(left_names, right_names):
    return bool(set(left_names) & set(right_names))


def _source_entry(row):
    fields = row.get("fields_provided") or []
    return {
        "source_name": row.get("source_name") or "",
        "source_url": row.get("source_url") or "",
        "source_record_url": row.get("source_record_url") or "",
        "retrieved_at": row.get("retrieved_at") or "",
        "fields_provided": list(fields),
    }


def _blank(value):
    return value is None or value == "" or value == []


def _merge_scalar(current, incoming, *, prefer_incoming=False):
    if _blank(current) and not _blank(incoming):
        return incoming
    if prefer_incoming and not _blank(incoming):
        return incoming
    return current


def _merge_rows(rows, strength):
    merged = {
        "alternate_names": [],
        "newness_evidence": [],
        "sources": [],
        "public_contacts": [],
        "website_issues": [],
        "merged_from": len(rows),
        "dedupe_match": strength if len(rows) > 1 else None,
    }
    names = []
    best_email_rank = -1
    best_phone_rank = -1
    description = ""
    for row in rows:
        for name in [row.get("business_name")] + list(row.get("alternate_names") or []):
            if name and name not in names:
                names.append(name)
        evidence = list(row.get("newness_evidence") or [])
        for item in evidence:
            if item not in merged["newness_evidence"]:
                merged["newness_evidence"].append(item)
        source = _source_entry(row)
        if source not in merged["sources"] and source.get("source_name"):
            merged["sources"].append(source)
        for contact in row.get("public_contacts") or []:
            if contact not in merged["public_contacts"]:
                merged["public_contacts"].append(contact)
        for issue in row.get("website_issues") or []:
            if issue not in merged["website_issues"]:
                merged["website_issues"].append(issue)
        incoming_registry = _is_registry(row)
        current_registry = bool(merged.get("_registry"))
        for field in (
            "business_name",
            "category",
            "registration_date",
            "formation_date",
            "filing_date",
            "opening_date",
            "business_status",
            "state",
            "county",
            "city",
            "zip",
            "address",
            "website",
            "maps_url",
            "place_id",
            "entity_id",
            "contact_form_url",
            "website_status",
            "profile_url",
            "user_ratings_total",
            "rating",
            "email_source",
            "email_source_url",
            "email_confidence",
            "email_evidence",
            "source_category",
        ):
            prefer = False
            if field in ("registration_date", "formation_date", "filing_date", "opening_date", "business_status"):
                prefer = incoming_registry and not current_registry
            merged[field] = _merge_scalar(merged.get(field), row.get(field), prefer_incoming=prefer)
        if incoming_registry:
            merged["_registry"] = True
        text = str(row.get("description") or "")
        if len(text) > len(description):
            description = text
        phone = row.get("phone") or row.get("phone_google")
        origin = (row.get("phone_origin") or "").strip().lower()
        rank = PHONE_RANK.get(origin, 1 if phone else 0)
        if phone and ( _blank(merged.get("phone")) or rank > best_phone_rank):
            merged["phone"] = phone
            merged["phone_google"] = phone
            merged["phone_origin"] = origin or merged.get("phone_origin") or ""
            best_phone_rank = rank
        confidence = str(row.get("email_confidence") or "").lower()
        email_rank = CONFIDENCE_RANK.get(confidence, 0)
        if row.get("email") and email_rank >= CONFIDENCE_RANK["medium"] and email_rank >= best_email_rank:
            merged["email"] = row.get("email")
            merged["email_confidence"] = confidence
            merged["email_source"] = row.get("email_source")
            merged["email_source_url"] = row.get("email_source_url")
            merged["email_evidence"] = row.get("email_evidence")
            best_email_rank = email_rank
        elif row.get("email") and _blank(merged.get("email")) and best_email_rank < 0:
            merged["email"] = row.get("email")
            merged["email_source"] = row.get("email_source") or ""
            merged["email_source_url"] = row.get("email_source_url") or ""
            merged["email_evidence"] = row.get("email_evidence") or ""
        try:
            quality = row.get("website_quality_score")
            if quality is not None and (
                merged.get("website_quality_score") is None
                or int(quality) > int(merged.get("website_quality_score") or 0)
            ):
                if row.get("website_status"):
                    merged["website_quality_score"] = quality
                    merged["website_status"] = row.get("website_status") or merged.get("website_status")
        except (TypeError, ValueError):
            pass
    merged["description"] = description
    if names:
        merged["business_name"] = names[0]
        merged["alternate_names"] = names[1:]
    merged.pop("_registry", None)
    if merged.get("place_id") and not merged.get("maps_url"):
        merged["maps_url"] = f"https://www.google.com/maps/place/?q=place_id:{merged['place_id']}"
    if merged.get("maps_url") and not merged.get("profile_url"):
        merged["profile_url"] = merged["maps_url"]
    merged["newness_date"] = _earliest_newness(merged)
    return merged


def _earliest_newness(row):
    reliable = []
    opening = []
    for item in row.get("newness_evidence") or []:
        if not isinstance(item, dict):
            continue
        parsed = str(item.get("date") or "")[:10]
        if not re.match(r"\d{4}-\d{2}-\d{2}", parsed):
            continue
        evidence_type = item.get("type") or ""
        if evidence_type in ("registration_date", "formation_date", "filing_date"):
            reliable.append(parsed)
        elif evidence_type in ("opening_date", "license_date"):
            opening.append(parsed)
    for field in ("registration_date", "formation_date", "filing_date"):
        parsed = str(row.get(field) or "")[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}", parsed):
            reliable.append(parsed)
    for field in ("opening_date",):
        parsed = str(row.get(field) or "")[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}", parsed):
            opening.append(parsed)
    if reliable:
        return min(reliable)
    if opening:
        return min(opening)
    return None


def _pair_relation(left, right, left_names, right_names, shared_phones, shared_streets):
    """Return exact, strong, weak, or none."""
    left_entity = ("entity", str(left.get("state") or "").upper(), str(left.get("entity_id") or "").lower())
    right_entity = ("entity", str(right.get("state") or "").upper(), str(right.get("entity_id") or "").lower())
    if left.get("entity_id") and right.get("entity_id") and left_entity == right_entity:
        return "exact"
    if left.get("place_id") and right.get("place_id") and str(left["place_id"]).lower() == str(right["place_id"]).lower():
        return "exact"
    left_profile = normalize_profile_url(left.get("maps_url") or left.get("profile_url") or "")
    right_profile = normalize_profile_url(right.get("maps_url") or right.get("profile_url") or "")
    if left_profile and left_profile == right_profile:
        return "exact"
    left_domain = _domain_of(left)
    right_domain = _domain_of(right)
    if left_domain and left_domain == right_domain:
        return "exact"

    left_phone = _phone_digits(left.get("phone") or left.get("phone_google"))
    right_phone = _phone_digits(right.get("phone") or right.get("phone_google"))
    phone_ok = bool(left_phone and left_phone == right_phone and left_phone not in shared_phones)
    similar = _names_similar(left_names, right_names)
    same = _same_name(left_names, right_names)
    left_zip = zip5(left.get("zip") or left.get("address"))
    right_zip = zip5(right.get("zip") or right.get("address"))
    same_zip = bool(left_zip and left_zip == right_zip)
    left_street = normalize_street(left.get("address"))
    right_street = normalize_street(right.get("address"))
    street_key_left = (left_street, left_zip)
    street_shared = street_key_left in shared_streets or (right_street, right_zip) in shared_streets
    same_street = bool(left_street and left_street == right_street and not street_shared)
    if phone_ok and similar >= NAME_SIMILARITY:
        return "strong"
    if same and (same_zip or same_street):
        return "strong"

    left_city = str(left.get("city") or "").strip().lower()
    right_city = str(right.get("city") or "").strip().lower()
    same_city = bool(left_city and left_city == right_city)
    if same and same_city and not same_zip and not same_street and not phone_ok:
        return "weak"
    if similar >= NAME_SIMILARITY and same_zip and not same and not phone_ok and not same_street:
        return "weak"
    return "none"


def dedupe_new_businesses(records, seen_cache=None):
    """Merge records that are the same business. Returns (rows, stats)."""
    rows_in = [dict(row) for row in records or []]
    if not rows_in:
        return [], {"merged_duplicates": 0, "possible_duplicates": 0}

    phones = []
    streets = []
    for row in rows_in:
        phone = _phone_digits(row.get("phone") or row.get("phone_google"))
        phones.append(phone)
        street = normalize_street(row.get("address"))
        postal = zip5(row.get("zip") or row.get("address"))
        streets.append((street, postal) if street else ("", ""))
    phone_counts = {}
    street_counts = {}
    for phone in phones:
        if phone:
            phone_counts[phone] = phone_counts.get(phone, 0) + 1
    for street in streets:
        if street[0]:
            street_counts[street] = street_counts.get(street, 0) + 1
    shared_phones = {phone for phone, count in phone_counts.items() if count >= SHARED_THRESHOLD}
    shared_streets = {street for street, count in street_counts.items() if count >= SHARED_THRESHOLD}

    names = [_all_names(row) for row in rows_in]
    finder = _UnionFind(len(rows_in))
    weak_pairs = []
    for left_index in range(len(rows_in)):
        for right_index in range(left_index + 1, len(rows_in)):
            relation = _pair_relation(
                rows_in[left_index],
                rows_in[right_index],
                names[left_index],
                names[right_index],
                shared_phones,
                shared_streets,
            )
            if relation in ("exact", "strong"):
                finder.union(left_index, right_index, relation)
            elif relation == "weak":
                weak_pairs.append((left_index, right_index))

    clusters = {}
    for index in range(len(rows_in)):
        root = finder.find(index)
        clusters.setdefault(root, []).append(index)

    merged_rows = []
    root_to_pos = {}
    for root, indexes in clusters.items():
        strength = finder.strength[root] if len(indexes) > 1 else None
        if strength == "none":
            strength = None
        combined = _merge_rows([rows_in[index] for index in indexes], strength if len(indexes) > 1 else None)
        keys = identity_key_tuples(combined)
        for index in indexes:
            for key in identity_key_tuples(rows_in[index]):
                if key not in keys:
                    keys.append(key)
        if seen_cache is not None:
            combined["lead_id"] = seen_cache.assign(combined, keys)
            first_seen, last_seen = seen_cache.seen_dates(combined["lead_id"])
            combined["first_seen"] = first_seen
            combined["last_seen"] = last_seen
        else:
            combined["lead_id"] = _preferred_lead_id(combined)
        combined["_cluster_indexes"] = indexes
        root_to_pos[root] = len(merged_rows)
        merged_rows.append(combined)

    possible = 0
    for left_index, right_index in weak_pairs:
        left_root = finder.find(left_index)
        right_root = finder.find(right_index)
        if left_root == right_root:
            continue
        later_root, earlier_root = (left_root, right_root) if left_index > right_index else (right_root, left_root)
        if max(left_index, right_index) == right_index:
            later_root = right_root
            earlier_root = left_root
        else:
            later_root = left_root
            earlier_root = right_root
        later = merged_rows[root_to_pos[later_root]]
        earlier = merged_rows[root_to_pos[earlier_root]]
        if not later.get("possible_duplicate_of"):
            later["possible_duplicate_of"] = earlier.get("lead_id")
            possible += 1

    for row in merged_rows:
        row.pop("_cluster_indexes", None)
        row.setdefault("possible_duplicate_of", None)
        row["phone_google"] = row.get("phone_google") or row.get("phone")
        # Keep leadfilter identity keys available for cross-mode dedupe.
        row["_identity_keys"] = [
            list(key) for key in identity_keys_from_row({
                "place_id": row.get("place_id"),
                "profile_url": row.get("profile_url") or row.get("maps_url"),
                "business_name": row.get("business_name"),
                "phone_google": row.get("phone"),
                "address": row.get("address"),
            })
        ]

    merged_away = max(0, len(rows_in) - len(merged_rows))
    return merged_rows, {
        "merged_duplicates": merged_away,
        "possible_duplicates": possible,
    }
