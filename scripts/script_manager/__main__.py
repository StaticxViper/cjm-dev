import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.script_manager.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
