"""CLI entry: cd scripts && python -m opp_finder_v2"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/opp_finder_v2/__main__.py -> parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opp_finder_v2.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
