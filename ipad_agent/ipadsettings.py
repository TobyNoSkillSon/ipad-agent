"""Semantic Settings commands."""
from __future__ import annotations

from typing import Any


def ipadsettings(command: object, *args: object, **options: object) -> Any:
    """Open Settings or one allowlisted safe destination."""
    from .commands import settings

    return settings(command, *args, **options)


__all__ = ["ipadsettings"]
