"""Print which of the given names are set. Never print values."""
import os
import sys

args = sys.argv[1:]
if "--check-foo" in args:
    raise SystemExit(0 if os.environ.get("FOO") == "from-process" else 3)
names = [arg for arg in args if not arg.startswith("--")]
set_names = [name for name in names if os.environ.get(name, "").strip()]
print("SET " + " ".join(set_names), flush=True)
