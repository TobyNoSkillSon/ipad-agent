"""Compatibility alias and executable for :mod:`ipad_agent.runtime.daemon`."""
import importlib as _importlib
import sys as _sys

_is_main = __name__ == "__main__"
_module = _importlib.import_module("ipad_agent.runtime.daemon")
_sys.modules[__name__] = _module

if _is_main:
    raise SystemExit(_module.main())
