"""Environment settings for the grocery price sync."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
STORAGE_STATE_PATH = PACKAGE_DIR / ".shoprite_storage.json"


class ConfigError(Exception):
    """Raised when required grocery settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    service_role_key: str
    anon_key: str
    shoprite_zip: str
    timeout_ms: int
    min_delay_s: float
    batch_size: int
    storage_state_path: Path


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < 1:
        return default
    return value


def _delay_seconds() -> float:
    raw = os.getenv("GROCERY_MIN_DELAY_SECONDS", "").strip()
    if not raw:
        return 2.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError("GROCERY_MIN_DELAY_SECONDS must be a number") from exc
    if value < 2:
        return 2.0
    return value


def load_settings(*, require_supabase: bool = False) -> Settings:
    """Load repo-root `.env`. Supabase keys are required only for pull and push."""
    load_dotenv(REPO_ROOT / ".env")
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    anon = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if require_supabase:
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", url),
                ("SUPABASE_SERVICE_ROLE_KEY", service),
                ("SUPABASE_ANON_KEY", anon),
            )
            if not value
        ]
        if missing:
            raise ConfigError("Missing " + ", ".join(missing))
    return Settings(
        supabase_url=url,
        service_role_key=service,
        anon_key=anon,
        shoprite_zip=os.getenv("DEFAULT_SHOPRITE_ZIP", "").strip(),
        timeout_ms=_positive_int("GROCERY_TIMEOUT_MS", 30000),
        min_delay_s=_delay_seconds(),
        batch_size=_positive_int("GROCERY_BATCH_SIZE", 20),
        storage_state_path=STORAGE_STATE_PATH,
    )
