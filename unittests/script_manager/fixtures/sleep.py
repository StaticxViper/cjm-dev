"""Sleep, optionally leaving a grandchild in the same process tree."""
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args and args[0] == "--grandchild":
    time.sleep(float(args[1]))
    raise SystemExit(0)

seconds = float(args[0])
if "--child-pid-file" in args:
    index = args.index("--child-pid-file")
    pid_path = Path(args[index + 1])
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--grandchild", "120"])
    pid_path.write_text(str(proc.pid), encoding="utf-8")
time.sleep(seconds)
