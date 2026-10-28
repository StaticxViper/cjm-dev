#!/usr/bin/env python3
"""Read-only Script Manager probe. Prints one JSON object and writes no files."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only CI probe. Prints one JSON object and writes nothing."
    )
    parser.add_argument("args", nargs="*", help="Echoed in the JSON payload. Nothing is read or written.")
    args = parser.parse_args(argv)
    payload = {"ok": True, "script": "ci-ping", "args": args.args}
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
