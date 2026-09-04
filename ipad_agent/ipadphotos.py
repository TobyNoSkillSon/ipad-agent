"""Semantic Photos commands."""
from __future__ import annotations
from typing import Any

def ipadphotos(command: object, *args: object, **options: object) -> Any:
    from integrations.photos.commands import photos
    return photos(command, *args, **options)

__all__ = ["ipadphotos"]
