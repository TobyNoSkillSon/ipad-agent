"""Compatibility alias for :mod:`ipad_agent.core.config`."""
import importlib as _importlib
import sys as _sys

_module = _importlib.import_module("ipad_agent.core.config")
_sys.modules[__name__] = _module
