"""Run repository scripts without remembering each folder, env file, or flag set."""

from pathlib import Path

__version__ = "1"

# unittest discover -s unittests imports this package as ``script_manager`` once
# another test has put ``scripts/`` on sys.path. Keep the test modules visible.
_TEST_DIR = Path(__file__).resolve().parents[2] / "unittests" / "script_manager"
if _TEST_DIR.is_dir():
    _test_path = str(_TEST_DIR)
    if _test_path not in __path__:
        __path__.append(_test_path)


def repo_root() -> Path:
    """Repository root derived from this package, not the caller's working directory."""
    return Path(__file__).resolve().parents[2]
