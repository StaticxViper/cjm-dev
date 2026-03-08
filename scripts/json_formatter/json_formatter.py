import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

import json
import os
import sys
from shared.logger import setup_logger

logger = setup_logger(
    name="stock-analyzer",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

def infer_type(value):
    """Convert Python values into simplified type placeholders."""
    if isinstance(value, str):
        return "string"
    elif isinstance(value, bool):
        return "boolean"
    elif isinstance(value, int) or isinstance(value, float):
        return "number"
    elif value is None:
        return "null"
    elif isinstance(value, list):
        if len(value) > 0:
            return [infer_type(value[0])]
        else:
            return []
    elif isinstance(value, dict):
        return {k: infer_type(v) for k, v in value.items()}
    else:
        return "unknown"

def process_json(data):
    """Recursively reduce arrays to one item and convert values to type placeholders."""
    if isinstance(data, dict):
        return {k: process_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        if len(data) > 0:
            return [process_json(data[0])]
        return []
    else:
        return infer_type(data)

def main():
    if len(sys.argv) < 2:
        logger.critical("Usage: python json_formatter.py input.json")
        return

    input_path = sys.argv[1]

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    formatted = process_json(data)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")

    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "formatted_schema.json")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, indent=2)

    logger.critical(f"Formatted JSON saved to: {output_file}")

if __name__ == "__main__":
    main()