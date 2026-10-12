"""Small input helpers shared by the script menus."""

from __future__ import annotations


def ask(reader, prompt: str) -> str:
    return reader(prompt).strip()


def say(writer, text: str = "") -> None:
    writer(text)


def yes(raw: str, default: bool = True) -> bool:
    value = raw.strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def parse_index_selection(raw: str, max_index: int) -> list[int] | None:
    """Parse '1,3' or '1-4,8'. Empty or 'all' means everything (None)."""
    if not raw or not raw.strip():
        return None
    lowered = raw.strip().lower()
    if lowered in {"all", "*"}:
        return None
    if lowered in {"none", "n"}:
        return []
    indices: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and not part.startswith("-"):
            ends = part.split("-", 1)
            try:
                start = int(ends[0].strip())
                end = int(ends[1].strip())
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                idx = number - 1
                if 0 <= idx < max_index and idx not in indices:
                    indices.append(idx)
            continue
        try:
            idx = int(part) - 1
        except ValueError:
            continue
        if 0 <= idx < max_index and idx not in indices:
            indices.append(idx)
    return indices
