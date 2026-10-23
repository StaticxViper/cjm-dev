"""CI run contract: one shape for every trigger.

Callers pass script, args, request_id, outputs, confirm, and dry_run through
environment variables or a repository_dispatch client_payload. Args are split
with shlex here. The workflow shell never receives them.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path

from scripts.script_manager import exit_codes
from scripts.script_manager.envcheck import playwright_needed
from scripts.script_manager.registry import Registry, Script
from scripts.script_manager.runner import (
    RunOptions,
    ci_access_refusal,
    command_args,
    confirm_refusal,
    entry_refusal,
    status_refusal,
)

SCRIPT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
JOB_TIMEOUT_CAP_MINUTES = 360

_INPUT_SCRIPT = "SCRIPT_MANAGER_INPUT_SCRIPT"
_INPUT_ARGS = "SCRIPT_MANAGER_INPUT_ARGS"
_INPUT_REQUEST_ID = "SCRIPT_MANAGER_INPUT_REQUEST_ID"
_INPUT_OUTPUTS = "SCRIPT_MANAGER_INPUT_OUTPUTS"
_INPUT_CONFIRM = "SCRIPT_MANAGER_INPUT_CONFIRM"
_INPUT_DRY_RUN = "SCRIPT_MANAGER_INPUT_DRY_RUN"
_INPUT_CALLBACK = "SCRIPT_MANAGER_INPUT_CALLBACK_URL"
_EVENT_NAME = "SCRIPT_MANAGER_EVENT_NAME"
_EVENT_PATH = "SCRIPT_MANAGER_EVENT_PATH"
_RUN_ID = "SCRIPT_MANAGER_RUN_ID"


class ContractError(Exception):
    """The contract itself is unusable. This is a usage error, exit 2."""


@dataclass
class Contract:
    script: str
    args: str
    argv: list[str]
    request_id: str
    outputs: list[str] | None
    confirm: bool
    dry_run: bool
    callback_url: str
    trigger: str

    def to_dict(self) -> dict:
        return {
            "script": self.script,
            "args": self.args,
            "argv": list(self.argv),
            "request_id": self.request_id,
            "outputs": None if self.outputs is None else list(self.outputs),
            "confirm": self.confirm,
            "dry_run": self.dry_run,
            "callback_url": self.callback_url,
            "trigger": self.trigger,
        }


def build_contract(env: dict | None = None) -> Contract:
    """Build a contract from process env and, for repository_dispatch, the event file."""
    source = os.environ if env is None else env
    event_name = str(source.get(_EVENT_NAME, "") or "").strip()
    payload = _client_payload(source, event_name)
    script = _first(source.get(_INPUT_SCRIPT), payload.get("script"))
    if not script:
        raise ContractError("script is required")
    if not SCRIPT_RE.fullmatch(script):
        raise ContractError(f"script {script!r} must match {SCRIPT_RE.pattern}")
    raw_args = _first(source.get(_INPUT_ARGS), payload.get("args"))
    if isinstance(payload.get("args"), list) and not str(source.get(_INPUT_ARGS, "") or "").strip():
        raise ContractError("args must be a string; the Script Manager splits it")
    try:
        argv = shlex.split(raw_args, posix=True) if raw_args else []
    except ValueError as exc:
        raise ContractError(f"args could not be split: {exc}") from exc
    request_id = _first(source.get(_INPUT_REQUEST_ID), payload.get("request_id"), source.get(_RUN_ID))
    if not request_id:
        request_id = uuid.uuid4().hex
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ContractError("request_id must be 1-80 characters of letters, digits, dot, underscore, or hyphen")
    outputs = _outputs(source.get(_INPUT_OUTPUTS), payload.get("outputs"))
    confirm = _as_bool(_prefer(source.get(_INPUT_CONFIRM), payload.get("confirm")))
    dry_run = _as_bool(_prefer(source.get(_INPUT_DRY_RUN), payload.get("dry_run")))
    callback_url = _first(source.get(_INPUT_CALLBACK), payload.get("callback_url"))
    return Contract(
        script=script,
        args=raw_args,
        argv=argv,
        request_id=request_id,
        outputs=outputs,
        confirm=confirm,
        dry_run=dry_run,
        callback_url=callback_url,
        trigger=event_name or "cli",
    )


def write_contract(path: Path, contract: Contract) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract.to_dict(), indent=2) + "\n", encoding="utf-8")


def read_contract(path: Path) -> Contract:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read contract {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("contract must be a JSON object")
    script = data.get("script")
    if not isinstance(script, str) or not SCRIPT_RE.fullmatch(script):
        raise ContractError("contract script is missing or invalid")
    argv = data.get("argv", [])
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise ContractError("contract argv must be a list of strings")
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise ContractError("contract request_id is missing or invalid")
    outputs = data.get("outputs", None)
    if outputs is not None and (
        not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs)
    ):
        raise ContractError("contract outputs must be a list of strings or null")
    return Contract(
        script=script,
        args=data.get("args") if isinstance(data.get("args"), str) else "",
        argv=list(argv),
        request_id=request_id,
        outputs=None if outputs is None else list(outputs),
        confirm=bool(data.get("confirm")),
        dry_run=bool(data.get("dry_run")),
        callback_url=data.get("callback_url") if isinstance(data.get("callback_url"), str) else "",
        trigger=data.get("trigger") if isinstance(data.get("trigger"), str) else "",
    )


def contract_b64(contract: Contract) -> str:
    raw = json.dumps(contract.to_dict(), separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def run_options_from_contract(contract: Contract, **overrides) -> RunOptions:
    options = RunOptions(
        passthrough=list(contract.argv),
        dry_run=contract.dry_run,
        non_interactive=True,
        yes=contract.confirm,
        ci=True,
        env_scope="declared",
        request_id=contract.request_id,
    )
    for key, value in overrides.items():
        setattr(options, key, value)
    if overrides.get("yes"):
        options.yes = True
    if overrides.get("dry_run"):
        options.dry_run = True
    return options


def resolve_payload(repo: Path, registry: Registry, contract: Contract) -> tuple[dict, int]:
    """Return the resolve document and the process exit code."""
    script = registry.get(contract.script)
    if script is None:
        return {
            "ok": False,
            "name": contract.script,
            "status": None,
            "exit_code": exit_codes.UNKNOWN_SCRIPT,
            "failure_kind": "unknown_script",
            "request_id": contract.request_id,
            "message": f"unknown script {contract.script!r}",
            "data": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "output_files": {},
            "outputs": [],
            "dry_run": contract.dry_run,
        }, exit_codes.UNKNOWN_SCRIPT
    options = run_options_from_contract(contract)
    code, message = _resolve_refusal(repo, script, options)
    args = command_args(script, contract.argv, no_defaults=False, non_interactive=True)
    timeout_minutes = max(1, min(JOB_TIMEOUT_CAP_MINUTES, math.ceil(script.timeout_seconds / 60)))
    selected = _selected_output_names(script, contract)
    payload = {
        "ok": code == 0,
        "name": script.name,
        "status": script.status,
        "ci_allowed": script.ci_allowed,
        "local_only": script.local_only,
        "needs_playwright": bool(playwright_needed(script, args)),
        "timeout_seconds": script.timeout_seconds,
        "timeout_minutes": timeout_minutes,
        "outputs": list(script.outputs),
        "default_outputs": script.effective_default_outputs(),
        "selected_outputs": selected,
        "env_names": script.declared_env_names(),
        "confirm_required": script.confirm_required,
        "side_effects": list(script.side_effects),
        "needs_confirm": bool(script.confirm_required or script.side_effects),
        "confirm": contract.confirm,
        "dry_run": contract.dry_run,
        "request_id": contract.request_id,
        "exit_code": code,
        "failure_kind": None if code == 0 else exit_codes.failure_kind_for(code, child_finished=False),
        "message": message,
        "data": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "output_files": {},
    }
    return payload, code


def selected_sinks(script: Script, contract: Contract) -> list[str]:
    """Sinks for this run. artifact is always last so it includes the other results."""
    if contract.dry_run:
        names = ["artifact"]
    else:
        names = _selected_output_names(script, contract)
        if "artifact" not in names:
            names.insert(0, "artifact")
        names = [name for name in names if name != "artifact"] + ["artifact"]
    return names


def write_github_output(values: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            text = "" if value is None else str(value)
            if "\n" in text or "\r" in text:
                marker = f"EOF_{uuid.uuid4().hex}"
                handle.write(f"{key}<<{marker}\n{text}\n{marker}\n")
            else:
                handle.write(f"{key}={text}\n")


def _resolve_refusal(repo: Path, script: Script, options: RunOptions) -> tuple[int, str]:
    for check in (
        status_refusal(script, options),
        entry_refusal(repo, script),
        ci_access_refusal(script, options),
        confirm_refusal(script, options),
    ):
        if check is not None:
            return check
    return 0, ""


def _selected_output_names(script: Script, contract: Contract) -> list[str]:
    if contract.outputs is None:
        return script.effective_default_outputs()
    return list(contract.outputs)


def _client_payload(env: dict, event_name: str) -> dict:
    if event_name != "repository_dispatch":
        return {}
    path = str(env.get(_EVENT_PATH, "") or "").strip()
    if not path:
        raise ContractError("repository_dispatch requires SCRIPT_MANAGER_EVENT_PATH")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read GitHub event: {exc}") from exc
    payload = data.get("client_payload") if isinstance(data, dict) else None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ContractError("client_payload must be an object")
    return payload


def _first(*values) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _prefer(primary, fallback):
    """Env inputs win when set. An empty string falls through to the payload."""
    if primary is None:
        return fallback
    if isinstance(primary, str) and not primary.strip():
        return fallback
    return primary


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes"}


def _outputs(from_env, from_payload):
    chosen = _prefer(from_env, from_payload)
    if chosen is None:
        return None
    if isinstance(chosen, list):
        if not all(isinstance(item, str) and item.strip() for item in chosen):
            raise ContractError("outputs must be a comma-separated string or a list of names")
        return [item.strip() for item in chosen]
    text = str(chosen).strip()
    if not text:
        return None
    names = [part.strip() for part in text.split(",") if part.strip()]
    if not names:
        return None
    return names
