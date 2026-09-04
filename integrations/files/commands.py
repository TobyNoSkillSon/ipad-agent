"""Executable Files semantic commands."""
from __future__ import annotations

from typing import Any

from ipad_agent.core import commands as shared


COMMANDS = ("open", "drop", "show")


def files(command: object, *args: object, **options: object) -> Any:
    """Open Files, transfer one local file, or request a file handoff."""
    try:
        operation = shared._command(command)
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return shared._direct_open("Files")
        if operation == "drop":
            if len(args) != 1 or options:
                raise ValueError("drop requires exactly one local file path")
            return shared._airdrop(args[0])
        if operation == "show":
            if len(args) != 1 or options:
                raise ValueError("show requires exactly one local file path")
            return shared._show_local("Files", args[0])
        return shared._unsupported(operation, COMMANDS)
    except (TypeError, ValueError, OSError) as error:
        return shared._failed(error)


__all__ = ["files"]
