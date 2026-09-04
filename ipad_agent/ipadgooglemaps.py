"""Semantic Google Maps commands."""
from __future__ import annotations
from typing import Any


def ipadgooglemaps(command: object, *args: object, **options: object) -> Any:
    """Run one declared Google Maps command."""
    from integrations.google_maps.commands import google_maps
    return google_maps(command, *args, **options)


__all__ = ["ipadgooglemaps"]
