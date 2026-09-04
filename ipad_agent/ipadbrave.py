"""Semantic Brave commands."""
from __future__ import annotations

from typing import Any


def ipadbrave(command: object, *args: object, **options: object) -> Any:
    """Open Brave or deliver one explicit website or YouTube URL."""
    from integrations.brave.commands import brave

    return brave(command, *args, **options)


__all__ = ["ipadbrave"]
