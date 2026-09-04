"""Shared implementation of the public :func:`ipad_agent.ipadc` command."""
from __future__ import annotations

from typing import Any


def controller(command: object, *args: object, **options: object) -> Any:
    """Open one app, transfer one local file, or report runtime status."""
    from ipad_agent.core import commands as shared

    try:
        operation = shared._command(command)
        if operation == "open":
            if len(args) != 1 or options:
                raise ValueError("open requires exactly one app name")
            return shared._direct_open(shared._text(args[0], "app"))
        if operation == "drop":
            if len(args) != 1 or options:
                raise ValueError("drop requires exactly one local file path")
            return shared._airdrop(args[0])
        if operation == "status":
            if args or options:
                raise ValueError("status takes no arguments")
            return shared._runtime_ip("q")
        return shared._unsupported(operation, ("open", "drop", "status"))
    except (TypeError, ValueError, OSError) as error:
        return shared._failed(error)


__all__ = ["controller"]
