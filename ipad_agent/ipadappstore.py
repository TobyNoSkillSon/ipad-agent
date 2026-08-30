"""Semantic App Store commands."""
from __future__ import annotations

from typing import Any


def ipadappstore(command: object, *args: object, **options: object) -> Any:
    """Open App Store or show one validated product destination."""
    from .commands import app_store

    return app_store(command, *args, **options)


__all__ = ["ipadappstore"]
