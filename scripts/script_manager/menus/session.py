"""Home menu: pick a script, queue it, then run the queue in order."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

from scripts.script_manager.menus.prompts import ask, say, yes
from scripts.script_manager.registry import Registry, Script
from scripts.script_manager.runner import RunOptions, run_script

_CUSTOM = {
    "leadgen": "scripts.script_manager.menus.leadgen",
    "opp-finder": "scripts.script_manager.menus.opp_finder",
    "clip-generator": "scripts.script_manager.menus.clip_generator",
    "montage-builder": "scripts.script_manager.menus.montage_builder",
    "flags": "scripts.script_manager.menus.flags",
    "confirm": "scripts.script_manager.menus.flags",
}


@dataclass
class QueueItem:
    name: str
    args: list[str] = field(default_factory=list)
    force: bool = False
    yes: bool = False

    def label(self) -> str:
        tail = " ".join(self.args)
        return f"{self.name} {tail}".rstrip()


def menu_scripts(registry: Registry) -> list[Script]:
    return [script for script in registry.ordered() if script.menu]


def configure_script(script: Script, *, reader, writer, repo: Path) -> list[str] | None:
    kind = script.menu or ""
    module_name = _CUSTOM.get(kind)
    if module_name is None:
        say(writer, f"{script.name} has no menu.")
        return None
    module = importlib.import_module(module_name)
    if kind == "confirm":
        return module.configure(script, reader=reader, writer=writer, repo=repo, confirm_only=True)
    return module.configure(script, reader=reader, writer=writer, repo=repo)


def run_session(registry: Registry, *, reader=input, writer=print, repo: Path, runner=run_script) -> int:
    """Interactive home screen. Returns the last non-zero child code, or 0."""
    queue: list[QueueItem] = []
    last_code = 0
    while True:
        say(writer, "")
        say(writer, "Script manager")
        if queue:
            say(writer, "Queue:")
            for index, item in enumerate(queue, start=1):
                say(writer, f"  {index}) {item.label()}")
        else:
            say(writer, "Queue: (empty)")
        say(writer, "1) Add a script")
        say(writer, "2) Show queue")
        say(writer, "3) Remove a queued run")
        say(writer, "4) Run queue")
        say(writer, "5) Quit")
        choice = ask(reader, "Select [1]: ") or "1"
        if choice == "5":
            return last_code
        if choice == "2":
            _show_queue(queue, writer)
            continue
        if choice == "3":
            _remove_item(queue, reader, writer)
            continue
        if choice == "4":
            last_code = _run_queue(registry, queue, reader, writer, repo, runner)
            queue.clear()
            continue
        if choice != "1":
            say(writer, "Pick 1, 2, 3, 4, or 5.")
            continue
        item = _add_script(registry, reader, writer, repo)
        if item is not None:
            queue.append(item)
            say(writer, f"Queued {item.label()}")


def _add_script(registry: Registry, reader, writer, repo: Path) -> QueueItem | None:
    scripts = menu_scripts(registry)
    if not scripts:
        say(writer, "No scripts have a menu.")
        return None
    say(writer, "")
    say(writer, "Scripts")
    for index, script in enumerate(scripts, start=1):
        say(writer, f"{index}) {script.name} — {script.description}")
    raw = ask(reader, "Select: ")
    if not raw.isdigit() or not 1 <= int(raw) <= len(scripts):
        say(writer, "That number is not in the list.")
        return None
    script = scripts[int(raw) - 1]
    args = configure_script(script, reader=reader, writer=writer, repo=repo)
    if args is None:
        return None
    force = False
    confirmed = False
    if script.status != "active":
        if not yes(ask(reader, f"{script.name} is {script.status}. Queue it anyway? [y/N]: "), False):
            return None
        force = True
    if script.confirm_required:
        if not yes(ask(reader, f"{script.name} asks for confirmation before it runs. Allow it? [y/N]: "), False):
            return None
        confirmed = True
    return QueueItem(name=script.name, args=list(args), force=force, yes=confirmed)


def _show_queue(queue: list[QueueItem], writer) -> None:
    if not queue:
        say(writer, "Queue is empty.")
        return
    for index, item in enumerate(queue, start=1):
        say(writer, f"{index}) {item.label()}")


def _remove_item(queue: list[QueueItem], reader, writer) -> None:
    if not queue:
        say(writer, "Queue is empty.")
        return
    _show_queue(queue, writer)
    raw = ask(reader, "Number to remove (blank cancels): ")
    if not raw:
        return
    if not raw.isdigit() or not 1 <= int(raw) <= len(queue):
        say(writer, "That number is not in the list.")
        return
    removed = queue.pop(int(raw) - 1)
    say(writer, f"Removed {removed.label()}")


def _run_queue(registry, queue, reader, writer, repo, runner) -> int:
    if not queue:
        say(writer, "Queue is empty.")
        return 0
    last = 0
    for index, item in enumerate(queue, start=1):
        script = registry.get(item.name)
        say(writer, "")
        say(writer, f"Running {index}/{len(queue)}: {item.label()}")
        if script is None:
            say(writer, f"{item.name} is not in the registry.")
            last = 64
        else:
            summary = runner(
                repo,
                script,
                RunOptions(
                    passthrough=list(item.args),
                    non_interactive=True,
                    force=item.force,
                    yes=item.yes,
                ),
            )
            last = int(summary.get("exit_code", 1))
        if last != 0 and index < len(queue):
            if not yes(ask(reader, "Continue with the rest of the queue? [y/N]: "), False):
                return last
    return last
