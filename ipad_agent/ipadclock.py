"""Semantic Clock commands."""
from __future__ import annotations

from typing import Any


def ipadclock(command: object, *args: object, **options: object) -> Any:
    """Open Clock."""
    from integrations.clock.commands import clock

    return clock(command, *args, **options)


__all__ = ["ipadclock"]
