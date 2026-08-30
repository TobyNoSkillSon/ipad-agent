"""Device-wide semantic commands."""
from __future__ import annotations

from typing import Any


def ipadc(command: object, *args: object, **options: object) -> Any:
    """Open an app, drop a local file, or report runtime status."""
    from .commands import controller

    return controller(command, *args, **options)


__all__ = ["ipadc"]
