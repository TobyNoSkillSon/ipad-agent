"""Compatibility alias for :mod:`ipad_agent.core.results`."""
import importlib as _importlib
import sys as _sys

_module = _importlib.import_module("ipad_agent.core.results")
_sys.modules[__name__] = _module
