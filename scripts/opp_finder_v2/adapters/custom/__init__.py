"""Site-specific hooks used only when sites.json cannot express the parse."""

from __future__ import annotations

_HOOKS = {
    "wwr_title": "opp_finder_v2.adapters.custom.wwr_title",
    "hn_hiring": "opp_finder_v2.adapters.custom.hn_hiring",
}


def get_hook(name: str | None):
    if not name:
        return None
    module_name = _HOOKS.get(name)
    if module_name is None:
        raise KeyError(name)
    import importlib

    return importlib.import_module(module_name)
