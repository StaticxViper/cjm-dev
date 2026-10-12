"""Clip generator menu. Lists ride folders and returns --folder plus optional flags."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from scripts.script_manager.menus.prompts import ask, say, yes


def configure(script=None, *, reader=input, writer=print, repo: Path | None = None) -> list[str] | None:
    del script, repo
    base = Path(os.environ.get("MOTO_VIDS_BASE", r"E:\0. Moto Vids"))
    raw_dir = base / "raw"
    say(writer, "")
    say(writer, "Clip generator")
    say(writer, f"Media root: {base}")
    folders = []
    if raw_dir.is_dir():
        folders = sorted(
            [path.name for path in raw_dir.iterdir() if path.is_dir()],
            key=lambda name: (raw_dir / name).stat().st_mtime,
            reverse=True,
        )
    if folders:
        say(writer, "Ride folders (newest first):")
        for index, folder in enumerate(folders, start=1):
            modified = datetime.fromtimestamp((raw_dir / folder).stat().st_mtime)
            say(writer, f"{index}) {folder}  |  {modified}")
        say(writer, "0) Type a folder name")
        raw = ask(reader, "Select folder: ")
        if raw == "0":
            folder = ask(reader, "Folder name: ")
        elif raw.isdigit() and 1 <= int(raw) <= len(folders):
            folder = folders[int(raw) - 1]
        else:
            say(writer, "That number is not in the list.")
            return None
    else:
        say(writer, f"No folders found in {raw_dir}.")
        folder = ask(reader, "Folder name (blank cancels): ")
    if not folder:
        return None
    args = ["--folder", folder]
    if yes(ask(reader, "Vertical 9:16 export? [y/N]: "), False):
        args.append("--vertical")
    if yes(ask(reader, "Dry run? [y/N]: "), False):
        args.append("--dry-run")
    if yes(ask(reader, "First video only? [y/N]: "), False):
        args.append("--first-only")
    if yes(ask(reader, "Skip splits? [y/N]: "), False):
        args.append("--skip-splits")
    style = ask(reader, "Style pov/front/auto [auto]: ") or "auto"
    if style in {"pov", "front", "auto"} and style != "auto":
        args.extend(["--style", style])
    elif style not in {"pov", "front", "auto"}:
        say(writer, "Unknown style. Using auto.")
    if not yes(ask(reader, "Add to the queue? [Y/n]: "), True):
        return None
    return args
