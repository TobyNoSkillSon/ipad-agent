"""Explicit compatibility surface for compact iPad control.

Use the semantic functions exported by :mod:`ipad_agent` for new code. Importing
this module is inert; configuration and the integration registry load on the
first legacy command call.
"""
from __future__ import annotations

import threading
from typing import Any

_context_lock = threading.Lock()
_context: tuple[Any, Any] | None = None
_context_error: str | None = None
_context_loaded = False


def _load_context() -> tuple[Any, Any] | None:
    global _context, _context_error, _context_loaded
    if _context_loaded:
        return _context
    with _context_lock:
        if _context_loaded:
            return _context
        try:
            from .config import load_config
            from .registry import load_registry

            config = load_config()
            registry = load_registry(enabled_addons=config.enabled_addons)
            # Preserve the original strict boundary for a configured browser.
            try:
                registry.resolve(config.browser)
            except KeyError as error:
                from .registry import AddonNotEnabledError, normalize_name

                if isinstance(error, AddonNotEnabledError):
                    raise
                aliases = {
                    normalize_name(name): bundle
                    for name, bundle in config.bundle_aliases.items()
                }
                if normalize_name(config.browser) not in aliases:
                    raise
            _context = (config, registry)
        except Exception as error:
            _context_error = " ".join(str(error).split()) or error.__class__.__name__
            _context = None
        _context_loaded = True
    return _context


def _configuration_failure():
    from .api import IPadResult

    return IPadResult({"ok": False, "error": f"invalid configuration: {_context_error}"})


def ipad(*args: object, **options: object):
    context = _load_context()
    if context is None:
        return _configuration_failure()
    from .api import ipad as execute

    config, registry = context
    return execute(*args, config=config, registry=registry, **options)


def show(*args: object, **options: object):
    context = _load_context()
    if context is None:
        return _configuration_failure()
    from .api import show as display

    config, registry = context
    return display(*args, config=config, registry=registry, **options)


ip = ipad
sh = show

__all__ = ["ip", "ipad", "sh", "show"]
