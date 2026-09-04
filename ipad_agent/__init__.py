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
from .ipadgooglemaps import ipadgooglemaps
from .ipadpages import ipadpages
from .ipadnumbers import ipadnumbers
from .ipadkeynote import ipadkeynote
from .ipadphotos import ipadphotos
from .ipadmessages import ipadmessages


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
    "ipadgooglemaps",
    "ipadpages",
    "ipadnumbers",
    "ipadkeynote",
    "ipadphotos",
    "ipadmessages",
    "Config",
    "IPadResult",
]


def __getattr__(name: str):
    if name == "Config":
        from ipad_agent.core.config import Config

        return Config
    if name == "IPadResult":
        from ipad_agent.core.results import IPadResult

        return IPadResult
    raise AttributeError(name)


def __dir__() -> list[str]:
    """Expose only the supported root surface to discovery and doc tools."""
    return sorted(__all__)
