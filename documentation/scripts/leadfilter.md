# Lead Filter

**Source:** `scripts/lead_automation/leadfilter.py`

## Purpose

Library module for thread-safe duplicate filtering during lead generation. Prevents re-exporting leads that already exist in a previous CSV run, keyed by Google `place_id`.

## Prerequisites

None beyond Python stdlib. Imported by [leadgen](leadgen.md); not run as a standalone script.

## Configuration

No config files. The caller passes the CSV path (typically `leads_output.csv`).

## How to run

Not a CLI. Import in Python:

```python
from leadfilter import load_existing_place_ids, is_new_place

existing = load_existing_place_ids("leads_output.csv")
if is_new_place(place_id, existing):
    # process new lead
```

Run leadgen from `scripts/lead_automation/` so the relative import resolves.

## API

### `load_existing_place_ids(csv_path: str) -> set`

Loads all `place_id` values from an existing CSV. Returns an empty set if the file does not exist.

### `is_new_place(place_id: str, existing_ids: set) -> bool`

Thread-safe check-and-insert. Returns `True` if the `place_id` was not seen before; adds it to the set on first sight.

## Related scripts

- [leadgen.md](leadgen.md) — primary consumer
