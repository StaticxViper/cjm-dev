"""Command line for list, info, help, run, and validate."""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import os
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

_COMMANDS = {
    "list",
    "info",
    "help",
    "run",
    "validate",
    "menu",
    "contract",
    "resolve",
    "sinks",
    "schedules",
    "stage-result",
    "stage-cancelled",
    "lookup",
}
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
        if args.command == "contract":
            return _cmd_contract(args)
        if args.command == "resolve":
            return _cmd_resolve(registry, args)
        if args.command == "sinks":
            return _cmd_sinks(registry, args)
        if args.command == "schedules":
            return _cmd_schedules(registry, args)
        if args.command == "stage-result":
            return _cmd_stage_result(args)
        if args.command == "stage-cancelled":
            return _cmd_stage_cancelled(args)
        if args.command == "lookup":
            return _cmd_lookup(args)
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
        "default_outputs": script.effective_default_outputs(),
        "ci_allowed": script.ci_allowed,
        "schedule": script.schedule,
    }
    refusal = None
    if args.ci:
        from scripts.script_manager.runner import RunOptions, ci_access_refusal, entry_refusal, status_refusal

        options = RunOptions(ci=True, dry_run=True, non_interactive=True)
        for check in (
            status_refusal(script, options),
            entry_refusal(repo, script),
            ci_access_refusal(script, options),
        ):
            if check is not None:
                refusal = check
                break
        code, message = refusal if refusal is not None else (0, "")
        payload["ok"] = refusal is None
        payload["exit_code"] = code
        payload["failure_kind"] = None if code == 0 else exit_codes.failure_kind_for(code, child_finished=False)
        payload["message"] = message
    if args.json:
        _write_json(payload)
        if refusal is not None:
            logger.error("%s", refusal[1])
        return 0 if refusal is None else refusal[0]
    if refusal is not None:
        logger.error("%s", refusal[1])
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
    print("default_outputs: " + ", ".join(script.effective_default_outputs()))
    if script.docs:
        print(f"docs: {script.docs}")
    if script.schedule:
        print("schedule: " + json.dumps(script.schedule))
    if refusal is not None:
        return refusal[0]
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
    contract = None
    if args.from_contract:
        try:
            from scripts.script_manager.contract import read_contract

            contract = read_contract(Path(args.from_contract))
        except Exception as exc:
            logger.error("%s", exc)
            return exit_codes.USAGE
        if args.name and args.name != contract.script:
            logger.error("contract script %s does not match %s", contract.script, args.name)
            return exit_codes.USAGE
        name = contract.script
        passthrough = list(contract.argv)
    else:
        name = args.name
    if not name:
        logger.error("run requires a script name or --from-contract")
        return exit_codes.USAGE
    script = registry.get(name)
    dry_run = bool(args.dry_run or (contract.dry_run if contract else False))
    if script is None:
        summary = {
            "name": name,
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
            "dry_run": dry_run,
            "request_id": contract.request_id if contract else None,
            "trigger": _trigger_from_contract(contract),
            "run_url": (contract.run_url or None) if contract else None,
            "run_id": (contract.run_id or None) if contract else None,
            "message": f"unknown script {name!r}",
            "data": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "output_files": {},
        }
        _unknown(name, registry, False)
        if args.summary_json:
            Path(args.summary_json).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        _print_run_summary(summary, args.json)
        return _accepted_code(exit_codes.UNKNOWN_SCRIPT, "unknown_script", args.accept_rejection)
    if args.non_interactive and args.interactive:
        logger.error("pass only one of --non-interactive and --interactive")
        return exit_codes.USAGE
    if args.non_interactive or contract is not None:
        non_interactive = True
    elif args.interactive:
        non_interactive = False
    else:
        non_interactive = None
    options = RunOptions(
        passthrough=passthrough,
        dry_run=dry_run,
        timeout=args.timeout,
        env_file=Path(args.env_file) if args.env_file else None,
        no_dotenv=args.no_dotenv,
        non_interactive=non_interactive,
        yes=bool(args.yes or args.confirm or (contract.confirm if contract else False)),
        force=args.force,
        no_defaults=args.no_defaults,
        summary_json=Path(args.summary_json) if args.summary_json else None,
        github_summary=args.github_summary,
        ci=args.ci or contract is not None,
        env_scope=args.env_scope or ("declared" if contract is not None else None),
        request_id=contract.request_id if contract else None,
        trigger=_trigger_from_contract(contract) if contract else None,
        run_url=(contract.run_url or None) if contract else None,
        run_id=(contract.run_id or None) if contract else None,
    )
    summary = run_script(repo_root(), script, options)
    _print_run_summary(summary, args.json)
    return _accepted_code(int(summary["exit_code"]), summary.get("failure_kind"), args.accept_rejection)


