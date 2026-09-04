"""CoreDevice-only App Store product navigation."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ipad_agent.core import commands as shared

COMMANDS = ("open", "show")
_PRODUCT_ID = re.compile(r"(?:id)?([1-9][0-9]{4,19})", re.IGNORECASE)
_PRODUCT_PATH = re.compile(r"(?:/[a-z]{2})?/app(?:/[a-z0-9](?:[a-z0-9-]{0,198}))?/id([1-9][0-9]{4,19})")


def _product_url(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("product must be an App Store URL or positive product ID")
    if isinstance(value, int):
        raw = str(value)
    elif isinstance(value, str):
        raw = value
    else:
        raise ValueError("product must be an App Store URL or positive product ID")
    identifier = _PRODUCT_ID.fullmatch(raw)
    if identifier is not None:
        return f"https://apps.apple.com/app/id{identifier.group(1)}"
    if not raw or raw != raw.strip() or len(raw.encode("utf-8")) > 2048 or "\\" in raw:
        raise ValueError("App Store product URL is invalid")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"App Store product URL is invalid: {error}") from error
    if parsed.scheme != "https" or parsed.netloc != "apps.apple.com" or parsed.hostname != "apps.apple.com" or parsed.username is not None or parsed.password is not None or port is not None or parsed.query or parsed.fragment:
        raise ValueError("App Store URL must use the exact apps.apple.com product authority")
    if _PRODUCT_PATH.fullmatch(parsed.path) is None:
        raise ValueError("App Store URL must be a canonical app product path")
    return raw


def app_store(command: object, *args: object, **options: object) -> Any:
    try:
        operation = shared._command(command)
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return shared._direct_open("App Store")
        if operation == "show":
            if len(args) != 1 or options:
                raise ValueError("show requires exactly one App Store URL or product ID")
            url = _product_url(args[0])
            if _product_url(url) != url:
                raise ValueError("App Store product route changed during validation")
            return shared._direct_open("App Store", url)
        return shared._unsupported(operation, COMMANDS)
    except (TypeError, ValueError, OSError) as error:
        return shared._failed(error)


__all__ = ["app_store"]
