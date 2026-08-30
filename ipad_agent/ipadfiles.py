"""Semantic Files commands."""
from __future__ import annotations

from typing import Any


def ipadfiles(command: object, *args: object, **options: object) -> Any:
    """Open Files, drop a local file, or hand off a transferred file."""
    from .commands import files

    return files(command, *args, **options)


__all__ = ["ipadfiles"]
