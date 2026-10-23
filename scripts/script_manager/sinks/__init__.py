"""Deliver a run summary to the sinks selected for that run.

A sink failure is recorded on the summary. It does not change the script exit code.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

from scripts.script_manager.contract import Contract, selected_sinks
from scripts.script_manager.registry import Registry

STAGING_DIR = "script-manager-artifact"


class SinkError(Exception):
    pass


def deliver(
    repo: Path,
    registry: Registry,
    summary: dict,
    contract: Contract,
    summary_path: Path,
) -> dict:
    script = registry.get(contract.script)
    if script is None:
        summary["sinks"] = [
            {"name": name, "ok": False, "error": "unknown script"}
            for name in (contract.outputs or ["artifact"])
        ]
        _write(summary_path, summary)
        _append_summary(summary)
        return summary
    results = []
    names = selected_sinks(script, contract)
    for name in names:
        results.append(_invoke(repo, registry, name, summary, contract, summary_path))
        summary["sinks"] = results
        _write(summary_path, summary)
    staged = repo / STAGING_DIR / "run.json"
    if staged.is_file():
        _write(staged, summary)
    _append_summary(summary)
    return summary


def _invoke(repo, registry: Registry, name: str, summary: dict, contract: Contract, summary_path: Path) -> dict:
    module_name = registry.sinks.get(name)
    if not module_name:
        return {"name": name, "ok": False, "error": "unknown sink"}
    try:
        module = importlib.import_module(module_name)
        send = getattr(module, "send", None)
        if send is None:
            raise SinkError(f"{module_name} does not define send()")
        send(
            summary,
            {
                "repo": repo,
                "contract": contract,
                "summary_path": summary_path,
                "env": os.environ,
            },
        )
    except Exception as exc:
        return {"name": name, "ok": False, "error": _public_error(exc)}
    return {"name": name, "ok": True, "error": None}


def _public_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text.splitlines()[0][:300]


def _write(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def _append_summary(summary: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["### script-manager sinks", ""]
    for item in summary.get("sinks") or []:
        if item.get("ok"):
            lines.append(f"- {item.get('name')}: ok")
        else:
            lines.append(f"- {item.get('name')}: failed: {item.get('error')}")
    lines.append("")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
