"""Compatibility facade over :mod:`ipad_agent.core.commands`.

Shared helpers are exposed for historical callers. Application forwards remain
lazy and live outside the shared core implementation.
"""
import importlib as _importlib

_shared = _importlib.import_module("ipad_agent.core.commands")
_forwards = _importlib.import_module("ipad_agent._command_forwards")
for _name in dir(_shared):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_shared, _name)
for _name, _value in _forwards.APPLICATION_FORWARDS.items():
    globals()[_name] = _value

__all__ = [
    "app_store",
    "books",
    "browser",
    "clock",
    "controller",
    "files",
    "maps",
    "preview",
    "settings",
]
