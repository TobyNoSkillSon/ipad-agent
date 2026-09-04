"""Semantic Messages commands."""
from __future__ import annotations
from typing import Any

def ipadmessages(command: object, *args: object, **options: object) -> Any:
    from integrations.messages.commands import messages
    return messages(command, *args, **options)

__all__ = ["ipadmessages"]
