"""Opp finder menu. Returns CLI args. Imports preset and skill helpers, not the logger."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.script_manager import repo_root
from scripts.script_manager.menus.prompts import ask, say, yes


def _import_package():
    scripts_dir = str(repo_root() / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from opp_finder_v2.config import ConfigError
    from opp_finder_v2.menu import load_skills, profile_lines, save_skills
    from opp_finder_v2.presets import (
        delete_preset,
        find_preset,
        load_presets,
        save_presets,
        setup_from_preset,
        upsert_preset,
    )
    from opp_finder_v2.search_setup import SearchSetup, selected_keywords

    return {
        "ConfigError": ConfigError,
        "load_skills": load_skills,
        "save_skills": save_skills,
        "profile_lines": profile_lines,
        "delete_preset": delete_preset,
        "find_preset": find_preset,
        "load_presets": load_presets,
        "save_presets": save_presets,
        "setup_from_preset": setup_from_preset,
        "upsert_preset": upsert_preset,
        "SearchSetup": SearchSetup,
        "selected_keywords": selected_keywords,
    }


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


def configure(script=None, *, reader=input, writer=print, repo: Path | None = None, skills_path=None, presets_path=None) -> list[str] | None:
    del script, repo
    deps = _import_package()
    setup = run_menu(
        reader=reader,
        writer=writer,
        skills_path=skills_path,
        presets_path=presets_path,
        deps=deps,
    )
    if setup is None:
        return None
    skills = deps["load_skills"](skills_path)
    return argv_from_setup(setup, skills, deps["selected_keywords"])


def argv_from_setup(setup, skills, selected_keywords) -> list[str]:
    """Translate a search setup into flags the opp-finder CLI already accepts."""
    if getattr(setup, "_from_preset", False) or getattr(setup, "_save_requested", False):
        args = ["--preset", setup.name]
    else:
        args = ["--employment", setup.employment]
        args.append("--remote-only" if setup.remote_only else "--no-remote")
        if setup.keyword_mode == "any":
            args.append("--any-keyword")
        else:
            words = selected_keywords(setup, skills)
            if words:
                args.extend(["--keywords", ",".join(words)])
    if not setup.upload_crm:
        args.append("--no-crm")
    return args


def configure_search(reader, writer, skills, *, name: str = "Custom", deps=None):
    deps = deps or _import_package()
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
        skill_ids = [group["id"] for group in skills.get("groups") or [] if group.get("enabled")]
    save_name = ask(reader, "Save this as a preset? Type a name, or Enter to skip: ")
    upload = yes(ask(reader, "Upload matches to the CRM (Side Job Leads)? [Y/n]: "), True)
    relaxed = employment == "part_time" or keyword_mode == "any"
    setup = deps["SearchSetup"](
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


def _toggle_skills(reader, writer, skills, skills_path, deps=None) -> None:
    deps = deps or _import_package()
    groups = skills.get("groups") or []
    say(writer, "Toggle a skill group. Enabled groups are included when a search uses skills.")
    for index, group in enumerate(groups, start=1):
        state = "on" if group.get("enabled") else "off"
        words = ", ".join(group.get("keywords") or [])
        say(writer, f"{index}) [{state}] {group.get('name')} — {words}")
    raw = ask(reader, "Numbers to toggle (example: 1,6), or Enter to go back: ")
    if not raw:
        return
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        number = int(part)
        if 1 <= number <= len(groups):
            groups[number - 1]["enabled"] = not groups[number - 1].get("enabled")
    deps["save_skills"](skills, skills_path)
    say(writer, "Saved skill toggles.")


def run_menu(*, reader=input, writer=print, skills_path=None, presets_path=None, deps=None):
    """Return a SearchSetup to queue, or None when the user goes back."""
    deps = deps or _import_package()
    skills = deps["load_skills"](skills_path)
    while True:
        say(writer, "")
        say(writer, "Opp finder")
        for line in deps["profile_lines"](skills):
            say(writer, line)
        say(writer, "1) Search")
        say(writer, "2) Presets")
        say(writer, "3) Toggle skills")
        say(writer, "4) Back")
        choice = ask(reader, "Select [1]: ") or "1"
        if choice == "4":
            return None
        if choice == "3":
            _toggle_skills(reader, writer, skills, skills_path, deps)
            skills = deps["load_skills"](skills_path)
            continue
        if choice == "2":
            queued = _presets_menu(reader, writer, skills, presets_path, deps)
            if queued is not None:
                return queued
            continue
        if choice not in {"1", ""}:
            say(writer, "Pick 1, 2, 3, or 4.")
            continue
        setup = configure_search(reader, writer, skills, deps=deps)
        if setup.keyword_mode == "skills" and not setup.skill_ids:
            say(writer, "No skills are turned on. Toggle skills (menu 3) or type keywords.")
            continue
        if getattr(setup, "_save_requested", False):
            presets = deps["load_presets"](presets_path)
            deps["upsert_preset"](presets, setup)
            deps["save_presets"](presets, presets_path)
            say(writer, f"Saved preset {setup.name}.")
        return setup


def _presets_menu(reader, writer, skills, presets_path, deps):
    presets = deps["load_presets"](presets_path)
    _print_presets(writer, presets)
    say(writer, "n) New preset")
    say(writer, "d) Delete a preset")
    say(writer, "b) Back")
    picked = ask(reader, "Select: ").lower()
    if picked in {"", "b"}:
        return None
    if picked == "n":
        setup = configure_search(reader, writer, skills, deps=deps)
        if not getattr(setup, "_save_requested", False):
            setup.name = ask(reader, "Preset name: ")
        if not setup.name:
            say(writer, "Preset needs a name.")
            return None
        presets = deps["load_presets"](presets_path)
        deps["upsert_preset"](presets, setup)
        deps["save_presets"](presets, presets_path)
        say(writer, f"Saved preset {setup.name}.")
        if yes(ask(reader, "Add it to the queue? [Y/n]: "), True):
            setup._save_requested = True  # type: ignore[attr-defined]
            return setup
        return None
    if picked == "d":
        which = ask(reader, "Preset number or name to delete: ")
        try:
            if which.isdigit():
                index = int(which) - 1
                if not 0 <= index < len(presets):
                    raise deps["ConfigError"](["that number is not in the list"])
                removed = presets.pop(index)
            else:
                removed = deps["delete_preset"](presets, which)
        except deps["ConfigError"] as exc:
            say(writer, str(exc))
            return None
        deps["save_presets"](presets, presets_path)
        say(writer, f"Deleted {removed.get('name')}.")
        return None
    try:
        if picked.isdigit():
            index = int(picked) - 1
            if not 0 <= index < len(presets):
                raise deps["ConfigError"](["that number is not in the list"])
            preset = presets[index]
        else:
            preset = deps["find_preset"](presets, picked)
    except deps["ConfigError"] as exc:
        say(writer, str(exc))
        return None
    setup = deps["setup_from_preset"](preset)
    setup.upload_crm = yes(ask(reader, "Upload matches to the CRM (Side Job Leads)? [Y/n]: "), True)
    setup._from_preset = True  # type: ignore[attr-defined]
    return setup


def _print_presets(writer, presets) -> None:
    if not presets:
        say(writer, "No presets saved.")
        return
    for index, preset in enumerate(presets, start=1):
        remote = "remote" if preset.get("remote_only", True) else "remote or on-site"
        say(writer, f"{index}) {preset.get('name')} ({preset.get('employment')}, {remote})")


def _choose(reader, writer, title, options, default_index: int) -> str:
    say(writer, title)
    for index, (_value, label) in enumerate(options, start=1):
        say(writer, f"{index}) {label}")
    raw = ask(reader, f"Select [{default_index}]: ")
    if not raw:
        return options[default_index - 1][0]
    if raw.isdigit():
        number = int(raw)
        if 1 <= number <= len(options):
            return options[number - 1][0]
    say(writer, "That number is not in the list. Using the default.")
    return options[default_index - 1][0]


def _keyword_list(reader) -> list[str]:
    raw = ask(reader, "Keywords (comma-separated): ")
    return [part.strip() for part in raw.split(",") if part.strip()]
