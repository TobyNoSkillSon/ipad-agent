"""Semantic Books commands."""
from __future__ import annotations

from typing import Any


def ipadbooks(command: object, *args: object, **options: object) -> Any:
    """Open Books, drop a local file, or hand off a transferred file."""
    from .commands import books

    return books(command, *args, **options)


__all__ = ["ipadbooks"]
