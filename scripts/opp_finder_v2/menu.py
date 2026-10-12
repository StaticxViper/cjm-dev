"""Skill file helpers for opp finder. The interactive menu lives in the script manager."""

from __future__ import annotations

from pathlib import Path

from opp_finder_v2.config import PACKAGE_DIR

SKILLS_PATH = PACKAGE_DIR / "skills.json"


def load_skills(path: Path | None = None) -> dict:
    path = path or SKILLS_PATH
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def save_skills(skills: dict, path: Path | None = None) -> None:
    import json

    path = path or SKILLS_PATH
    path.write_text(json.dumps(skills, indent=2) + "\n", encoding="utf-8")


def profile_lines(skills: dict) -> list[str]:
    profile = skills.get("profile") or {}
    enabled = [group["name"] for group in skills.get("groups") or [] if group.get("enabled")]
    return [
        f"Profile: {profile.get('name', 'Unknown')} — {profile.get('headline', '')}",
        f"Location: {profile.get('location', '')}",
        f"LinkedIn: {profile.get('url', '')}",
        "Skills on: " + (", ".join(enabled) if enabled else "(none)"),
    ]
