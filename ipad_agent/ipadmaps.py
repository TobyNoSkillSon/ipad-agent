"""Semantic Maps commands."""
from __future__ import annotations

from typing import Any


def ipadmaps(command: object, *args: object, **options: object) -> Any:
    """Run one declared Apple Unified Maps command."""
    from integrations.apple_maps.commands import maps

    return maps(command, *args, **options)


__all__ = ["ipadmaps"]
