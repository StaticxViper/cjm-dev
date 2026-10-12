import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.script_manager.cli import main
if __name__ == "__main__": raise SystemExit(main())
