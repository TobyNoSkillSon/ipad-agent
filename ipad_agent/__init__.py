"""Semantic control of a paired physical iPad from macOS.

Importing this package is inert. The named semantic functions are the public
root surface. Legacy compact control is available only from
:mod:`ipad_agent.legacy`.
"""
from __future__ import annotations

from .ipadc import ipadc
from .ipadpreview import ipadpreview
from .ipadbooks import ipadbooks
from .ipadfiles import ipadfiles
from .ipadsettings import ipadsettings
from .ipadclock import ipadclock
from .ipadappstore import ipadappstore
from .ipadbrave import ipadbrave
from .ipadsafari import ipadsafari
from .ipadmaps import ipadmaps


__all__ = [
    "ipadc",
    "ipadpreview",
    "ipadbooks",
    "ipadfiles",
    "ipadsettings",
    "ipadclock",
    "ipadappstore",
    "ipadbrave",
    "ipadsafari",
    "ipadmaps",
    "Config",
    "IPadResult",
]


def __getattr__(name: str):
    if name == "Config":
        from .config import Config

        return Config
    if name == "IPadResult":
        from .api import IPadResult

        return IPadResult
    raise AttributeError(name)


def __dir__() -> list[str]:
    """Expose only the supported root surface to discovery and doc tools."""
    return sorted(__all__)
