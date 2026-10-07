"""Interactive search menu: employment, skills, keywords, and presets."""

from __future__ import annotations

from pathlib import Path

from opp_finder_v2.config import PACKAGE_DIR, ConfigError
from opp_finder_v2.presets import (
    PRESETS_PATH,
    delete_preset,
    find_preset,
    load_presets,
    save_presets,
    setup_from_preset,
    upsert_preset,
)
from opp_finder_v2.search_setup import SearchSetup

SKILLS_PATH = PACKAGE_DIR / "skills.json"

EMPLOYMENT_MENU = (
    ("part_time", "Part time"),
    ("full_time", "Full time"),
    ("contract", "Contract / freelance"),
    ("any", "Any employment type"),
)

KEYWORD_MENU = (
    ("skills", "Selected skills"),
    ("custom", "Type my own keywords"),
    ("skills_plus", "Selected skills plus extra keywords"),
    ("any", "Any keyword (no keyword filter)"),
)


def load_skills(path: Path | None = None) -> dict:
    path = path or SKILLS_PATH
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def save_skills(skills: dict, path: Path | None = None) -> None:
    import json

    path = path or SKILLS_PATH
    path.write_text(json.dumps(skills, indent=2) + "\n", encoding="utf-8")


def _ask(reader, prompt: str) -> str:
    return reader(prompt).strip()


def _yes(raw: str, default: bool) -> bool:
    value = raw.strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def _choose(reader, writer, title: str, options: tuple, default_index: int) -> str:
    writer(title)
    for index, (_value, label) in enumerate(options, start=1):
        writer(f"{index}) {label}")
    raw = _ask(reader, f"Select [{default_index}]: ")
    if not raw:
        return options[default_index - 1][0]
    if raw.isdigit():
        number = int(raw)
        if 1 <= number <= len(options):
            return options[number - 1][0]
    writer("That number is not in the list. Using the default.")
    return options[default_index - 1][0]


def _keyword_list(reader) -> list[str]:
    raw = _ask(reader, "Keywords (comma-separated): ")
    return [part.strip() for part in raw.split(",") if part.strip()]


def profile_lines(skills: dict) -> list[str]:
    profile = skills.get("profile") or {}
    enabled = [group["name"] for group in skills.get("groups") or [] if group.get("enabled")]
    return [
        f"Profile: {profile.get('name', 'Unknown')} — {profile.get('headline', '')}",
        f"Location: {profile.get('location', '')}",
        f"LinkedIn: {profile.get('url', '')}",
        "Skills on: " + (", ".join(enabled) if enabled else "(none)"),
    ]


def configure_search(reader, writer, skills: dict, *, name: str = "Custom") -> SearchSetup:
    employment = _choose(reader, writer, "Employment", EMPLOYMENT_MENU, 4)
    remote_choice = _choose(
        reader,
        writer,
        "Location",
        (("remote", "Remote only"), ("any", "Remote or on-site")),
        1,
    )
    keyword_mode = _choose(reader, writer, "Keywords", KEYWORD_MENU, 1)
    keywords: list[str] = []
    if keyword_mode in {"custom", "skills_plus"}:
        keywords = _keyword_list(reader)
    skill_ids = None
    if keyword_mode in {"skills", "skills_plus"}:
        skill_ids = [
            group["id"] for group in skills.get("groups") or [] if group.get("enabled")
        ]
    save_name = _ask(reader, "Save this as a preset? Type a name, or Enter to skip: ")
    upload = _yes(_ask(reader, "Upload matches to the CRM (Side Job Leads)? [Y/n]: "), True)
    # Part-time roles and unfiltered searches rarely meet the full-time rate floor.
    relaxed = employment == "part_time" or keyword_mode == "any"
    setup = SearchSetup(
        name=save_name or name,
        employment=employment,
        remote_only=remote_choice == "remote",
        keyword_mode=keyword_mode,
        keywords=keywords,
        skill_ids=skill_ids,
        min_relevance=15 if relaxed else None,
        clear_rates=relaxed,
        upload_crm=upload,
    )
    setup._save_requested = bool(save_name)  # type: ignore[attr-defined]
    return setup


