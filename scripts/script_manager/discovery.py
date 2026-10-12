"""Find Python files with a ``__main__`` block that the registry does not name."""

from __future__ import annotations

import re
from pathlib import Path

_MAIN_RE = re.compile(r"""(?m)^\s*if\s+__name__\s*==\s*['"]__main__['"]\s*:""")


def glob_match(path: str, pattern: str) -> bool:
    """Match a repo-relative posix path against a glob that may contain ``**``."""
    regex = ["^"]
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            regex.append(".*")
            i += 2
            continue
        char = pattern[i]
        if char == "*":
            regex.append("[^/]*")
        else:
            regex.append(re.escape(char))
        i += 1
    regex.append("$")
    return re.fullmatch("".join(regex), path) is not None


def is_ignored(rel_posix: str, patterns: list[str]) -> bool:
    return any(glob_match(rel_posix, pattern) for pattern in patterns)


def unregistered_scripts(repo: Path, ignore_paths: list[str], registered: set[Path]) -> list[Path]:
    """Return ``__main__`` files under scripts/ and helper_scripts/ that are not registered."""
    registered_resolved = {path.resolve() for path in registered}
    found: list[Path] = []
    for root_name in ("scripts", "helper_scripts"):
        root = repo / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            rel = path.relative_to(repo).as_posix()
            if is_ignored(rel, ignore_paths):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not _MAIN_RE.search(text):
                continue
            if path.resolve() not in registered_resolved:
                found.append(path)
    found.sort(key=lambda item: item.as_posix().lower())
    return found
