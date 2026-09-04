"""Prepare-only Apple Messages commands."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from ipad_agent.core import commands as shared

COMMANDS = ("open", "compose", "prepare")
_DIRECTORY = Path(__file__).parent
_COMPATIBILITY = _DIRECTORY / "route-compatibility.json"
_NUMBER_RE = re.compile(r"\+?[0-9](?:[0-9.-]{0,30}[0-9])?")


def _load_authority() -> dict[str, dict[str, object]]:
    data = json.loads(_COMPATIBILITY.read_text(encoding="utf-8"))
    if data.get("schema") != "ipad-agent.messages-route-compatibility/v1" or data.get("version") != 1:
        raise ValueError("Messages compatibility authority is invalid")
    routes = data.get("commands")
    if not isinstance(routes, list) or [item.get("command") for item in routes if isinstance(item, dict)] != list(COMMANDS):
        raise ValueError("Messages command authority is invalid")
    indexed = {str(item["command"]): item for item in routes}
    for name, route in indexed.items():
        if route.get("availability") not in {"candidate", "proven", "incompatible"} or route.get("production") not in {"candidate-gated", "admitted"}:
            raise ValueError(f"Messages route {name} status is invalid")
        if route["production"] == "admitted" and route["availability"] != "proven":
            raise ValueError(f"Messages route {name} lacks proof")
    return indexed


def _sms_url(recipient: object | None = None) -> str:
    if recipient is None:
        return "sms:"
    if not isinstance(recipient, str) or recipient != recipient.strip() or _NUMBER_RE.fullmatch(recipient) is None:
        raise ValueError("Messages recipient must use only a leading plus, digits, hyphens, and periods")
    return f"sms:{recipient}"



def messages(command: object, *args: object, **options: object) -> Any:
    try:
        operation = shared._command(command)
        route = _load_authority().get(operation)
        if route is None:
            return shared._unsupported(operation, COMMANDS)
        if route["availability"] != "proven" or route["production"] != "admitted":
            raise ValueError(f"Messages route {operation!r} is {route['availability']} on this profile")
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return shared._direct_open("Messages")
        if operation == "compose":
            if args or options:
                raise ValueError("compose takes no arguments")
            return shared._direct_open("Messages", _sms_url())
        if operation == "prepare":
            if len(args) != 1 or options:
                raise ValueError("prepare requires exactly one caller-supplied recipient")
            return shared._direct_open("Messages", _sms_url(args[0]))
        raise ValueError("Messages route is not admitted")
    except (TypeError, ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        return shared._failed(error)


__all__ = ["messages"]
