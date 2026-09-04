"""Semantic Numbers commands."""
from __future__ import annotations
from typing import Any

def ipadnumbers(command: object, *args: object, **options: object) -> Any:
    from integrations.numbers.commands import numbers
    return numbers(command, *args, **options)

__all__ = ["ipadnumbers"]
