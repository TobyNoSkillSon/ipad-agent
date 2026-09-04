"""Executable Clock semantic commands."""
from __future__ import annotations
from typing import Any
from ipad_agent.core import commands as shared

COMMANDS = ('open',)


def clock(command: object, *args: object, **options: object) -> Any:
    try:
        operation = shared._command(command)
        if args or options:
            raise ValueError(f"{operation} takes no arguments")
        if operation == "open":
            return shared._direct_open("Clock")
        return shared._unsupported(operation, COMMANDS)
    except (TypeError, ValueError, OSError) as error:
        return shared._failed(error)


__all__ = ["clock"]
