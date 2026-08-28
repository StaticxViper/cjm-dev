# Logger

**Source:** `helper_scripts/utils/logger/logger.py`

Duplicate re-export: `helper_scripts/utilities/logger/` (used by `lovable_automation.py`).

## Purpose

Shared logging setup for cjm-dev scripts: colored console output (filtered by level) plus a DEBUG-level file log per process execution.

## Prerequisites

- Python 3.12+ (stdlib `logging` only)

## Configuration

| Setting | Default |
|---------|---------|
| Log directory | `logs/<entry-script>/` at repo root (created at runtime if missing) |
| Log filename | `{timestamp}_{entry-script}.log` |
| Entry script | Taken from `__main__.__file__` (the process that was launched), not the helper that first called `setup_logger` |
| Console colors | INFO (blue), ERROR (red), CRITICAL (magenta) |

## How to run

Library only. Import:

```python
from helper_scripts.utils.logger.logger import setup_logger

logger = setup_logger(
    name="my-script",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)
logger.info("Hello")
```

Alternate import path (lovable_automation):

```python
from helper_scripts.utilities.logger import setup_logger
```

Both resolve to the same `setup_logger` implementation.

## `setup_logger(name, console_levels=None)`

| Parameter | Description |
|-----------|-------------|
| `name` | Logger name (appears in each log line as `%(name)s`; file/folder use the entry-point script) |
| `console_levels` | List of levels shown on console; file always logs DEBUG |

Returns a configured `logging.Logger`. Handlers are not duplicated if the logger already exists.

## Related scripts

All major automation scripts use this module for consistent logging.
