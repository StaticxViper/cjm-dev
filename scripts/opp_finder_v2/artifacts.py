"""Screenshot, HTML, and meta dumps for errors and block pages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def format_z(moment: datetime | None = None) -> str:
    current = moment or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_from(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def save_artifact(
    root: Path,
    run_id: str,
    site_id: str,
    step: str,
    *,
    url: str,
    status: str,
    reason: str,
    html: str,
    png_bytes: bytes | None = None,
) -> str:
    folder = Path(root) / run_id / site_id
    folder.mkdir(parents=True, exist_ok=True)
    index = len(list(folder.glob(f"{step}_*.html"))) + 1
    stem = f"{step}_{index}"
    (folder / f"{stem}.html").write_text(html or "", encoding="utf-8")
    if png_bytes:
        (folder / f"{stem}.png").write_bytes(png_bytes)
    meta = {
        "url": url,
        "status": status,
        "reason": reason,
        "timestamp": format_z(),
        "html": f"{stem}.html",
        "png": f"{stem}.png" if png_bytes else None,
    }
    (folder / f"{stem}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return str(folder)
