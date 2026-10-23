"""Fixture whose import fails, like a script with a missing logger package."""
from helper_scripts.utils.logger_missing import setup_logger  # noqa: F401

if __name__ == "__main__":
    raise SystemExit("smoke_import must not run __main__")
