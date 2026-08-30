"""Semantic Maps commands."""
from __future__ import annotations

from typing import Any


def ipadmaps(command: object, *args: object, **options: object) -> Any:
    """Open Maps or show one location."""
    from .commands import maps

    return maps(command, *args, **options)


__all__ = ["ipadmaps"]
