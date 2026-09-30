"""CSV read/write helpers with incremental upsert support."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Iterable

import pandas as pd


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def write_csv_rows(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    """Atomically rewrite a CSV with the given columns."""
    ensure_parent(path)
    rows_list = list(rows)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows_list:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    os.replace(tmp_path, path)


def upsert_csv_row(
    path: Path,
    row: dict,
    fieldnames: list[str],
    key_fields: list[str],
) -> None:
    """Insert or update a single row keyed by key_fields; write immediately."""
    existing = read_csv_rows(path)
    key = tuple(str(row.get(k, "")).strip().lower() for k in key_fields)
    replaced = False
    updated: list[dict] = []
    for old in existing:
        old_key = tuple(str(old.get(k, "")).strip().lower() for k in key_fields)
        if old_key == key and key != tuple("" for _ in key_fields):
            merged = dict(old)
            merged.update({k: row.get(k, merged.get(k, "")) for k in fieldnames})
            updated.append(merged)
            replaced = True
        else:
            updated.append(old)
    if not replaced:
        updated.append({k: row.get(k, "") for k in fieldnames})
    write_csv_rows(path, updated, fieldnames)


def append_csv_row(path: Path, row: dict, fieldnames: list[str]) -> None:
    ensure_parent(path)
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


def load_job_index(path: Path, id_field: str = "job_id") -> dict[str, dict]:
    rows = read_csv_rows(path)
    return {str(r.get(id_field, "")).strip(): r for r in rows if r.get(id_field)}


def dataframe_from_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")
