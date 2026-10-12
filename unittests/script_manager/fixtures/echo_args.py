"""Print argv, cwd, and PYTHONPATH. Optionally touch a file."""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if "--touch" in args:
    index = args.index("--touch")
    Path(args[index + 1]).write_text("touched", encoding="utf-8")
print(
    "ECHO "
    + json.dumps(
        {
            "argv": args,
            "cwd": os.getcwd(),
            "pythonpath": os.environ.get("PYTHONPATH", ""),
        }
    ),
    flush=True,
)
