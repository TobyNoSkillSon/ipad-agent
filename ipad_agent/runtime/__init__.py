"""Compatibility alias for the relocated runtime engine."""
from __future__ import annotations

import importlib as _importlib
import sys as _sys

_package_path = __path__
_module = _importlib.import_module(f"{__name__}.engine")
_module.__path__ = _package_path
_module.engine = _module
_sys.modules[__name__] = _module
