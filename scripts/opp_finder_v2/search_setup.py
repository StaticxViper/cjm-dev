"""Turn a menu choice or a saved preset into criteria overrides."""

from __future__ import annotations

from dataclasses import dataclass, field

from opp_finder_v2.models import Criteria

EMPLOYMENT_TYPES = {
    "part_time": ["part_time"],
    "full_time": ["full_time"],
    "contract": ["contract", "freelance"],
    "any": ["full_time", "part_time", "contract", "freelance", "temporary", "internship"],
}

KEYWORD_MODES = ("skills", "custom", "skills_plus", "any")


@dataclass
class SearchSetup:
    name: str = "Custom"
    employment: str = "any"
    remote_only: bool = True
    keyword_mode: str = "skills"
    keywords: list[str] = field(default_factory=list)
    skill_ids: list[str] | None = None
    min_relevance: int | None = None
    clear_rates: bool = False
    upload_crm: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "employment": self.employment,
            "remote_only": self.remote_only,
            "keyword_mode": self.keyword_mode,
            "keywords": list(self.keywords),
            "skill_ids": list(self.skill_ids or []),
            "min_relevance": self.min_relevance,
            "clear_rates": self.clear_rates,
        }


def _unique(words: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for word in words:
        cleaned = word.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def skill_keywords(skills: dict, skill_ids: list[str] | None) -> list[str]:
    groups = skills.get("groups") or []
    if skill_ids is None:
        chosen = [group for group in groups if group.get("enabled")]
    else:
        wanted = set(skill_ids)
        chosen = [group for group in groups if group.get("id") in wanted]
    words: list[str] = []
    for group in chosen:
        words.extend(group.get("keywords") or [])
    return _unique(words)


def selected_keywords(setup: SearchSetup, skills: dict) -> list[str]:
    if setup.keyword_mode == "any":
        return []
    custom = _unique(setup.keywords)
    if setup.keyword_mode == "custom":
        return custom
    mined = skill_keywords(skills, setup.skill_ids)
    if setup.keyword_mode == "skills_plus":
        return _unique(mined + custom)
    return mined


def apply_setup(criteria: Criteria, setup: SearchSetup, skills: dict) -> None:
    """Mutate criteria so this run uses the menu or preset choices."""
    if setup.employment not in EMPLOYMENT_TYPES:
        raise ValueError(f"unknown employment choice: {setup.employment}")
    if setup.keyword_mode not in KEYWORD_MODES:
        raise ValueError(f"unknown keyword mode: {setup.keyword_mode}")
    keywords = selected_keywords(setup, skills)
    criteria.keywords_any = keywords
    criteria.keywords_all = []
    criteria.title_boost = list(keywords)
    criteria.employment_types = list(EMPLOYMENT_TYPES[setup.employment])
    criteria.remote_only = bool(setup.remote_only)
    if setup.min_relevance is not None:
        criteria.min_relevance = int(setup.min_relevance)
    if setup.clear_rates:
        criteria.min_rate_hourly = None
        criteria.min_rate_annual = None
        criteria.min_rate_unknown = "keep"
