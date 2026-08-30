"""Implementation for the small semantic V1 command surface.

Imports are inert. Full command words are translated here so CoreDevice, WDA,
and AirDrop details never become part of the public function signatures.
"""
from __future__ import annotations

import importlib
import math
import re
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


Result = Any


def _result(value: dict[str, Any]) -> Result:
    from .api import IPadResult

    return IPadResult(value)


def _failed(message: object, *, uncertain: bool = False, **fields: object) -> Result:
    text = " ".join(str(message).split()) or "iPad command failed"
    return _result({"ok": False, "error": text, "uncertain": uncertain, **fields})


def _command(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("command must be a full, non-empty word")
    return " ".join(value.strip().casefold().replace("-", " ").replace("_", " ").split())


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _runtime_ip(*args: object) -> Result:
    """Call the compact runtime API for status and the hidden Settings WDA burst."""
    from .api import ipad

    return ipad(*args)


def _launch_payload(value: object) -> Result:
    """Normalize the unlock-gated CoreDevice helper's result without overclaiming."""
    if isinstance(value, dict):
        return _result(dict(value))

    status = getattr(value, "status", None)
    if status == "locked":
        return _failed("iPad is locked", locked=True)
    if status == "unknown":
        return _failed("iPad lock state is unavailable")
    if status == "dispatched":
        value = getattr(value, "value", None)
        if isinstance(value, dict):
            public = dict(value)
            public.setdefault("ok", True)
            public.setdefault("route", "coredevice")
            return _result(public)

    bundle_id = getattr(value, "bundle_id", None)
    if isinstance(bundle_id, str) and bundle_id:
        return _result(
            {
                "ok": True,
                "route": "coredevice",
                "bundle_id": bundle_id,
                "device_id": getattr(value, "device_id", None),
                "elapsed_seconds": getattr(value, "elapsed_seconds", None),
                "url": getattr(value, "url", None),
                "locked": getattr(value, "locked", None),
            }
        )
    return _failed("CoreDevice unlock-gated launch returned an invalid result")


def _direct_open(target: str, url: str | None = None) -> Result:
    """Call the CoreDevice unlock gate expected by the semantic surface.

    The import stays lazy so package import remains inert and so this facade can
    land independently of the helper's implementation.
    """
    try:
        coredevice = importlib.import_module(f"{__package__}.coredevice")
        helper = getattr(coredevice, "open_ipad_when_unlocked")
    except (ImportError, AttributeError) as error:
        return _failed(f"unlock-gated CoreDevice launch is unavailable: {error}")
    if not callable(helper):
        return _failed("unlock-gated CoreDevice launch is unavailable")
    try:
        value = helper(target) if url is None else helper(target, url=url)
    except Exception as error:
        uncertain = bool(
            getattr(error, "uncertain", False) or getattr(error, "response_lost", False)
        )
        return _failed(error, uncertain=uncertain)
    return _launch_payload(value)


def _unlock_preflight() -> Result | None:
    """Read the configured iPad lock state; return a failure or ``None``."""
    try:
        from .coredevice import wait_for_ipad_unlocked

        state = wait_for_ipad_unlocked()
    except Exception as error:
        return _failed(f"iPad unlock preflight failed: {error}")
    if state == "unlocked":
        return None
    if state == "locked":
        return _failed("iPad is locked", locked=True)
    if state == "unknown":
        return _failed("iPad lock state is unavailable")
    return _failed("iPad unlock preflight returned an invalid result")


def _http_url(value: object, *, name: str = "url") -> str:
    url = _text(value, name)
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise ValueError(f"{name} must not contain whitespace or control characters")
    parsed = urlparse(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{name} must not contain credentials")
    return url


def _youtube_url(value: object, at: object | None) -> str:
    url = _http_url(value, name="video url")
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if host not in {"youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"}:
        raise ValueError("video url must be a YouTube HTTP or HTTPS URL")
    if at is None:
        return url
    if (
        isinstance(at, bool)
        or not isinstance(at, (int, float))
        or not math.isfinite(float(at))
        or float(at) < 0
    ):
        raise ValueError("at must be a non-negative number of seconds")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["t"] = f"{int(float(at))}s"
    return urlunparse(parsed._replace(query=urlencode(query)))


_APP_STORE_ID = re.compile(r"(?:id)?([1-9][0-9]*)", re.IGNORECASE)
_APP_STORE_PATH_ID = re.compile(r"id([1-9][0-9]*)", re.IGNORECASE)


def _app_store_url(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("product must be an App Store URL or positive product ID")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError("product ID must be positive")
        return f"https://apps.apple.com/app/id{value}"

    product = _text(value, "product")
    identifier = _APP_STORE_ID.fullmatch(product)
    if identifier is not None:
        return f"https://apps.apple.com/app/id{identifier.group(1)}"

    url = _http_url(product, name="App Store URL")
    parsed = urlparse(url)
    if (parsed.hostname or "").casefold() != "apps.apple.com" or parsed.port is not None:
        raise ValueError("App Store URL must use apps.apple.com")
    if not any(_APP_STORE_PATH_ID.fullmatch(part) for part in parsed.path.split("/")):
        raise ValueError("App Store URL must contain an explicit product ID")
    return url


def _unsupported(command: str, choices: Iterable[str]) -> Result:
    return _failed(f"unsupported command {command!r}; choose: {', '.join(choices)}")


def _merge_teardown(action: Result, teardown: Result) -> Result:
    if isinstance(teardown, dict) and teardown.get("ok") is True:
        return action
    teardown_error = teardown.get("error") if isinstance(teardown, dict) else "unknown teardown failure"
    teardown_uncertain = isinstance(teardown, dict) and teardown.get("uncertain") is True
    if isinstance(action, dict) and action.get("ok") is not True:
        public = dict(action)
        public["error"] = (
            f"{public.get('error') or 'Settings navigation failed'}; "
            f"WDA teardown failed: {teardown_error}"
        )
        public["uncertain"] = bool(public.get("uncertain")) or teardown_uncertain
        return _result(public)
    return _failed(
        f"Settings navigation completed but WDA teardown failed: {teardown_error}",
        uncertain=teardown_uncertain,
    )


def _settings_ui(work: Callable[[], Result]) -> Result:
    """Launch Settings directly, use one hidden WDA burst, and always tear down."""
    action: Result
    try:
        try:
            launched = _direct_open("Settings")
            if not isinstance(launched, dict) or launched.get("ok") is not True:
                action = launched
            else:
                # The user may relock the iPad after CoreDevice accepts the
                # launch. Recheck at the WDA boundary and do not start WDA
                # unless fresh read-only evidence says it is unlocked.
                preflight = _unlock_preflight()
                action = preflight if preflight is not None else work()
        except Exception as error:
            action = _failed(
                error,
                uncertain=bool(
                    getattr(error, "uncertain", False)
                    or getattr(error, "response_lost", False)
                ),
            )
    finally:
        try:
            teardown = _runtime_ip("x")
        except Exception as error:
            teardown = _failed(error)
    return _merge_teardown(action, teardown)


def _batch(steps: list[list[str]]) -> Result:
    return _runtime_ip("b", steps)


def _airdrop(path_value: object) -> Result:
    """Call only the optional, narrow ``airdrop(path)`` backend."""
    module_name = f"{__package__}.airdrop"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name == module_name:
            return _failed(
                "local file transfer is unsupported: the optional airdrop backend is not available"
            )
        return _failed(f"local file transfer backend could not load: {error}")
    except ImportError as error:
        return _failed(f"local file transfer backend could not load: {error}")
    backend = getattr(module, "airdrop", None)
    if not callable(backend):
        return _failed(
            "local file transfer is unsupported: the optional backend does not expose "
            "the narrow airdrop(path) function"
        )

    try:
        path = Path(path_value).expanduser().resolve()
    except (TypeError, ValueError, OSError) as error:
        return _failed(f"file must be a valid local path: {error}")
    if not path.is_file():
        return _failed(f"local file does not exist: {path}")

    # AirDrop is a host-side mutation. Gate each drop (including the transfer
    # phase of show) on fresh lock evidence immediately before dispatch.
    preflight = _unlock_preflight()
    if preflight is not None:
        return preflight
    try:
        value = backend(path)
    except Exception as error:
        return _failed(
            error,
            uncertain=bool(
                getattr(error, "uncertain", False) or getattr(error, "response_lost", False)
            ),
        )
    if isinstance(value, dict):
        public = dict(value)
        status = public.get("status")
        if status == "uncertain":
            public["ok"] = False
            public["uncertain"] = True
            public.setdefault("error", str(public.get("reason") or "local file transfer is uncertain"))
        else:
            if "ok" not in public:
                public["ok"] = status == "completed"
            public["uncertain"] = bool(public.get("uncertain"))
            if public["ok"] is not True and "error" not in public:
                public["error"] = str(public.get("reason") or "local file transfer failed")
        return _result(public)
    return _result({"ok": True, "route": "airdrop", "result": value, "uncertain": False})


def _show_local(target: str, path: object) -> Result:
    transfer = _airdrop(path)
    if not isinstance(transfer, dict) or transfer.get("ok") is not True:
        return transfer

    handoff = _direct_open(target)
    if not isinstance(handoff, dict):
        return _result(
            {
                "ok": False,
                "status": "handoff_failed",
                "error": "file transferred, but app handoff returned an invalid result",
                "transfer_complete": True,
                "handoff_verified": False,
                "shown": False,
                "uncertain": False,
                "transfer": dict(transfer),
            }
        )
    if handoff.get("ok") is not True:
        return _result(
            {
                "ok": False,
                "status": "handoff_failed",
                "error": (
                    "file transferred, but app handoff failed: "
                    f"{handoff.get('error') or 'unknown failure'}"
                ),
                "transfer_complete": True,
                "handoff_verified": False,
                "shown": False,
                "uncertain": bool(handoff.get("uncertain")),
                "transfer": dict(transfer),
                "handoff": dict(handoff),
            }
        )

    # Launch acceptance cannot prove that iPadOS associated this exact file
    # with the target app. Keep the transfer fact, but expose the handoff as a
    # pending non-success until a live observer supplies that missing evidence.
    return _result(
        {
            "ok": False,
            "status": "pending",
            "error": f"file transferred; exact handoff to {target} is unverified",
            "transfer_complete": True,
            "handoff_verified": False,
            "shown": False,
            "uncertain": False,
            "transfer": dict(transfer),
            "handoff": dict(handoff),
        }
    )


def _local_app(target: str, command: object, *args: object, **options: object) -> Result:
    try:
        operation = _command(command)
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return _direct_open(target)
        if operation == "drop":
            if len(args) != 1 or options:
                raise ValueError("drop requires exactly one local file path")
            return _airdrop(args[0])
        if operation == "show":
            if len(args) != 1 or options:
                raise ValueError("show requires exactly one local file path")
            return _show_local(target, args[0])
        return _unsupported(operation, ("open", "drop", "show"))
    except (TypeError, ValueError, OSError) as error:
        return _failed(error)


def controller(command: object, *args: object, **options: object) -> Result:
    """Open one app, transfer one local file, or report runtime status."""
    try:
        operation = _command(command)
        if operation == "open":
            if len(args) != 1 or options:
                raise ValueError("open requires exactly one app name")
            return _direct_open(_text(args[0], "app"))
        if operation == "drop":
            if len(args) != 1 or options:
                raise ValueError("drop requires exactly one local file path")
            return _airdrop(args[0])
        if operation == "status":
            if args or options:
                raise ValueError("status takes no arguments")
            return _runtime_ip("q")
        return _unsupported(operation, ("open", "drop", "status"))
    except (TypeError, ValueError, OSError) as error:
        return _failed(error)


def preview(command: object, *args: object, **options: object) -> Result:
    return _local_app("Preview", command, *args, **options)


def books(command: object, *args: object, **options: object) -> Result:
    return _local_app("Books", command, *args, **options)


def files(command: object, *args: object, **options: object) -> Result:
    return _local_app("Files", command, *args, **options)


_SETTINGS = {
    "general": "settings.general",
    "wifi": "settings.wifi",
    "bluetooth": "settings.bluetooth",
    "battery": "settings.battery",
    "accessibility": "settings.accessibility",
}


def settings(command: object, *args: object, **options: object) -> Result:
    """Open Settings or one allowlisted read-only destination."""
    try:
        operation = _command(command)
        if args or options:
            raise ValueError(f"{operation} takes no arguments")
        if operation == "open":
            return _direct_open("Settings")
        if operation in _SETTINGS:
            return _settings_ui(lambda: _batch([["t", _SETTINGS[operation]]]))
        if operation == "about":
            return _settings_ui(
                lambda: _batch(
                    [
                        ["t", "settings.general"],
                        ["w", "accessibility id=About", "5"],
                        ["t", "accessibility id=About"],
                    ]
                )
            )
        return _unsupported(
            operation,
            ("open", "general", "about", "wifi", "bluetooth", "battery", "accessibility"),
        )
    except (TypeError, ValueError, OSError) as error:
        return _failed(error)


def clock(command: object, *args: object, **options: object) -> Result:
    try:
        operation = _command(command)
        if args or options:
            raise ValueError(f"{operation} takes no arguments")
        if operation == "open":
            return _direct_open("Clock")
        return _unsupported(operation, ("open",))
    except (TypeError, ValueError, OSError) as error:
        return _failed(error)


def browser(target: str, command: object, *args: object, **options: object) -> Result:
    try:
        operation = _command(command)
        if operation == "website":
            if len(args) != 1 or options:
                raise ValueError("website requires exactly one HTTP or HTTPS URL")
            return _direct_open(target, _http_url(args[0]))
        if operation == "youtube":
            if len(args) != 1 or set(options) - {"at"}:
                raise ValueError("youtube requires one URL and optional at=seconds")
            return _direct_open(target, _youtube_url(args[0], options.get("at")))
        return _unsupported(operation, ("website", "youtube"))
    except (TypeError, ValueError, OSError) as error:
        return _failed(error)


def maps(command: object, *args: object, **options: object) -> Result:
    try:
        operation = _command(command)
        if operation == "show":
            if len(args) != 1 or options:
                raise ValueError("show requires exactly one location")
            location = _text(args[0], "location")
            return _direct_open("Maps", "maps://?" + urlencode({"q": location}))
        return _unsupported(operation, ("show",))
    except (TypeError, ValueError, OSError) as error:
        return _failed(error)


def app_store(command: object, *args: object, **options: object) -> Result:
    try:
        operation = _command(command)
        if operation == "open":
            if args or options:
                raise ValueError("open takes no arguments")
            return _direct_open("App Store")
        if operation == "show":
            if len(args) != 1 or options:
                raise ValueError("show requires exactly one App Store URL or product ID")
            return _direct_open("App Store", _app_store_url(args[0]))
        return _unsupported(operation, ("open", "show"))
    except (TypeError, ValueError, OSError) as error:
        return _failed(error)


__all__ = [
    "app_store",
    "books",
    "browser",
    "clock",
    "controller",
    "files",
    "maps",
    "preview",
    "settings",
]
