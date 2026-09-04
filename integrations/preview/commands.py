"""CoreDevice/AirDrop Preview commands with app-owned file authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ipad_agent.core import commands as shared

COMMANDS = ("open", "drop", "show")
_DIRECTORY = Path(__file__).parent
_AUTHORITY_PATH = _DIRECTORY / "file-authority.json"
_ALLOWED_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".jpe", ".png", ".tif", ".tiff", ".heic", ".heif",
    ".exr", ".bmp", ".dib", ".ico", ".tga", ".psd", ".icns", ".jp2", ".j2k",
    ".j2c", ".jpf", ".jpx", ".jpm",
)


def _load_file_authority() -> dict[str, object]:
    raw = json.loads(_AUTHORITY_PATH.read_text(encoding="utf-8"))
    if set(raw) != {"schema", "version", "application", "transport", "extensions", "evidence"}:
        raise ValueError("Preview file authority shape is invalid")
    if raw["schema"] != "ipad-agent.preview-file-authority/v1" or raw["version"] != 1:
        raise ValueError("Preview file authority version is invalid")
    if raw["application"] != "Preview" or raw["transport"] != "airdrop-single-local-file":
        raise ValueError("Preview file authority identity is invalid")
    extensions = raw["extensions"]
    if not isinstance(extensions, list) or tuple(extensions) != _ALLOWED_EXTENSIONS or len(extensions) != len(set(extensions)):
        raise ValueError("Preview file extensions are invalid")
    evidence = raw["evidence"]
    if not isinstance(evidence, list) or {item.get("kind") for item in evidence if isinstance(item, dict)} != {"apple-documentation", "simulator-bundle-declaration"}:
        raise ValueError("Preview file authority evidence is invalid")
    return raw


def _validated_preview_file(value: object) -> object:
    _load_file_authority()
    try:
        text = os.fspath(value)
    except TypeError as error:
        raise ValueError("Preview file must be one local path") from error
    if not isinstance(text, str) or not text or "\x00" in text:
        raise ValueError("Preview file must be one non-empty local path")
    name = Path(text).name.casefold()
    if not any(name.endswith(extension) for extension in _ALLOWED_EXTENSIONS):
        raise ValueError("Preview accepts PDF or a declared image format only")
    return value


def preview(command: object, *args: object, **options: object) -> Any:
    """Open Preview, transfer one admitted local file, or request a file handoff."""
    try:
        operation = shared._command(command)
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return shared._direct_open("Preview")
        if operation in {"drop", "show"}:
            if len(args) != 1 or options:
                raise ValueError(f"{operation} requires exactly one local file path")
            path = _validated_preview_file(args[0])
            return shared._airdrop(path) if operation == "drop" else shared._show_local("Preview", path)
        return shared._unsupported(operation, COMMANDS)
    except (TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        return shared._failed(error)


__all__ = ["preview"]
