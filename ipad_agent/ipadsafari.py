"""Semantic Safari commands."""
from __future__ import annotations

from typing import Any


def ipadsafari(command: object, *args: object, **options: object) -> Any:
    """Open Safari or deliver one explicit website or YouTube URL."""
    from .commands import browser

    return browser("Safari", command, *args, **options)


__all__ = ["ipadsafari"]