def _cmd_contract(args) -> int:
    from scripts.script_manager.contract import ContractError, build_contract, contract_b64, write_contract, write_github_output

    try:
        contract = build_contract()
    except ContractError as exc:
        logger.error("%s", exc)
        _write_contract_failure(args, exc)
        return _accepted_code(exit_codes.USAGE, "usage", args.accept_rejection)
    if args.out:
        write_contract(Path(args.out), contract)
    if args.github_output:
        write_github_output(
            {
                "script": contract.script,
                "request_id": contract.request_id,
                "contract_b64": contract_b64(contract),
                "rejected": "false",
            }
        )
    if args.json:
        _write_json(contract.to_dict())
    else:
        print(contract.script)
        print(contract.request_id)
    return 0


def _cmd_resolve(registry: Registry, args) -> int:
    from scripts.script_manager.contract import (
        Contract,
        ContractError,
        read_contract,
        resolve_payload,
        write_github_output,
    )

    try:
        if args.from_contract:
            contract = read_contract(Path(args.from_contract))
        else:
            if not args.name:
                logger.error("resolve requires a script name or --from-contract")
                return exit_codes.USAGE
            contract = Contract(
                script=args.name,
                args="",
                argv=[],
                request_id="resolve",
                outputs=None,
                confirm=bool(args.confirm),
                dry_run=bool(args.dry_run),
                callback_url="",
                trigger="cli",
                actor="",
                caller="",
                run_url="",
                run_id="",
            )
    except ContractError as exc:
        logger.error("%s", exc)
        return exit_codes.USAGE
    payload, code = resolve_payload(repo_root(), registry, contract)
    if code == exit_codes.UNKNOWN_SCRIPT:
        _unknown(contract.script, registry, False)
    elif payload.get("message"):
        logger.error("%s", payload["message"])
    if args.github_output:
        write_github_output(
            {
                "timeout_minutes": str(payload.get("timeout_minutes") or 1),
                "playwright": "true" if payload.get("needs_playwright") else "false",
                "request_id": contract.request_id,
                "script": contract.script,
                "rejected": "true" if _is_accepted(code, payload.get("failure_kind"), args.accept_rejection) else "false",
            }
        )
    if args.summary_json:
        Path(args.summary_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary_json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.json:
        _write_json(payload)
    else:
        print(json.dumps(payload, indent=2))
    return _accepted_code(code, payload.get("failure_kind"), args.accept_rejection)


def _cmd_sinks(registry: Registry, args) -> int:
    from scripts.script_manager.contract import ContractError, read_contract
    from scripts.script_manager.sinks import deliver

    summary_path = Path(args.summary)
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("cannot read run summary: %s", exc)
        return 0
    if not isinstance(summary, dict):
        logger.error("run summary must be a JSON object")
        return 0
    try:
        contract = read_contract(Path(args.from_contract))
    except ContractError as exc:
        logger.error("%s", exc)
        summary["sinks"] = [{"name": "contract", "ok": False, "error": str(exc)}]
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 0
    deliver(repo_root(), registry, summary, contract, summary_path)
    return 0


def _cmd_schedules(registry: Registry, args) -> int:
    from scripts.script_manager.schedules import (
        SCHEDULE_WORKFLOW,
        ScheduleError,
        due_matrix,
        render_schedule_block,
        replace_schedule_block,
        schedule_block_matches,
    )
    from scripts.script_manager.contract import write_github_output

    repo = repo_root()
    workflow = Path(args.workflow) if args.workflow else repo / SCHEDULE_WORKFLOW
    flags = [bool(args.due), bool(args.check), bool(args.write)]
    if sum(flags) != 1:
        logger.error("pass one of --due, --check, or --write")
        return exit_codes.USAGE
    if args.due:
        try:
            matrix = due_matrix(registry, now=_parse_now(args.now), cron=args.cron)
        except ScheduleError as exc:
            logger.error("%s", exc)
            return exit_codes.REGISTRY_INVALID
        text = json.dumps(matrix, separators=(",", ":"))
        if args.github_output:
            write_github_output({"matrix": text})
        if args.json:
            _write_json(matrix)
        elif not args.github_output:
            print(text)
        return 0
    if not workflow.is_file():
        logger.error("schedule workflow not found: %s", workflow)
        return exit_codes.REGISTRY_INVALID
    text = workflow.read_text(encoding="utf-8")
    try:
        if args.check:
            if schedule_block_matches(text, registry):
                print("schedules ok")
                return 0
            logger.error("schedule workflow cron block does not match the registry. Run schedules --write.")
            return exit_codes.REGISTRY_INVALID
        updated = replace_schedule_block(text, render_schedule_block(registry))
    except ScheduleError as exc:
        logger.error("%s", exc)
        return exit_codes.REGISTRY_INVALID
    workflow.write_text(updated, encoding="utf-8")
    print(f"wrote {workflow}")
    return 0


def _write_contract_failure(args, exc: Exception) -> None:
    """Write a run summary when the contract itself is rejected, and keep request_id for the artifact name."""
    from scripts.script_manager.contract import write_github_output

    from scripts.script_manager.contract import REQUEST_ID_RE

    request_id = (
        os.environ.get("SCRIPT_MANAGER_INPUT_REQUEST_ID")
        or os.environ.get("SCRIPT_MANAGER_RUN_ID")
        or "rejected"
    ).strip()
    if not REQUEST_ID_RE.fullmatch(request_id):
        request_id = "rejected"
    script = (os.environ.get("SCRIPT_MANAGER_INPUT_SCRIPT") or "").strip()
    event = (os.environ.get("SCRIPT_MANAGER_INPUT_TRIGGER") or os.environ.get("SCRIPT_MANAGER_EVENT_NAME") or "").strip()
    actor = (os.environ.get("SCRIPT_MANAGER_ACTOR") or "").strip()
    caller = (os.environ.get("SCRIPT_MANAGER_CALLER") or actor).strip()
    summary = {
        "name": script or None,
        "status": None,
        "request_id": request_id,
        "trigger": {"event": event or None, "actor": actor or None, "caller": caller or None},
        "run_url": (os.environ.get("SCRIPT_MANAGER_RUN_URL") or "").strip() or None,
        "run_id": (os.environ.get("SCRIPT_MANAGER_RUN_ID") or "").strip() or None,
        "exit_code": exit_codes.USAGE,
        "failure_kind": "usage",
        "message": str(exc),
        "data": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "output_files": {},
        "outputs": [],
        "dry_run": False,
    }
    if getattr(args, "summary_json", None):
        path = Path(args.summary_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if getattr(args, "github_output", False):
        rejected = _is_accepted(exit_codes.USAGE, "usage", getattr(args, "accept_rejection", False))
        write_github_output(
            {
                "request_id": request_id,
                "script": script,
                "rejected": "true" if rejected else "false",
                "exit_code": str(exit_codes.USAGE),
                "failure_kind": "usage",
            }
        )
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        _append_rejection_summary(summary)


def _cmd_stage_result(args) -> int:
    """Copy the first existing summary into the artifact path and note it on the job summary."""
    dest = Path(args.dest)
    chosen = None
    for raw in args.summary or []:
        path = Path(raw)
        if path.is_file():
            chosen = path
            break
    dest.parent.mkdir(parents=True, exist_ok=True)
    if chosen is None:
        payload = {
            "name": None,
            "request_id": os.environ.get("SCRIPT_MANAGER_RUN_ID") or os.environ.get("GITHUB_RUN_ID"),
            "exit_code": exit_codes.USAGE,
            "failure_kind": "usage",
            "message": "script manager failed before it could write a summary",
            "data": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "output_files": {},
            "outputs": [],
        }
        dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        dest.write_text(chosen.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            payload = json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"message": chosen.read_text(encoding="utf-8")[:500], "failure_kind": "usage"}
    if isinstance(payload, dict):
        _append_rejection_summary(payload)
    return 0


def _cmd_stage_cancelled(args) -> int:
    """Write a run.json for a workflow GitHub cancelled before the script finished."""
    request_id = (os.environ.get("SCRIPT_MANAGER_REQUEST_ID") or os.environ.get("SCRIPT_MANAGER_RUN_ID") or "cancelled").strip()
    event = (os.environ.get("SCRIPT_MANAGER_EVENT_NAME") or "").strip()
    actor = (os.environ.get("SCRIPT_MANAGER_ACTOR") or "").strip()
    caller = (os.environ.get("SCRIPT_MANAGER_CALLER") or actor).strip()
    summary = {
        "name": (os.environ.get("SCRIPT_MANAGER_SCRIPT") or "").strip() or None,
        "status": None,
        "request_id": request_id,
        "trigger": {"event": event or None, "actor": actor or None, "caller": caller or None},
        "run_url": (os.environ.get("SCRIPT_MANAGER_RUN_URL") or "").strip() or None,
        "run_id": (os.environ.get("SCRIPT_MANAGER_RUN_ID") or "").strip() or None,
        "exit_code": exit_codes.INTERRUPTED,
        "failure_kind": "cancelled",
        "message": "GitHub Actions cancelled this run before it finished. The script result was not produced.",
        "data": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "output_files": {},
        "outputs": [],
        "dry_run": False,
    }
    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _append_rejection_summary(summary)
    return 0


def _cmd_lookup(args) -> int:
    from scripts.script_manager.contract import REQUEST_ID_RE
    from scripts.script_manager.lookup import lookup

    request_id = (args.request_id or "").strip()
    if not REQUEST_ID_RE.fullmatch(request_id):
        logger.error("request_id must be 1-80 characters of letters, digits, dot, underscore, or hyphen")
        return exit_codes.USAGE
    result = lookup(request_id, repo=args.repo)
    _write_json(result)
    return 0


def _append_rejection_summary(summary: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    trigger = summary.get("trigger") if isinstance(summary.get("trigger"), dict) else {}
    text = (
        f"### script-manager {exit_codes.result_label(summary)}\n\n"
        f"- request_id: {summary.get('request_id')}\n"
        f"- name: {summary.get('name')}\n"
        f"- trigger: {trigger.get('event')}\n"
        f"- caller: {trigger.get('caller')}\n"
        f"- run_url: {summary.get('run_url')}\n"
        f"- exit_code: {summary.get('exit_code')}\n"
        f"- failure_kind: {summary.get('failure_kind')}\n"
        f"- message: {summary.get('message')}\n\n"
    )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def _trigger_from_contract(contract):
    if contract is None:
        return {"event": "cli", "actor": None, "caller": None}
    from scripts.script_manager.contract import trigger_view

    return trigger_view(contract)


def _is_accepted(code, failure_kind, accept: bool) -> bool:
    return bool(accept) and exit_codes.is_expected_rejection(code, failure_kind)


def _accepted_code(code: int, failure_kind, accept: bool) -> int:
    """Keep the summary's exit code. The process exits 0 for an expected refusal."""
    if _is_accepted(code, failure_kind, accept):
        return 0
    return code


def _parse_now(value: str | None):
    if not value:
        return None
    from datetime import datetime

    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


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
    if args.ci_secrets:
        from scripts.script_manager.ci_secrets import WORKFLOW, ci_secret_errors

        workflow = Path(args.workflow) if args.workflow else repo / WORKFLOW
        errors.extend(ci_secret_errors(registry, workflow))
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
        if script.local_only:
            continue
        for dep, found in system_dep_status(script.deps_system):
            if not found:
                warnings.append(f"{script.name}: system dependency not on PATH: {dep}")
    if check_unregistered:
        known = registered_files(repo, registry)
        for path in unregistered_scripts(repo, registry.ignore_paths, known, registry.discover_roots):
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
    info_parser.add_argument("--ci", action="store_true", help="Exit 67 when this script cannot run in CI")

    help_parser = sub.add_parser("help", parents=[common], help="Show a script's --help, or the registry description")
    help_parser.add_argument("name")

    run_parser = sub.add_parser("run", parents=[common], help="Run a registered script")
    run_parser.add_argument("name", nargs="?")
    run_parser.add_argument("--from-contract", help="Read script, args, confirm, and dry_run from a contract file")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--timeout", type=int)
    run_parser.add_argument("--env-file")
    run_parser.add_argument("--no-dotenv", action="store_true")
    run_parser.add_argument("--non-interactive", action="store_true")
    run_parser.add_argument("--interactive", action="store_true")
    run_parser.add_argument("--yes", action="store_true")
    run_parser.add_argument("--confirm", action="store_true", help="Allow a script with side effects or confirm_required")
    run_parser.add_argument("--force", action="store_true")
    run_parser.add_argument("--no-defaults", action="store_true")
    run_parser.add_argument("--summary-json")
    run_parser.add_argument("--github-summary", action="store_true")
    run_parser.add_argument("--ci", action="store_true", help="Refuse scripts that are not active, local_only, or ci_allowed")
    run_parser.add_argument("--env-scope", choices=["declared", "inherit"])
    run_parser.add_argument(
        "--accept-rejection",
        action="store_true",
        help="Exit 0 for usage, unknown_script, and confirmation_required. The summary keeps the real exit code",
    )

    sub.add_parser("menu", parents=[common], help="Pick scripts, queue them, and run the queue")

    validate_parser = sub.add_parser("validate", parents=[common], help="Check the registry, paths, and unregistered scripts")
    validate_parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    validate_parser.add_argument("--smoke", action="store_true", help="Import broken scripts and run --help for active ones")
    validate_parser.add_argument("--ci-secrets", action="store_true", help="Fail when a ci_allowed script declares an env name missing from the workflow")
    validate_parser.add_argument("--workflow", help="Workflow file for --ci-secrets")

    contract_parser = sub.add_parser("contract", parents=[common], help="Write a CI run contract from the environment")
    contract_parser.add_argument("--out", help="Write contract JSON to this path")
    contract_parser.add_argument("--summary-json", help="On failure, write a run summary to this path")
    contract_parser.add_argument("--github-output", action="store_true", help="Append script, request_id, and contract_b64 to GITHUB_OUTPUT")
    contract_parser.add_argument(
        "--accept-rejection",
        action="store_true",
        help="Exit 0 when the contract is rejected. The summary keeps exit code 2",
    )

    resolve_parser = sub.add_parser("resolve", parents=[common], help="Resolve a script for CI without running it")
    resolve_parser.add_argument("name", nargs="?")
    resolve_parser.add_argument("--from-contract")
    resolve_parser.add_argument("--confirm", action="store_true")
    resolve_parser.add_argument("--dry-run", action="store_true")
    resolve_parser.add_argument("--github-output", action="store_true")
    resolve_parser.add_argument("--summary-json", help="Write the resolve document, including refusals")
    resolve_parser.add_argument(
        "--accept-rejection",
        action="store_true",
        help="Exit 0 for usage, unknown_script, and confirmation_required",
    )

    stage_parser = sub.add_parser("stage-result", parents=[common], help="Copy a run summary into the artifact directory")
    stage_parser.add_argument("--dest", required=True)
    stage_parser.add_argument("--summary", action="append", default=[], help="Candidate summary file. The first one that exists is copied")

    cancelled_parser = sub.add_parser("stage-cancelled", parents=[common], help="Write a cancelled run summary for the artifact")
    cancelled_parser.add_argument("--dest", required=True)

    lookup_parser = sub.add_parser("lookup", parents=[common], help="Find a run and artifact by request_id")
    lookup_parser.add_argument("--request-id", required=True)
    lookup_parser.add_argument("--repo", help="OWNER/NAME. Defaults to GITHUB_REPOSITORY")

    sinks_parser = sub.add_parser("sinks", parents=[common], help="Deliver a run summary. Sink failures stay in the summary")
    sinks_parser.add_argument("--summary", required=True)
    sinks_parser.add_argument("--from-contract", required=True)

    schedules_parser = sub.add_parser("schedules", parents=[common], help="Generate, check, or list due cron schedules")
    schedules_parser.add_argument("--due", action="store_true")
    schedules_parser.add_argument("--check", action="store_true")
    schedules_parser.add_argument("--write", action="store_true")
    schedules_parser.add_argument("--workflow")
    schedules_parser.add_argument("--now", help="UTC timestamp for --due, such as 2026-10-13T14:05:00Z")
    schedules_parser.add_argument("--github-output", action="store_true")
    schedules_parser.add_argument("--cron", help="With --due, select scripts registered for this cron and ignore the clock")
    return parser
