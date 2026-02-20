import logging
import sys
from pathlib import Path
from datetime import datetime

# ---- GLOBAL LOG FILE (created once per execution) ----
_LOG_FILE = None


def _get_log_file(class_name: str) -> Path:
    global _LOG_FILE

    if _LOG_FILE is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        filename = f"{timestamp}_{class_name}.log"
        _LOG_FILE = log_dir / filename

    return _LOG_FILE


# ---- COLOR CONFIG ----
COLORS = {
    "INFO": "\033[94m",
    "ERROR": "\033[91m",
    "CRITICAL": "\033[95m",
}
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    def format(self, record):
        original_levelname = record.levelname

        if original_levelname in COLORS:
            record.levelname = (
                f"{COLORS[original_levelname]}"
                f"{original_levelname}"
                f"{RESET}"
            )

        formatted = super().format(record)
        record.levelname = original_levelname
        return formatted


def setup_logger(name: str, console_levels=None):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger  # Prevent duplicate handlers

    # ---- FILE HANDLER ----
    log_file_path = _get_log_file(name)

    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.DEBUG)

    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    file_handler.setFormatter(file_format)

    # ---- CONSOLE HANDLER ----
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    console_format = ColorFormatter(
        "%(asctime)s | %(levelname)-8s | %(message)s"
    )
    console_handler.setFormatter(console_format)

    if console_levels:
        console_levels = [lvl.upper() for lvl in console_levels]

        class ConsoleFilter(logging.Filter):
            def filter(self, record):
                return record.levelname in console_levels

        console_handler.addFilter(ConsoleFilter())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger