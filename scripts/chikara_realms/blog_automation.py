import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

from shared.api_manager import APIManager as api
from shared.logger import setup_logger

logger = setup_logger(
    name="stock-analyzer",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)


def main():
    pass


if __name__ == "__main__":
    main()
