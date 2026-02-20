import logging
import sys

# ANSI color codes
COLORS = {
    "INFO": "\033[94m",       # Blue
    "ERROR": "\033[91m",      # Red
    "CRITICAL": "\033[95m",   # Light Purple
    "RESET": "\033[0m"
}


class ColorFormatter(logging.Formatter):
    def format(self, record):
        levelname = record.levelname
        color = COLORS.get(levelname, "")
        reset = COLORS["RESET"]
        message = super().format(record)
        return f"{color}{message}{reset}"


def setup_logger(name: str, console_levels=None):
    """
    console_levels: list of level names to show in console
                    e.g. ["INFO", "ERROR"]
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Capture everything

    # Prevent duplicate logs if called multiple times
    if logger.handlers:
        return logger

    # ---- FILE HANDLER (logs everything) ----
    file_handler = logging.FileHandler("app.log")
    file_handler.setLevel(logging.DEBUG)

    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    file_handler.setFormatter(file_format)

    # ---- CONSOLE HANDLER (filtered + colored) ----
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    console_format = ColorFormatter(
        "%(levelname)s | %(message)s"
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