"""Shared Actor helpers. Actor folders re-export this module from src/runtime.py."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging
import os
import sys

# Same Chrome UA the local Playwright scrapers already send. robots.txt is
# evaluated for User-agent: *, which is the group this UA falls into.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

RESULT_EVENT = "result"


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def find_repo_root():
    """Repo root locally, or CJM_REPO_ROOT inside the Actor image."""
    env = os.environ.get("CJM_REPO_ROOT")
    if env:
        root = Path(env)
        if (root / "helper_scripts").is_dir() and (root / "scripts").is_dir():
            return root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "helper_scripts").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not find the repo root. Set CJM_REPO_ROOT.")


def prepare_imports():
    """Put the repo, city-data CLI, and lead_automation CLI on sys.path."""
    import sys

    root = find_repo_root()
    for path in (
        root,
        root / "scripts" / "city_data",
        root / "scripts" / "lead_automation",
    ):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    return root


def fetch_text(url, attempts=3, timeout=20):
    """GET a text URL. Retries 429 and 5xx with jittered backoff.

    Navigation retries for the scrapers stay inside the existing Playwright
    sessions. This helper is for robots.txt and similar short HTTP reads.
    The repo root is added here because Actors call this before prepare_imports().
    """
    import sys

    root = str(find_repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    from helper_scripts.http.client import fetch_url_text

    return fetch_url_text(
        url,
        attempts=attempts,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )


async def push_charged_rows(rows, billable, event_name=None, ledger=None):
    """Push every row. Charge ``event_name`` only when ``billable(row)`` is true.

    Pay per event, not pay per dataset item. The default event is ``result``
    so existing Actors keep their Console event. A caller can pass another
    primary event, such as ``license``. Misses, blocks, and errors stay in
    the dataset and are not billed. When ``ledger`` is set, a row that would
    pass maxSpendUsd is saved and not billed. An unknown event name is a
    warning on the platform until Console pricing defines it.
    """
    from apify import Actor

    charge_as = event_name or RESULT_EVENT
    log = logging.getLogger("apify")
    capped = False
    for row in rows or []:
        await Actor.push_data(row)
        if capped or not billable(row):
            continue
        if ledger is not None and not ledger.can(charge_as):
            capped = True
            log.critical(
                "%s spend cap reached. Later rows are saved and are not billed.",
                charge_as,
            )
            continue
        if ledger is not None:
            ledger.commit(charge_as)
        result = await Actor.charge(event_name=charge_as)
        if getattr(result, "event_charge_limit_reached", False):
            capped = True
            log.critical(
                "%s charge limit reached. Later rows are saved and are not billed.",
                charge_as,
            )


def _load_access():
    """Load scripts/apify-scripts/access.py beside this file."""
    key = "cjm_apify_scripts_access"
    loaded = sys.modules.get(key)
    if loaded is not None:
        return loaded
    path = Path(__file__).resolve().with_name("access.py")
    if not path.is_file():
        raise ImportError("scripts/apify-scripts/access.py was not found")
    import importlib.util

    spec = importlib.util.spec_from_file_location(key, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


_access = _load_access()
ACCESS_NAMES = _access.ACCESS_NAMES
for _access_name in ACCESS_NAMES:
    globals()[_access_name] = getattr(_access, _access_name)
