"""Business-name comparison.

Two normalizers stay separate because they answer different questions.
``normalize_business_name`` is the Facebook and CRM matcher (stopword tokens).
``normalize_registry_name`` is the filing deduper (leading "the", legal suffixes,
including "l l c").
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

NAME_APOSTROPHE_RE = re.compile(r"['\u2018\u2019\u02bc]")
NAME_PUNCTUATION_RE = re.compile(r"[^a-z0-9]+")
NAME_STOPWORDS = frozenset({
    "the", "a", "an", "and", "of", "llc", "inc", "incorporated", "co", "corp",
    "corporation", "ltd", "limited", "company", "pllc", "lp", "llp",
})

REGISTRY_LEGAL_SUFFIXES = (
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


def normalize_business_name(name):
    """Lowercase and strip punctuation plus legal suffixes so names compare cleanly."""
    lowered = (name or "").lower().replace("&", " and ")
    tokens = NAME_PUNCTUATION_RE.sub(" ", NAME_APOSTROPHE_RE.sub("", lowered)).split()
    return " ".join(token for token in tokens if token not in NAME_STOPWORDS)


def name_similarity(left, right):
    """Return 0.0-1.0 similarity between two already-normalized business names."""
    if not left or not right:
        return 0.0

    ratio = SequenceMatcher(None, left, right).ratio()
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    smaller = min(len(left_tokens), len(right_tokens))
    if smaller < 2:
        return ratio

    containment = len(left_tokens & right_tokens) / smaller
    return max(ratio, containment * 0.95)


def clean_registry_text(value):
    text = (value or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_registry_suffixes(text):
    changed = True
    while changed and text:
        changed = False
        for suffix in REGISTRY_LEGAL_SUFFIXES:
            if text == suffix:
                return ""
            tail = " " + suffix
            if text.endswith(tail):
                text = text[: -len(tail)].strip()
                changed = True
                break
    return text


def normalize_registry_name(name):
    """Lowercase, expand &, drop punctuation and a trailing legal suffix."""
    text = clean_registry_text(name)
    if text.startswith("the "):
        text = text[4:].strip()
    return _strip_registry_suffixes(text)


def registry_name_similarity(left, right):
    """Max of SequenceMatcher ratio and a token-set ratio. Normalizes first."""
    left_name = normalize_registry_name(left) if left else ""
    right_name = normalize_registry_name(right) if right else ""
    if not left_name or not right_name:
        return 0.0
    if left_name == right_name:
        return 1.0
    sequence = SequenceMatcher(None, left_name, right_name).ratio()
    left_tokens = set(left_name.split())
    right_tokens = set(right_name.split())
    if not left_tokens or not right_tokens:
        token_score = 0.0
    else:
        shared = len(left_tokens & right_tokens)
        token_score = (2.0 * shared) / (len(left_tokens) + len(right_tokens))
    return max(sequence, token_score)
