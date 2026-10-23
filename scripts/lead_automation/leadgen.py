#!/usr/bin/env python3
"""
leadgen.py

Local Business Lead Generation System.

Run: python leadgen.py

Implementation lives in leadgen_config, places_api, lead_scoring,
lead_pipeline, lead_persistence, and leadgen_cli. Those files are executed
into this module so existing ``from leadgen import ...`` paths and unittest
patches of ``leadgen.*`` keep resolving here.
"""
from pathlib import Path

_LEADGEN_PARTS = (
    "leadgen_config.py",
    "places_api.py",
    "lead_scoring.py",
    "lead_pipeline.py",
    "lead_persistence.py",
    "leadgen_cli.py",
)


def _load_leadgen_parts():
    here = Path(__file__).resolve().parent
    namespace = globals()
    for name in _LEADGEN_PARTS:
        path = here / name
        code = path.read_text(encoding="utf-8")
        exec(compile(code, str(path), "exec"), namespace)


_load_leadgen_parts()

if __name__ == "__main__":
    main()
