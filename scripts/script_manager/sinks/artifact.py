"""Stage run.json, declared output files, and the manager log for upload."""

from __future__ import annotations

import shutil
from pathlib import Path

from scripts.script_manager.sinks import STAGING_DIR


def send(run_result: dict, config: dict) -> None:
    repo: Path = config["repo"]
    staging = repo / STAGING_DIR
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    summary_path: Path = config["summary_path"]
    if summary_path.is_file():
        shutil.copy2(summary_path, staging / "run.json")
    else:
        (staging / "run.json").write_text("{}\n", encoding="utf-8")
    log_path = config.get("log_path") or (repo / "script-manager.log")
    if log_path and Path(log_path).is_file():
        shutil.copy2(log_path, staging / Path(log_path).name)
    for rel in run_result.get("outputs") or []:
        source = (repo / rel).resolve()
        try:
            source.relative_to(repo.resolve())
        except ValueError:
            continue
        if not source.is_file():
            continue
        target = staging / "outputs" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
