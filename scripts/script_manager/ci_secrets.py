"""Check that every secret a CI script declares is listed in the workflow."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.script_manager.registry import Registry

BEGIN = "# script-manager:secrets:begin"
END = "# script-manager:secrets:end"
WORKFLOW = ".github/workflows/script_manager.yml"
_KEY_RE = re.compile(r"(?m)^[ \t]*([A-Z][A-Z0-9_]*)[ \t]*:")


def secret_names(text: str) -> set[str]:
    """Env keys between the secrets markers. Values are not returned."""
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        return set()
    block = text[start:end]
    return set(_KEY_RE.findall(block))


def ci_secret_errors(registry: Registry, workflow: Path) -> list[str]:
    errors: list[str] = []
    if not workflow.is_file():
        return [f"workflow not found: {workflow.as_posix()}"]
    text = workflow.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        errors.append(f"{workflow.as_posix()}: missing {BEGIN} / {END}")
        return errors
    present = secret_names(text)
    for script in registry.ordered():
        if script.ci_allowed and script.local_only:
            errors.append(f"{script.name}: ci_allowed and local_only cannot both be set")
        if not script.ci_allowed or script.status != "active":
            continue
        for name in script.declared_env_names():
            if name not in present:
                errors.append(
                    f"{script.name}: declared env {name} is missing from the workflow secrets block"
                )
    return errors
