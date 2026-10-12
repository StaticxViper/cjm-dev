"""Environment checks for a script run.

Values are merged into the child environment and never returned to callers
that print output. Reports contain names only.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from scripts.script_manager.registry import Script

# Names and prefixes a declared-scope child may see even when the script did
# not list them. Windows needs the system and profile paths so Python and
# Playwright can start; none of these are script secrets.
_SAFE_EXACT = {
    "PATH",
    "PATHEXT",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "USERNAME",
    "USER",
    "LANG",
    "PLAYWRIGHT_BROWSERS_PATH",
    "CI",
}
_SAFE_PREFIXES = ("PYTHON", "GITHUB_", "RUNNER_", "LC_")


class EnvFileError(Exception):
    """Raised when an explicit --env-file path does not exist."""


def args_match(token: str, args: list[str]) -> bool:
    """Return True when a conditional token matches explicit args.

    A token matches when it equals an arg, when ``--flag=value`` equals an
    arg, or when ``--flag`` is immediately followed by ``value``.
    """
    if token in args:
        return True
    if token.startswith("--") and "=" in token:
        flag, _, value = token.partition("=")
        for index, arg in enumerate(args):
            if arg == flag and index + 1 < len(args) and args[index + 1] == value:
                return True
    return False


def triggered_rules(script: Script, args: list[str]) -> list[dict]:
    return [
        rule
        for rule in script.env_conditional
        if any(args_match(token, args) for token in rule.get("when_args_any", []))
    ]


def load_dotenv_file(repo: Path, env_file: Path | None, no_dotenv: bool) -> dict[str, str]:
    if no_dotenv:
        return {}
    path = Path(env_file) if env_file is not None else repo / ".env"
    if env_file is not None and not path.is_file():
        raise EnvFileError(f"env file not found: {path}")
    if not path.is_file():
        return {}
    loaded = dotenv_values(path)
    values = {}
    for key, value in loaded.items():
        if key and value is not None:
            values[key] = value
    return values


def merged_env(process: dict[str, str] | None = None, dotenv: dict[str, str] | None = None) -> dict[str, str]:
    """Process environment wins over the env file, including empty process values."""
    base = dict(os.environ if process is None else process)
    for key, value in (dotenv or {}).items():
        if key not in base and value is not None:
            base[key] = value
    return base


def is_set(env: dict[str, str], name: str) -> bool:
    value = env.get(name)
    return value is not None and str(value).strip() != ""


def missing_names(script: Script, args: list[str], env: dict[str, str]) -> dict[str, list[str]]:
    required_missing = [name for name in script.env_required if not is_set(env, name)]
    optional_missing = [name for name in script.env_optional if not is_set(env, name)]
    conditional_missing: list[str] = []
    for rule in triggered_rules(script, args):
        for name in rule.get("require", []):
            if not is_set(env, name) and name not in conditional_missing:
                conditional_missing.append(name)
    return {
        "required_missing": required_missing,
        "optional_missing": optional_missing,
        "conditional_missing": conditional_missing,
    }


def env_scope_mode(explicit: str | None, process: dict[str, str] | None = None) -> str:
    if explicit in {"declared", "inherit"}:
        return explicit
    source = os.environ if process is None else process
    if str(source.get("CI", "")).strip().lower() in {"1", "true", "yes"}:
        return "declared"
    return "inherit"


def _safe_base(name: str) -> bool:
    if name in _SAFE_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in _SAFE_PREFIXES)


def apply_env_scope(script: Script, env: dict[str, str], scope: str) -> dict[str, str]:
    if scope != "declared":
        return dict(env)
    allowed = set(script.declared_env_names())
    return {key: value for key, value in env.items() if key in allowed or _safe_base(key)}


def build_child_env(
    repo: Path,
    script: Script,
    *,
    env_file: Path | None = None,
    no_dotenv: bool = False,
    env_scope: str | None = None,
    process: dict[str, str] | None = None,
) -> dict[str, str]:
    dotenv = load_dotenv_file(repo, env_file, no_dotenv)
    merged = merged_env(process, dotenv)
    scope = env_scope_mode(env_scope, process)
    child = apply_env_scope(script, merged, scope)
    parts = [str(repo)]
    for rel in script.pythonpath:
        parts.append(str((repo / rel).resolve()))
    existing = child.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    child["PYTHONPATH"] = os.pathsep.join(parts)
    child["PYTHONUNBUFFERED"] = "1"
    return child


def playwright_needed(script: Script, args: list[str]) -> bool:
    if script.needs_playwright is True:
        return True
    if script.needs_playwright == "conditional":
        return any(args_match(token, args) for token in script.playwright_when_args_any)
    return False
