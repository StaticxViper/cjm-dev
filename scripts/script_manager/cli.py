"""Command line for list, info, help, run, and validate."""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import sys
from pathlib import Path

from scripts.script_manager import exit_codes, repo_root
from scripts.script_manager.discovery import unregistered_scripts
from scripts.script_manager.envcheck import (
    load_dotenv_file,
    merged_env,
    missing_names,
    playwright_needed,
)
from scripts.script_manager.envcheck import EnvFileError
from scripts.script_manager.menus.session import run_session
from scripts.script_manager.registry import (
    MENU_REQUIRED,
    Registry,
    RegistryError,
    Script,
    bundled_registry_path,
    entry_file,
    load_registry,
    registered_files,
)
from scripts.script_manager.runner import (
    RunOptions,
    build_argv,
    command_args,
    decide_noninteractive,
    describe_env,
    run_script,
    smoke_import,
    system_dep_status,
)

logger = logging.getLogger("script_manager")

_COMMANDS = {"list", "info", "help", "run", "validate", "menu"}
_GLOBAL_FLAGS = {"--json"}
_GLOBAL_VALUES = {"--registry", "--log-file"}

CONDITIONAL_NOTE = (
    "Conditional env and Playwright rules look only at explicit args on the "
    "resolved command (defaults inserted by the manager, non-interactive args, "
    "and everything after --). A token matches when it equals an arg, when "
    "--flag=value equals an arg, or when --flag is followed by value. "
    "Script-level defaults and saved settings files are not inferred, so a "
    "missing key can still be optional here and fail inside the script."
)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    manager_argv, passthrough = _split_passthrough(raw)
    manager_argv = _open_menu_when_tty(manager_argv)
    manager_argv = _normalize_globals(manager_argv)
    parser = _build_parser()
    try:
        args = parser.parse_args(manager_argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else exit_codes.USAGE
    _configure_logging(getattr(args, "log_file", None))
    _configure_stdio()
    registry_path = Path(args.registry) if args.registry else bundled_registry_path()
    try:
        registry = load_registry(registry_path)
    except RegistryError as exc:
        _emit_registry_error(exc, getattr(args, "json", False))
        return exit_codes.REGISTRY_INVALID
    try:
        if args.command == "list":
            return _cmd_list(registry, args)
        if args.command == "info":
            return _cmd_info(registry, args, passthrough)
        if args.command == "help":
            return _cmd_help(registry, args)
        if args.command == "run":
            return _cmd_run(registry, args, passthrough)
        if args.command == "validate":
            return _cmd_validate(registry, args)
        if args.command == "menu":
            return run_session(registry, repo=repo_root())
    except KeyboardInterrupt:
        logger.error("interrupted")
        return exit_codes.INTERRUPTED
    parser.error(f"unknown command {args.command}")
    return exit_codes.USAGE


def _cmd_list(registry: Registry, args) -> int:
    rows = registry.ordered()
    if args.ci:
        rows = [script for script in rows if script.ci_allowed and script.status == "active"]
    if args.tag:
        rows = [script for script in rows if args.tag in script.tags]
    if args.status:
        rows = [script for script in rows if script.status == args.status]
    payload = [
        {
            "name": script.name,
            "status": script.status,
            "needs_playwright": script.needs_playwright,
            "ci_allowed": script.ci_allowed,
            "tags": script.tags,
            "description": script.description,
        }
        for script in rows
    ]
    if args.json:
        _write_json(payload)
        return 0
    headers = ("name", "status", "needs_playwright", "ci_allowed", "tags", "description")
    table = []
    for item in payload:
        table.append(
            (
                item["name"],
                item["status"],
                _playwright_cell(item["needs_playwright"]),
                "yes" if item["ci_allowed"] else "no",
                ",".join(item["tags"]),
                item["description"],
            )
        )
    _print_table(headers, table)
    return 0


def _cmd_info(registry: Registry, args, passthrough: list[str]) -> int:
    script = registry.get(args.name)
    if script is None:
        return _unknown(args.name, registry, args.json)
    repo = repo_root()
    non_interactive = decide_noninteractive(False, False)
    args_for_child = command_args(script, passthrough, no_defaults=False, non_interactive=non_interactive)
    argv = build_argv(repo, script, args_for_child)
    try:
        dotenv = load_dotenv_file(repo, None, False)
    except EnvFileError:
        dotenv = {}
    env = merged_env(None, dotenv)
    report = missing_names(script, args_for_child, env)
    resolved = playwright_needed(script, args_for_child)
    payload = {
        "name": script.name,
        "status": script.status,
        "entry": script.entry_dict(),
        "cwd": script.cwd,
        "command": argv,
        "needs_playwright_resolved": resolved,
        "env": report,
        "timeout_seconds": script.timeout_seconds,
        "outputs": script.outputs,
        "ci_allowed": script.ci_allowed,
        "schedule": script.schedule,
    }
    if args.json:
        _write_json(payload)
        return 0
    cwd = (repo / script.cwd).resolve()
    pythonpath = [str(repo), *[str((repo / rel).resolve()) for rel in script.pythonpath]]
    print(f"name: {script.name}")
    print(f"status: {script.status}")
    if script.status_reason:
        print(f"status_reason: {script.status_reason}")
    if script.alias_of:
        print(f"alias_of: {script.alias_of}")
    if script.issue:
        print(f"issue: {script.issue}")
    print(f"description: {script.description}")
    print(f"entry: {json.dumps(script.entry_dict())}")
    print(f"cwd: {cwd}")
    print("command: " + " ".join(argv))
    print("PYTHONPATH: " + os_pathsep().join(pythonpath))
    print(f"timeout_seconds: {script.timeout_seconds}")
    print(f"needs_playwright: {script.needs_playwright}")
    print(f"needs_playwright_resolved: {resolved}")
    if script.playwright_when_args_any:
        print("playwright_when_args_any: " + ", ".join(script.playwright_when_args_any))
    print(CONDITIONAL_NOTE)
    for line in describe_env(script, args_for_child, env):
        print(line)
    print("system:")
    deps = system_dep_status(script.deps_system)
    if deps:
        for name, found in deps:
            print(f"  {name}: {'found' if found else 'missing'}")
    else:
        print("  (none)")
    print(f"ci_allowed: {script.ci_allowed}")
    print(f"interactive: {script.interactive}")
    print(f"confirm_required: {script.confirm_required}")
    print(f"local_only: {script.local_only}")
    print("side_effects: " + (", ".join(script.side_effects) if script.side_effects else "(none)"))
    print("tags: " + (", ".join(script.tags) if script.tags else "(none)"))
    print("outputs: " + (", ".join(script.outputs) if script.outputs else "(none)"))
    if script.docs:
        print(f"docs: {script.docs}")
    if script.schedule:
        print("schedule: " + json.dumps(script.schedule))
    return 0


def _cmd_help(registry: Registry, args) -> int:
    script = registry.get(args.name)
    if script is None:
        return _unknown(args.name, registry, args.json)
    repo = repo_root()
    if not script.help_supported:
        text = _registry_help(script)
        if args.json:
            _write_json({"name": script.name, "help_supported": False, "text": text})
        else:
            print(text)
        return 0
    options = RunOptions(
        passthrough=["--help"],
        non_interactive=True,
        no_dotenv=False,
        force=True,
        skip_env_check=True,
        skip_playwright=True,
        skip_system_deps=True,
        skip_confirm=True,
        timeout=30,
    )
    summary = run_script(repo, script, options)
    if args.json:
        _print_run_summary(summary, True)
    return int(summary["exit_code"])


def _cmd_run(registry: Registry, args, passthrough: list[str]) -> int:
    script = registry.get(args.name)
    if script is None:
        summary = {
            "name": args.name,
            "status": None,
            "argv": [],
            "cwd": None,
            "started_at": None,
            "finished_at": None,
            "duration_s": 0.0,
            "exit_code": exit_codes.UNKNOWN_SCRIPT,
            "failure_kind": "unknown_script",
            "env_missing": [],
            "outputs": [],
            "timed_out": False,
            "dry_run": args.dry_run,
        }
        _unknown(args.name, registry, False)
        _print_run_summary(summary, args.json)
        return exit_codes.UNKNOWN_SCRIPT
    if args.non_interactive and args.interactive:
        logger.error("pass only one of --non-interactive and --interactive")
        return exit_codes.USAGE
    if args.non_interactive:
        non_interactive = True
    elif args.interactive:
        non_interactive = False
    else:
        non_interactive = None
    options = RunOptions(
        passthrough=passthrough,
        dry_run=args.dry_run,
        timeout=args.timeout,
        env_file=Path(args.env_file) if args.env_file else None,
        no_dotenv=args.no_dotenv,
        non_interactive=non_interactive,
        yes=args.yes,
        force=args.force,
        no_defaults=args.no_defaults,
        summary_json=Path(args.summary_json) if args.summary_json else None,
        github_summary=args.github_summary,
        ci=args.ci,
        env_scope=args.env_scope,
    )
    summary = run_script(repo_root(), script, options)
    _print_run_summary(summary, args.json)
    return int(summary["exit_code"])


def _cmd_validate(registry: Registry, args) -> int:
    repo = repo_root()
    bundled = bundled_registry_path().resolve()
    current = registry.path.resolve() if registry.path else None
    errors, warnings, smoke = validate_inventory(
        repo,
        registry,
        smoke=args.smoke,
        check_unregistered=True,
        check_env_docs=current == bundled,
    )
    if args.strict and warnings:
        errors.append(f"strict: {len(warnings)} warning(s) treated as errors")
    ok = not errors
    payload = {"ok": ok, "errors": errors, "warnings": warnings}
    if args.smoke:
        payload["smoke"] = smoke
    if args.json:
        _write_json(payload)
    else:
        for warning in warnings:
            print(f"warning: {warning}")
        for error in errors:
            print(f"error: {error}")
        if ok:
            print(f"registry ok ({len(registry.scripts)} scripts)")
    for item in smoke:
        if not item["ok"] and item.get("detail"):
            logger.error("smoke %s failed:\n%s", item["name"], item["detail"][-4000:])
    return 0 if ok else exit_codes.REGISTRY_INVALID


def validate_inventory(repo, registry: Registry, *, smoke: bool, check_unregistered: bool, check_env_docs: bool):
    errors: list[str] = []
    warnings: list[str] = []
    for script in registry.ordered():
        if script.status == "planned":
            continue
        if script.entry_type == "path":
            if not script.entry_path or not (repo / script.entry_path).is_file():
                errors.append(f"{script.name}: entry not found: {script.entry_path}")
        elif entry_file(repo, script) is None:
            errors.append(f"{script.name}: module not found: {script.entry_module}")
        if not (repo / script.cwd).is_dir():
            errors.append(f"{script.name}: cwd not found: {script.cwd}")
        if script.docs and not (repo / script.docs).is_file():
            errors.append(f"{script.name}: docs not found: {script.docs}")
        for dep, found in system_dep_status(script.deps_system):
            if not found:
                warnings.append(f"{script.name}: system dependency not on PATH: {dep}")
    if check_unregistered:
        known = registered_files(repo, registry)
        for path in unregistered_scripts(repo, registry.ignore_paths, known):
            warnings.append(f"unregistered script: {path.relative_to(repo).as_posix()}")
    if check_env_docs:
        warnings.extend(_env_doc_warnings(repo, registry))
        for name, kind in MENU_REQUIRED.items():
            script = registry.get(name)
            if script is None or script.menu != kind:
                errors.append(f"{name}: menu must be {kind!r}")
    smoke_results = _run_smoke(repo, registry) if smoke else []
    for item in smoke_results:
        if not item["ok"]:
            errors.append(f"smoke {item['name']}: exit {item['exit_code']}")
    return errors, warnings, smoke_results


def _run_smoke(repo, registry: Registry) -> list[dict]:
    results = []
    for script in registry.ordered():
        if script.status == "broken":
            code, detail = smoke_import(repo, script)
            results.append(
                {
                    "name": script.name,
                    "ok": False if code != 0 else True,
                    "exit_code": code,
                    "detail": detail,
                    "mode": "import",
                }
            )
            continue
        if script.status == "active" and script.help_supported:
            summary = run_script(
                repo,
                script,
                RunOptions(
                    passthrough=["--help"],
                    non_interactive=True,
                    no_dotenv=True,
                    skip_env_check=True,
                    skip_playwright=True,
                    skip_system_deps=True,
                    skip_confirm=True,
                    timeout=30,
                ),
            )
            code = int(summary["exit_code"])
            results.append(
                {
                    "name": script.name,
                    "ok": code == 0,
                    "exit_code": code,
                    "detail": "",
                    "mode": "help",
                }
            )
    return results


def _env_doc_warnings(repo, registry: Registry) -> list[str]:
    readme = repo / "documentation" / "README.md"
    if not readme.is_file():
        return ["documentation/README.md is missing; cannot cross-check env names"]
    text = readme.read_text(encoding="utf-8")
    marker = "## Environment variables"
    start = text.find(marker)
    if start < 0:
        return ["documentation/README.md has no Environment variables section"]
    rest = text[start + len(marker):]
    next_heading = rest.find("\n## ")
    section = rest if next_heading < 0 else rest[:next_heading]
    import re

    documented = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", section))
    declared = set()
    for script in registry.scripts.values():
        declared.update(script.declared_env_names())
    warnings = []
    for name in sorted(declared - documented):
        warnings.append(f"env {name} is in the registry but not in documentation/README.md")
    for name in sorted(documented - declared):
        warnings.append(f"env {name} is in documentation/README.md but not in the registry")
    return warnings


def _registry_help(script: Script) -> str:
    lines = [
        script.description,
        f"status: {script.status}",
    ]
    if script.status_reason:
        lines.append(f"status_reason: {script.status_reason}")
    if script.docs:
        lines.append(f"docs: {script.docs}")
    lines.append(f"example: python -m scripts.script_manager run {script.name}")
    if script.help_supported:
        lines.append("This script accepts --help.")
    else:
        lines.append("This script does not publish --help. Pass its args after -- .")
    return "\n".join(lines)


def _unknown(name: str, registry: Registry, as_json: bool) -> int:
    matches = difflib.get_close_matches(name, list(registry.scripts), n=3, cutoff=0.5)
    if matches:
        message = f"unknown script {name!r}. close matches: {', '.join(matches)}"
    else:
        message = f"unknown script {name!r}"
    logger.error(message)
    if as_json:
        _write_json({"error": "unknown_script", "name": name, "suggestions": matches})
    return exit_codes.UNKNOWN_SCRIPT


def _print_run_summary(summary: dict, as_json: bool) -> None:
    if as_json:
        _write_json(summary)
        return
    print(json.dumps(summary, separators=(",", ":")))


def _write_json(payload) -> None:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _emit_registry_error(exc: RegistryError, as_json: bool) -> None:
    for line in exc.errors:
        logger.error("%s", line)
    if as_json:
        _write_json({"ok": False, "errors": exc.errors, "warnings": []})


def _print_table(headers, rows) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    def line(cells):
        print("  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(cells)))
    line(headers)
    line(tuple("-" * width for width in widths))
    for row in rows:
        line(row)


def _playwright_cell(value) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def os_pathsep():
    import os

    return os.pathsep


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _configure_logging(log_file) -> None:
    log = logging.getLogger("script_manager")
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    formatter = logging.Formatter("[script-manager] %(message)s")
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(formatter)
    log.addHandler(stderr)
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = logging.FileHandler(path, encoding="utf-8")
        handle.setFormatter(formatter)
        log.addHandler(handle)


def _open_menu_when_tty(argv: list[str]) -> list[str]:
    """No subcommand on a terminal opens the menu. A pipe still gets a usage error."""
    if any(token in _COMMANDS for token in argv):
        return argv
    try:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        interactive = False
    if interactive:
        return ["menu", *argv]
    return argv


def _split_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return argv, []
    index = argv.index("--")
    return argv[:index], argv[index + 1:]


def _normalize_globals(argv: list[str]) -> list[str]:
    """Allow --json / --registry / --log-file to appear before the subcommand."""
    prefix: list[str] = []
    rest: list[str] = []
    seen_command = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if not seen_command and token in _COMMANDS:
            seen_command = True
            rest.append(token)
            index += 1
            continue
        if not seen_command and token in _GLOBAL_FLAGS:
            prefix.append(token)
            index += 1
            continue
        if not seen_command and token in _GLOBAL_VALUES and index + 1 < len(argv):
            prefix.extend(argv[index:index + 2])
            index += 2
            continue
        name, sep, value = token.partition("=")
        if not seen_command and sep and name in _GLOBAL_VALUES:
            prefix.append(token)
            index += 1
            continue
        rest.append(token)
        index += 1
    if rest and rest[0] in _COMMANDS:
        return [rest[0], *prefix, *rest[1:]]
    return [*prefix, *rest]


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--registry", help="Path to registry.json (default: the packaged registry)")
    common.add_argument("--json", action="store_true", help="Machine-readable JSON on stdout")
    common.add_argument("--log-file", help="Also write manager logs to this file")

    parser = argparse.ArgumentParser(
        prog="script_manager",
        description="Run repository scripts with the working directory, env, and flags from the registry.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", parents=[common], help="List registered scripts")
    list_parser.add_argument("--tag")
    list_parser.add_argument("--status", choices=["active", "broken", "legacy", "planned"])
    list_parser.add_argument("--ci", action="store_true", help="Only active scripts allowed in CI")

    info_parser = sub.add_parser("info", parents=[common], help="Show one script and the resolved command")
    info_parser.add_argument("name")

    help_parser = sub.add_parser("help", parents=[common], help="Show a script's --help, or the registry description")
    help_parser.add_argument("name")

    run_parser = sub.add_parser("run", parents=[common], help="Run a registered script")
    run_parser.add_argument("name")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--timeout", type=int)
    run_parser.add_argument("--env-file")
    run_parser.add_argument("--no-dotenv", action="store_true")
    run_parser.add_argument("--non-interactive", action="store_true")
    run_parser.add_argument("--interactive", action="store_true")
    run_parser.add_argument("--yes", action="store_true")
    run_parser.add_argument("--force", action="store_true")
    run_parser.add_argument("--no-defaults", action="store_true")
    run_parser.add_argument("--summary-json")
    run_parser.add_argument("--github-summary", action="store_true")
    run_parser.add_argument("--ci", action="store_true", help="Refuse scripts that are not ci_allowed")
    run_parser.add_argument("--env-scope", choices=["declared", "inherit"])

    sub.add_parser("menu", parents=[common], help="Pick scripts, queue them, and run the queue")

    validate_parser = sub.add_parser("validate", parents=[common], help="Check the registry, paths, and unregistered scripts")
    validate_parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    validate_parser.add_argument("--smoke", action="store_true", help="Import broken scripts and run --help for active ones")
    return parser
