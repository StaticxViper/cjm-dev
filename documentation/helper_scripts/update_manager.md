# Update Manager (legacy)

**Source:** `helper_scripts/utils/update_manager/update_manager.py`

> **Not maintained.** Intended for an old Raspberry Pi deployment. `self.log` and `self.notif` are commented out in `__init__` but still referenced in methods—running `update_raspberry_pi()` or `update()` will raise `AttributeError`.

## Purpose

Originally ran `apt-get update/upgrade` on a Raspberry Pi and logged results to a fixed path on the device. Also supported generic shell update commands with notification hooks.

## Prerequisites

- Linux with `sudo` and `apt-get` (Raspberry Pi only in practice)
- Previously depended on external `LogManager` and `NotificationManager` (not in this repo)

## Configuration

Hardcoded log path: `/home/pi/1.Repos/sxv-projects/docs/logs/update_log.txt`

## How to run

```bash
python helper_scripts/utils/update_manager/update_manager.py
```

**Do not run on Windows or without restoring `LogManager` / `MyClient` integrations.** This entry point calls `update_raspberry_pi()` and will fail.

## API (if restored)

### `update_raspberry_pi()`

Runs `sudo apt-get update` and `sudo apt-get upgrade -y`.

### `update(command, location)`

Runs an arbitrary shell command and writes success/failure to a log file.

## Related scripts

None in active use. Kept for historical reference only.
