"""
This script processes large JSON files and converts them into a compact structural representation 
that is easier to use as context for AI tools or documentation. It recursively analyzes the JSON data, 
replaces actual values with their data types (such as "string", "number", "boolean", etc.), and reduces arrays 
to a single example element while preserving the overall structure. 

This dramatically reduces file size while keeping the schema of the data intact. 
The formatted result is then saved as a new JSON file in the output directory located in the same folder as the script.
"""
import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import json
import os
from helper_scripts.utilities.logger import setup_logger

logger = setup_logger(
    name="json-formatter",
    console_levels=["ERROR", "CRITICAL"]
)


def extract_keys(data):
    """
    Recursively remove values and keep only JSON keys.
    Arrays are reduced to a single structural example.
    """

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            result[key] = extract_keys(value)
        return result

    elif isinstance(data, list):
        if len(data) == 0:
            return {}
        return extract_keys(data[0])

    else:
        # Primitive values (string, number, bool, null)
        return {}


def main():
    if len(sys.argv) < 2:
        logger.critical("Usage: python json_formatter.py input.json")
        return

    input_path = sys.argv[1]

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    formatted = extract_keys(data)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "output")

    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "json_structure.json")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, indent=2)

    logger.critical(f"Formatted JSON saved to: {output_file}")


if __name__ == "__main__":
    main()