# JSON Formatter

**Source:** `scripts/json_formatter/json_formatter.py`

## Purpose

Shrinks large JSON files into a compact structural schema for AI tools or documentation. Recursively keeps keys only, replaces primitive values with empty objects, and reduces arrays to a single example element.

## Prerequisites

- Python 3.12+
- No API keys required

## Configuration

| Path | Description |
|------|-------------|
| Input | Any JSON file passed as CLI argument |
| Output | `scripts/json_formatter/output/json_structure.json` (auto-created) |

## How to run

```bash
cd scripts/json_formatter
python json_formatter.py input.json
```

Replace `input.json` with your file path (relative or absolute).

## How it works

1. Load input JSON from argv.
2. Recursively walk the structure via `extract_keys()`.
3. For dicts: preserve keys, recurse on values.
4. For lists: use only the first element as the structural sample.
5. For primitives: emit `{}`.
6. Write formatted result to `output/json_structure.json`.

## Related scripts

None. Standalone utility.
