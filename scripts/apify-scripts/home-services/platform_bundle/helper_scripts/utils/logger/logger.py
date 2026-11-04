import atexit
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import httpx


# ---- PATH SETUP ----
BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[2]  # helper_scripts/utils/logger -> repo root
LOG_DIR = REPO_ROOT / "logs"
LOGS_API_URL = "https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1/logs-api"

# ---- GLOBAL LOG FILE (created once per execution) ----
_LOG_FILE = None
_ATEXIT_REGISTERED = False
_UPLOAD_DONE = False


def _entry_script_name(fallback: str) -> str:
    """Name of the process entry-point script, not a helper that imported the logger."""
    main = sys.modules.get("__main__")
    main_file = getattr(main, "__file__", None)
    if main_file:
        stem = Path(main_file).stem
    elif sys.argv and sys.argv[0] not in ("", "-c", "-"):
        stem = Path(sys.argv[0]).stem
    else:
        stem = fallback
    return stem.replace("_", "-")


def _get_log_file(class_name: str) -> Path:
    global _LOG_FILE

    if _LOG_FILE is None:
        script_name = _entry_script_name(class_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_log_dir = LOG_DIR / script_name
        script_log_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{timestamp}_{script_name}.log"
        _LOG_FILE = script_log_dir / filename

    return _LOG_FILE


def _flush_file_handlers():
    loggers = [logging.getLogger()]
    for name, obj in logging.Logger.manager.loggerDict.items():
        if isinstance(obj, logging.PlaceHolder):
            continue
        loggers.append(logging.getLogger(name))
    for lg in loggers:
        for handler in lg.handlers:
            handler.flush()


def _payload_level(content: str) -> str:
    if " | ERROR" in content or " | CRITICAL" in content:
        return "error"
    if " | WARNING" in content:
        return "warn"
    return "info"


def _upload_log_file():
    """POST the process log file to logs-api when the script exits."""
    global _UPLOAD_DONE
    if _UPLOAD_DONE or _LOG_FILE is None:
        return
    _UPLOAD_DONE = True

    try:
        _flush_file_handlers()
        if not _LOG_FILE.exists():
            return
        content = _LOG_FILE.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            return

        load_dotenv(REPO_ROOT / ".env")
        api_key = os.getenv("MVLLC_LOGS_KEY")
        if not api_key:
            print("Skipping log upload: MVLLC_LOGS_KEY is not set", file=sys.stderr)
            return

        script_name = _LOG_FILE.parent.name
        payload = {
            "source": script_name,
            "level": _payload_level(content),
            "event_type": "script_complete",
            "message": content,
            "actor": script_name,
            "metadata": {
                "filename": _LOG_FILE.name,
                "script": script_name,
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = httpx.post(LOGS_API_URL, headers=headers, json=payload, timeout=60.0)
        response.raise_for_status()
        print(f"Uploaded log to logs-api ({_LOG_FILE.name})", file=sys.stderr)
    except Exception as exc:
        print(f"Failed to upload log to logs-api: {exc}", file=sys.stderr)


def _register_log_upload():
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    atexit.register(_upload_log_file)
    _ATEXIT_REGISTERED = True

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

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
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
    _register_log_upload()

    return logger
