"""Semantic Keynote commands."""
from __future__ import annotations
from typing import Any

def ipadkeynote(command: object, *args: object, **options: object) -> Any:
    from integrations.keynote.commands import keynote
    return keynote(command, *args, **options)

__all__ = ["ipadkeynote"]
