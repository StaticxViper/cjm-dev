# JSON formatter

Shrinks a JSON document to a structural schema: keys are kept, scalar values become empty objects, and each array keeps one example element.

**Inputs:** a JSON file path. **Outputs:** `output/json_structure.json` (the directory is created on run).

**Local run** from this directory:

```bash
python json_formatter.py path/to/input.json
```

**Script Manager:** `json-formatter` (registry status broken). `python -m scripts.script_manager run json-formatter`. No GitHub Actions workflow.

**Secrets:** none.

Longer guide: [documentation/scripts/json_formatter.md](../../documentation/scripts/json_formatter.md).
