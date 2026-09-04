"""Semantic Preview commands."""
from __future__ import annotations

from typing import Any


def ipadpreview(command: object, *args: object, **options: object) -> Any:
    """Open Preview, drop a local file, or hand off a transferred file."""
    from integrations.preview.commands import preview

    return preview(command, *args, **options)


__all__ = ["ipadpreview"]
