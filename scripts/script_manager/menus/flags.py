"""Flag and confirm menus built from registry prompts."""

from __future__ import annotations

import shlex

from scripts.script_manager.menus.prompts import ask, say, yes
from scripts.script_manager.registry import Script


def configure(script: Script, *, reader, writer, repo=None, confirm_only: bool = False) -> list[str] | None:
    """Walk registry prompts and return args to queue, or None to cancel."""
    del repo
    say(writer, "")
    say(writer, script.description)
    if script.status != "active":
        say(writer, f"Status: {script.status}. {script.status_reason}")
    args: list[str] = []
    if not confirm_only:
        for prompt in script.prompts:
            collected = _one_prompt(prompt, reader, writer)
            if collected:
                args.extend(collected)
        extra = ask(reader, "Extra args (blank to skip): ")
        if extra:
            args.extend(shlex.split(extra))
    else:
        say(writer, "This script takes no arguments.")
    if not yes(ask(reader, "Add to the queue? [Y/n]: "), True):
        return None
    return args


def _one_prompt(prompt: dict, reader, writer) -> list[str]:
    kind = prompt.get("kind", "str")
    label = prompt["prompt"]
    flag = prompt["arg"]
    if kind == "bool":
        if yes(ask(reader, f"{label} [y/N]: "), False):
            return [flag]
        return []
    if kind == "choice":
        choices = ", ".join(prompt.get("choices") or [])
        raw = ask(reader, f"{label} ({choices}, blank skips): ")
        if not raw:
            return []
        if raw not in (prompt.get("choices") or []):
            say(writer, "That choice is not in the list. Skipping.")
            return []
        return [flag, raw]
    raw = ask(reader, f"{label} (blank skips): ")
    if not raw:
        return []
    if kind == "int":
        try:
            int(raw)
        except ValueError:
            say(writer, "Enter a whole number. Skipping.")
            return []
    elif kind == "float":
        try:
            float(raw)
        except ValueError:
            say(writer, "Enter a number. Skipping.")
            return []
    if prompt.get("split"):
        parts = [part for part in raw.replace(",", " ").split() if part]
        if not parts:
            return []
        return [flag, *parts]
    return [flag, raw]
