#!/usr/bin/env python3
"""Compatibility alias and executable for :mod:`ipad_agent.runtime.server`."""
import importlib as _importlib
from pathlib import Path as _Path
import sys as _sys

_is_main = __name__ == "__main__"
if _is_main and __package__ in {None, ""}:
    _root = str(_Path(__file__).resolve().parents[1])
    if _root not in _sys.path:
        _sys.path.insert(0, _root)

_module = _importlib.import_module("ipad_agent.runtime.server")
_sys.modules[__name__] = _module

if _is_main:
    raise SystemExit(_module.main())
