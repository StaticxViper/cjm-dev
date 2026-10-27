"""Re-export the shared Actor runtime. Helpers live in scripts/apify-scripts/runtime.py."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os
import sys


def _load():
    key = "cjm_apify_scripts_runtime"
    loaded = sys.modules.get(key)
    if loaded is not None:
        return loaded
    candidates = [Path(__file__).resolve().parents[2] / "runtime.py"]
    root = os.environ.get("CJM_REPO_ROOT")
    if root:
        candidates.append(Path(root) / "scripts" / "apify-scripts" / "runtime.py")
    for path in candidates:
        if path.is_file():
            spec = spec_from_file_location(key, path)
            module = module_from_spec(spec)
            sys.modules[key] = module
            spec.loader.exec_module(module)
            return module
    raise ImportError("scripts/apify-scripts/runtime.py was not found")


_runtime = _load()
iso_now = _runtime.iso_now
find_repo_root = _runtime.find_repo_root
prepare_imports = _runtime.prepare_imports
fetch_text = _runtime.fetch_text
push_charged_rows = _runtime.push_charged_rows
RESULT_EVENT = _runtime.RESULT_EVENT
USER_AGENT = _runtime.USER_AGENT
for _access_name in _runtime.ACCESS_NAMES:
    globals()[_access_name] = getattr(_runtime, _access_name)
