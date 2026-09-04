"""CoreDevice/AirDrop Books commands with app-owned route and file authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from ipad_agent.core import commands as shared

COMMANDS = ("open", "drop", "show", "item")
_DIRECTORY = Path(__file__).parent
_COMPATIBILITY_PATH = _DIRECTORY / "route-compatibility.json"
_FILE_AUTHORITY_PATH = _DIRECTORY / "file-authority.json"
_PROFILE_REF = "device-profiles/ipad17-1-j817ap-books-12.5-ipados-26.6.1-23g83.json"
_ALLOWED_FILE_EXTENSIONS = (".epub", ".pdf")
_ITEM_PATH_RE = re.compile(r"/[a-z]{2}/(?:book|audiobook)/[a-z0-9](?:[a-z0-9-]{0,198})/id([1-9][0-9]{4,19})")
_ASSET_ID_RE = re.compile(r"[1-9][0-9]{4,19}")
_CANONICAL_ASSET_ROUTE_RE = re.compile(r"ibooks://assetid/[1-9][0-9]{4,19}")


def _load_authority() -> dict[str, dict[str, object]]:
    data = json.loads(_COMPATIBILITY_PATH.read_text(encoding="utf-8"))
    if data.get("schema") != "ipad-agent.books-route-compatibility/v1" or data.get("version") != 1 or data.get("profile") != _PROFILE_REF:
        raise ValueError("Books route compatibility identity is invalid")
    routes = data.get("commands")
    if not isinstance(routes, list) or [item.get("command") for item in routes if isinstance(item, dict)] != list(COMMANDS):
        raise ValueError("Books route compatibility commands are invalid")
    indexed = {str(item["command"]): item for item in routes}
    expected = {"open": ("proven", "admitted"), "drop": ("candidate", "legacy-admitted"), "show": ("proven", "admitted"), "item": ("proven", "admitted")}
    if {name: (route.get("availability"), route.get("production")) for name, route in indexed.items()} != expected:
        raise ValueError("Books route compatibility status is invalid")
    return indexed


def _load_file_authority() -> None:
    data = json.loads(_FILE_AUTHORITY_PATH.read_text(encoding="utf-8"))
    if data.get("schema") != "ipad-agent.books-file-authority/v1" or tuple(data.get("extensions", ())) != _ALLOWED_FILE_EXTENSIONS:
        raise ValueError("Books file authority is invalid")


def _validated_books_file(value: object) -> object:
    _load_file_authority()
    try:
        text = os.fspath(value)
    except TypeError as error:
        raise ValueError("Books file must be one local path") from error
    if not isinstance(text, str) or not text or "\x00" in text:
        raise ValueError("Books file must be one non-empty local path")
    if not any(Path(text).name.casefold().endswith(extension) for extension in _ALLOWED_FILE_EXTENSIONS):
        raise ValueError("Books accepts EPUB or PDF files only")
    return value


def _canonical_item(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("Books item must be an Apple Books URL or numeric asset ID")
    if isinstance(value, int):
        raw = str(value)
    elif isinstance(value, str):
        raw = value
    else:
        raise ValueError("Books item must be an Apple Books URL or numeric asset ID")
    if _ASSET_ID_RE.fullmatch(raw):
        return f"ibooks://assetid/{raw}"
    if not raw or raw != raw.strip() or len(raw.encode("utf-8")) > 2048 or "\\" in raw:
        raise ValueError("Apple Books item URL is invalid")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"Apple Books item URL is invalid: {error}") from error
    if parsed.scheme != "https" or parsed.hostname != "books.apple.com" or parsed.username is not None or parsed.password is not None or port is not None or parsed.query or parsed.fragment:
        raise ValueError("Apple Books item URL must use the exact books.apple.com product authority")
    if parsed.netloc != "books.apple.com" or _ITEM_PATH_RE.fullmatch(parsed.path) is None:
        raise ValueError("Apple Books item URL path is not a canonical book or audiobook product")
    return raw


def _policy_url(url: str) -> str:
    """Revalidate the complete adapter-owned route immediately before dispatch."""
    if not isinstance(url, str):
        raise ValueError("Books item route must be a string")
    if _CANONICAL_ASSET_ROUTE_RE.fullmatch(url):
        return url
    canonical = _canonical_item(url)
    if canonical != url:
        raise ValueError("Books item route changed during canonical validation")
    return canonical



def books(command: object, *args: object, **options: object) -> Any:
    """Open Books, transfer EPUB/PDF, or open one proven Apple Books product."""
    try:
        operation = shared._command(command)
        route = _load_authority().get(operation)
        if route is None:
            return shared._unsupported(operation, COMMANDS)
        if route["production"] == "candidate-gated":
            raise ValueError(f"Books route {operation!r} is candidate-gated on this profile")
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return shared._direct_open("Books")
        if operation in {"drop", "show"}:
            if len(args) != 1 or options:
                raise ValueError(f"{operation} requires exactly one local file path")
            path = _validated_books_file(args[0])
            return shared._airdrop(path) if operation == "drop" else shared._show_local("Books", path)
        if operation == "item":
            if len(args) != 1 or options:
                raise ValueError("item requires exactly one Apple Books URL or asset ID")
            return shared._direct_open("Books", _policy_url(_canonical_item(args[0])))
        raise ValueError("Books route is not admitted")
    except (TypeError, ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        return shared._failed(error)


__all__ = ["books"]
