#!/usr/bin/env python3
"""Script Manager entry. Starts the Actor with APIFY_TOKEN and downloads the dataset."""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from remote import main

if __name__ == "__main__":
    sys.exit(main())
