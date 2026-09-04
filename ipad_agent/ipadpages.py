"""Semantic Pages commands."""
from __future__ import annotations
from typing import Any

def ipadpages(command: object, *args: object, **options: object) -> Any:
    from integrations.pages.commands import pages
    return pages(command, *args, **options)

__all__ = ["ipadpages"]
