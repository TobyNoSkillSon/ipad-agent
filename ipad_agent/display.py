"""Historical alias for :mod:`ipad_agent.legacy.display`."""
import importlib as _importlib
import sys as _sys

_module = _importlib.import_module("ipad_agent.legacy.display")
_sys.modules[__name__] = _module
