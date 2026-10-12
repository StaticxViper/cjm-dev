"""Montage builder menu. Asks for a theme and count, then returns CLI args."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.script_manager.menus.prompts import ask, say, yes


def configure(script=None, *, reader=input, writer=print, repo: Path | None = None) -> list[str] | None:
    del script, repo
    base = Path(os.environ.get("MOTO_VIDS_BASE", r"E:\0. Moto Vids"))
    pool = base / "montage_pool"
    say(writer, "")
    say(writer, "Montage builder")
    say(writer, f"Media root: {base}")
    themes = []
    if pool.is_dir():
        themes = sorted(path.name for path in pool.iterdir() if path.is_dir())
    if themes:
        say(writer, "Themes:")
        for index, theme in enumerate(themes, start=1):
            say(writer, f"{index}) {theme}")
        say(writer, "0) Type a theme name")
        raw = ask(reader, "Select theme: ")
        if raw == "0":
            theme = ask(reader, "Theme folder: ")
        elif raw.isdigit() and 1 <= int(raw) <= len(themes):
            theme = themes[int(raw) - 1]
        else:
            say(writer, "That number is not in the list.")
            return None
    else:
        theme = ask(reader, "Theme folder: ")
    if not theme:
        say(writer, "Theme name required.")
        return None
    count_raw = ask(reader, "How many montages? [3]: ") or "3"
    try:
        count = int(count_raw)
    except ValueError:
        say(writer, "Enter a whole number. Using 3.")
        count = 3
    args = ["--theme", theme, "--count", str(count)]
    if yes(ask(reader, "Vertical 9:16? [y/N]: "), False):
        args.append("--vertical")
    if yes(ask(reader, "Shuffle clip order? [y/N]: "), False):
        args.append("--shuffle")
    if yes(ask(reader, "Test (one montage)? [y/N]: "), False):
        args.append("--test")
    if not yes(ask(reader, "Add to the queue? [Y/n]: "), True):
        return None
    return args
