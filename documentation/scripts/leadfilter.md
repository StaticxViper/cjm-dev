# Lead Filter

**Source:** `scripts/lead_automation/leadfilter.py`

## Purpose

Library module for thread-safe duplicate filtering during lead generation. Prevents re-exporting leads that already exist in a previous JSON run.

Primary key remains Google `place_id`. Playwright discovery also uses broader identity keys (`profile_url`, normalized name+phone, name+address) so browser-sourced leads dedupe against prior runs even when a Places API id is missing.

## Prerequisites

None beyond Python stdlib. Imported by [leadgen](leadgen.md); not run as a standalone script.

## Configuration

No config files. The caller passes the JSON path (typically `leads_output.json`).

## How to run

Not a CLI. Import in Python:

```python
from leadfilter import load_existing_place_ids, is_new_place, load_existing_identities, is_new_identity

existing = load_existing_place_ids("leads_output.json")
if is_new_place(place_id, existing):
    # process new lead

identities = load_existing_identities("leads_output.json")
if is_new_identity(lead_row, identities):
    # process new lead (multi-key)
```

Run leadgen from `scripts/lead_automation/` so the relative import resolves.

## API

### `load_existing_place_ids(json_path: str) -> set`

Loads all `place_id` values from an existing JSON leads array. Returns an empty set if the file does not exist or is invalid.

### `is_new_place(place_id: str, existing_ids: set) -> bool`

Thread-safe check-and-insert. Returns `True` if the `place_id` was not seen before; adds it to the set on first sight.

### `load_existing_identities(json_path: str) -> set`

Loads identity tuples from prior leads: `place_id`, `profile_url`, `name_phone`, and `name_address`.

### `is_new_identity(entry, existing_identities: set) -> bool`

Thread-safe multi-key check-and-insert used by the Playwright path.

## Related scripts

- [leadgen.md](leadgen.md) — primary consumer
