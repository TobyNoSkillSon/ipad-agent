"""Compatibility alias for :mod:`ipad_agent.transports.wda`."""
import importlib as _importlib
import sys as _sys

_module = _importlib.import_module("ipad_agent.transports.wda")
_sys.modules[__name__] = _module
