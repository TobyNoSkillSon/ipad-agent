"""CoreDevice/AirDrop Pages commands with app-owned file authority."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any
from ipad_agent.core import commands as shared

COMMANDS = ("open", "drop", "show")
_DIRECTORY = Path(__file__).parent
_EXTENSIONS = ('.pages', '.doc', '.docx', '.rtf', '.txt')
_COMPATIBILITY = _DIRECTORY / "route-compatibility.json"

def _load_authority() -> dict[str, dict[str, object]]:
    data = json.loads((_DIRECTORY / "file-authority.json").read_text(encoding="utf-8"))
    if data.get("schema") != "ipad-agent.pages-file-authority/v1" or tuple(data.get("extensions", ())) != _EXTENSIONS:
        raise ValueError("Pages file authority is invalid")
    routes = json.loads(_COMPATIBILITY.read_text(encoding="utf-8")).get("commands")
    if not isinstance(routes, list) or [item.get("command") for item in routes if isinstance(item, dict)] != list(COMMANDS):
        raise ValueError("Pages compatibility authority is invalid")
    return {str(item["command"]): item for item in routes}

def _validated_file(value: object) -> object:
    _load_authority()
    try: text = os.fspath(value)
    except TypeError as error: raise ValueError("Pages file must be one local path") from error
    if not isinstance(text, str) or not text or "\x00" in text:
        raise ValueError("Pages file must be one non-empty local path")
    if not any(Path(text).name.casefold().endswith(extension) for extension in _EXTENSIONS):
        raise ValueError("Pages file extension is not admitted")
    return value

def pages(command: object, *args: object, **options: object) -> Any:
    try:
        operation = shared._command(command)
        route = _load_authority().get(operation)
        if route is None: return shared._unsupported(operation, COMMANDS)
        if operation == "open":
            if route.get("availability") != "proven" or route.get("production") != "admitted": raise ValueError("Pages open is candidate-gated on this profile")
            if args or options: raise ValueError("open takes no arguments")
            return shared._direct_open("Pages")
        if len(args) != 1 or options: raise ValueError(f"{operation} requires exactly one local file path")
        path = _validated_file(args[0])
        return shared._airdrop(path) if operation == "drop" else shared._show_local("Pages", path)
    except (TypeError, ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        return shared._failed(error)

__all__ = ["pages"]