def _print_presets(writer, presets: list[dict]) -> None:
    if not presets:
        writer("No presets saved.")
        return
    for index, preset in enumerate(presets, start=1):
        remote = "remote" if preset.get("remote_only", True) else "remote or on-site"
        writer(f"{index}) {preset.get('name')} ({preset.get('employment')}, {remote})")


def _toggle_skills(reader, writer, skills: dict, skills_path: Path) -> None:
    groups = skills.get("groups") or []
    writer("Toggle a skill group. Enabled groups are included when a search uses skills.")
    for index, group in enumerate(groups, start=1):
        state = "on" if group.get("enabled") else "off"
        words = ", ".join(group.get("keywords") or [])
        writer(f"{index}) [{state}] {group.get('name')} — {words}")
    raw = _ask(reader, "Numbers to toggle (example: 1,6), or Enter to go back: ")
    if not raw:
        return
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        number = int(part)
        if 1 <= number <= len(groups):
            groups[number - 1]["enabled"] = not groups[number - 1].get("enabled")
    save_skills(skills, skills_path)
    writer("Saved skill toggles.")


def run_menu(
    *,
    reader=input,
    writer=print,
    skills_path: Path | None = None,
    presets_path: Path | None = None,
) -> SearchSetup | None:
    """Return a search to run, or None when the user exits."""
    skills_path = skills_path or SKILLS_PATH
    presets_path = presets_path or PRESETS_PATH
    skills = load_skills(skills_path)
    while True:
        writer("")
        writer("Opp finder")
        for line in profile_lines(skills):
            writer(line)
        writer("1) Search")
        writer("2) Presets")
        writer("3) Toggle skills")
        writer("4) Exit")
        choice = _ask(reader, "Select [1]: ") or "1"
        if choice == "4":
            return None
        if choice == "3":
            _toggle_skills(reader, writer, skills, skills_path)
            skills = load_skills(skills_path)
            continue
        if choice == "2":
            presets = load_presets(presets_path)
            _print_presets(writer, presets)
            writer("n) New preset")
            writer("d) Delete a preset")
            writer("b) Back")
            picked = _ask(reader, "Select: ").lower()
            if picked in {"", "b"}:
                continue
            if picked == "n":
                setup = configure_search(reader, writer, skills)
                if not getattr(setup, "_save_requested", False):
                    setup.name = _ask(reader, "Preset name: ")
                if not setup.name:
                    writer("Preset needs a name.")
                    continue
                presets = load_presets(presets_path)
                upsert_preset(presets, setup)
                save_presets(presets, presets_path)
                writer(f"Saved preset {setup.name}.")
                if _yes(_ask(reader, "Run it now? [Y/n]: "), True):
                    return setup
                continue
            if picked == "d":
                which = _ask(reader, "Preset number or name to delete: ")
                try:
                    if which.isdigit():
                        index = int(which) - 1
                        if not 0 <= index < len(presets):
                            raise ConfigError(["that number is not in the list"])
                        removed = presets.pop(index)
                    else:
                        removed = delete_preset(presets, which)
                except ConfigError as exc:
                    writer(str(exc))
                    continue
                save_presets(presets, presets_path)
                writer(f"Deleted {removed.get('name')}.")
                continue
            try:
                if picked.isdigit():
                    index = int(picked) - 1
                    if not 0 <= index < len(presets):
                        raise ConfigError(["that number is not in the list"])
                    preset = presets[index]
                else:
                    preset = find_preset(presets, picked)
            except ConfigError as exc:
                writer(str(exc))
                continue
            setup = setup_from_preset(preset)
            setup.upload_crm = _yes(
                _ask(reader, "Upload matches to the CRM (Side Job Leads)? [Y/n]: "),
                True,
            )
            return setup
        if choice not in {"1", ""}:
            writer("Pick 1, 2, 3, or 4.")
            continue
        setup = configure_search(reader, writer, skills)
        if setup.keyword_mode == "skills" and not setup.skill_ids:
            writer("No skills are turned on. Toggle skills (menu 3) or type keywords.")
            continue
        if getattr(setup, "_save_requested", False):
            presets = load_presets(presets_path)
            upsert_preset(presets, setup)
            save_presets(presets, presets_path)
            writer(f"Saved preset {setup.name}.")
        return setup
