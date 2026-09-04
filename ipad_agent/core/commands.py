"""Shared semantic command helpers.

Imports are inert. Application-owned command selection lives beside each
integration manifest; shared validation, unlock gating, dispatch, result
projection, and transport primitives remain here.
"""
from __future__ import annotations

import importlib
import math
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


Result = Any


def _result(value: dict[str, Any]) -> Result:
    from ipad_agent.core.projection import public_result
    from ipad_agent.core.results import IPadResult

    return IPadResult(public_result(value))


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
    from ipad_agent.core.results import ipad

    return ipad(*args)


def _launch_payload(value: object) -> Result:
    """Normalize the unlock-gated CoreDevice helper's result without overclaiming."""
    if isinstance(value, dict):
        public = dict(value)
        for private_key in ("device_id", "url", "stdout", "stderr", "command"):
            public.pop(private_key, None)
        return _result(public)

    status = getattr(value, "status", None)
    if status == "locked":
        return _failed("iPad is locked", locked=True)
    if status == "unknown":
        return _failed("iPad lock state is unavailable")
    if status == "dispatched":
        value = getattr(value, "value", None)
        if isinstance(value, dict):
            public = dict(value)
            for private_key in ("device_id", "url", "stdout", "stderr", "command"):
                public.pop(private_key, None)
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
                "elapsed_seconds": getattr(value, "elapsed_seconds", None),
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
        coredevice = importlib.import_module("ipad_agent.transports.coredevice")
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
        message = (
            "CoreDevice response was lost after dispatch"
            if uncertain
            else "CoreDevice rejected the launch before acceptance"
        )
        return _failed(message, uncertain=uncertain)
    return _launch_payload(value)


def _unlock_preflight() -> Result | None:
    """Read the configured iPad lock state; return a failure or ``None``."""
    try:
        from ipad_agent.transports.coredevice import wait_for_ipad_unlocked

        state = wait_for_ipad_unlocked()
    except Exception:
        return _failed("iPad unlock preflight failed")
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



def _browser_policy_url(target: str, url: str) -> str:
    """Validate a browser URL through the active inert v1 policy."""
    from ipad_agent.core.config import load_config
    from ipad_agent.core.registry import (
        AddonNotEnabledError, IntegrationNotFoundError, RegistryError, load_registry,
    )

    try:
        config = load_config()
        registry = load_registry(enabled_addons=config.enabled_addons)
        return registry.validate_v1_url(target, "open-url", url)
    except (AddonNotEnabledError, IntegrationNotFoundError, RegistryError) as error:
        raise ValueError(str(error)) from error


def _unsupported(command: str, choices: Iterable[str]) -> Result:
    return _failed(f"unsupported command {command!r}; choose: {', '.join(choices)}")


def _batch(steps: list[list[str]]) -> Result:
    return _runtime_ip("b", steps)


def _merge_wda_teardown(action: Any, teardown: Any, *, label: str) -> Result:
    """Project one action plus the mandatory teardown outcome."""
    if isinstance(teardown, dict) and teardown.get("ok") is True:
        return action
    teardown_error = (
        teardown.get("error")
        if isinstance(teardown, dict)
        else "unknown teardown failure"
    )
    teardown_uncertain = (
        isinstance(teardown, dict) and teardown.get("uncertain") is True
    )
    if isinstance(action, dict) and action.get("ok") is not True:
        public = dict(action)
        public["error"] = (
            f"{public.get('error') or f'{label} failed'}; "
            f"WDA teardown failed: {teardown_error}"
        )
        public["uncertain"] = bool(public.get("uncertain")) or teardown_uncertain
        return _result(public)
    return _failed(
        f"{label} completed but WDA teardown failed: {teardown_error}",
        uncertain=teardown_uncertain,
    )


def _bounded_wda_lifecycle(
    target: str,
    work: Callable[[], Any],
    *,
    label: str,
) -> Result:
    """Launch, recheck unlock, run one bounded WDA action, and tear down once."""
    action: Any = _failed(f"{label} did not start")
    try:
        try:
            launched = _direct_open(target)
            if not isinstance(launched, dict) or launched.get("ok") is not True:
                action = launched
            else:
                # A device can relock after CoreDevice accepts the launch.
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
    return _merge_wda_teardown(action, teardown, label=label)


def _airdrop(path_value: object) -> Result:
    """Call only the optional, narrow ``airdrop(path)`` backend."""
    module_name = "ipad_agent.transports.airdrop"
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
    except (TypeError, ValueError, OSError):
        return _failed("local file path is invalid")
    if not path.is_file():
        return _failed("local file does not exist or is not a regular file")

    # AirDrop is a host-side mutation. Gate each drop (including the transfer
    # phase of show) on fresh lock evidence immediately before dispatch.
    preflight = _unlock_preflight()
    if preflight is not None:
        return preflight
    try:
        value = backend(path)
    except Exception as error:
        uncertain = bool(
            getattr(error, "uncertain", False) or getattr(error, "response_lost", False)
        )
        return _failed(
            "local file transfer outcome is uncertain"
            if uncertain else "local file transfer failed before completion",
            uncertain=uncertain,
        )
    if isinstance(value, dict):
        public = dict(value)
        status = public.get("status")
        if status == "uncertain":
            public["ok"] = False
            public["uncertain"] = True
            public["reason"] = "local file transfer outcome is uncertain"
            public["error"] = "local file transfer outcome is uncertain"
        else:
            if "ok" not in public:
                public["ok"] = status == "completed"
            public["uncertain"] = bool(public.get("uncertain"))
            if public["ok"] is not True:
                public["reason"] = "local file transfer failed before completion"
                public["error"] = "local file transfer failed before completion"
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


def controller(command: object, *args: object, **options: object) -> Result:
    """Lazy compatibility forward to the shared controller owner."""
    from ipad_agent.core.controller import controller as implementation

    return implementation(command, *args, **options)

def _route_operation(route: Any) -> Any:
    from ipad_agent.core.operations import OperationSpec, RetryClass, SafetyClass

    return OperationSpec(
        f"{route.integration_id}:{route.action_id}",
        f"{route.integration_id} {route.command}",
        SafetyClass(route.safety),
        RetryClass(route.retry),
        metadata={
            "integration_id": route.integration_id,
            "action_id": route.action_id,
            "policy_sha256": route.policy_sha256,
            "url_shape": route.url_shape,
        },
    )


def _rejected_route(
    integration_id: str,
    command: str,
    error: object,
    *,
    display_name: str | None = None,
) -> Result:
    """Project a rejected semantic URL route without exposing private values."""
    from ipad_agent.core.operations import (
        OperationError, OperationResult, OperationSpec, SafetyClass,
    )

    label = display_name or integration_id
    operation = OperationSpec(
        f"{integration_id}:{command or 'invalid'}",
        f"rejected {label} command",
        SafetyClass.OBSERVE,
        metadata={"integration_id": integration_id, "command": command or "invalid"},
    )
    outcome = OperationResult.not_sent(
        operation, OperationError("route_rejected", " ".join(str(error).split())),
    )
    return _result(outcome.to_plain_result())


def _validated_route_open(
    route: Any, *, config: Any, registry: Any, terminate: bool = False,
) -> Result:
    """Cross the production CoreDevice boundary once with a validated route."""
    from ipad_agent.core.operations import OperationError, OperationResult

    operation = _route_operation(route)
    try:
        coredevice = importlib.import_module("ipad_agent.transports.coredevice")
        helper = getattr(coredevice, "open_validated_route_when_unlocked")
        value = helper(
            route, config=config, registry=registry, terminate=terminate,
        )
    except Exception as error:
        uncertain = bool(
            getattr(error, "response_lost", False)
            or getattr(error, "uncertain", False)
            or getattr(error, "dispatched", False)
        )
        if uncertain:
            structured = OperationError(
                "coredevice_response_lost",
                "CoreDevice route response was lost after dispatch",
            )
            outcome = OperationResult.response_lost(operation, structured)
        else:
            structured = OperationError(
                "coredevice_route_rejected",
                "CoreDevice rejected the route before acceptance",
            )
            outcome = OperationResult.not_sent(operation, structured)
        return _result(outcome.to_plain_result())

    status = getattr(value, "status", None)
    if status == "locked":
        outcome = OperationResult.not_sent(
            operation, OperationError("device_locked", "iPad is locked"),
        )
    elif status == "unknown":
        outcome = OperationResult.not_sent(
            operation, OperationError("lock_state_unknown", "iPad lock state is unavailable"),
        )
    elif status == "dispatched":
        launch = getattr(value, "value", None)
        if launch is None:
            outcome = OperationResult.response_lost(
                operation, OperationError("invalid_coredevice_result", "CoreDevice returned no launch result after dispatch"),
            )
        else:
            bundle_id = getattr(launch, "bundle_id", None)
            if bundle_id != route.bundle_id:
                outcome = OperationResult.response_lost(
                    operation,
                    OperationError("wrong_bundle", "CoreDevice returned a different target bundle after dispatch"),
                )
            else:
                outcome = OperationResult.succeeded(
                    operation,
                    {
                        "route": "coredevice",
                        "bundle_id": bundle_id,
                        "elapsed_seconds": getattr(launch, "elapsed_seconds", None),
                        "locked": getattr(launch, "locked", None),
                        "dispatch_accepted": True,
                        "visible": False,
                        "integration_id": route.integration_id,
                        "action_id": route.action_id,
                        "policy_sha256": route.policy_sha256,
                        "url_shape": route.url_shape,
                    },
                )
    else:
        outcome = OperationResult.failed(
            operation,
            OperationError("invalid_coredevice_result", "CoreDevice returned an invalid unlock result"),
        )
    return _result(outcome.to_plain_result())

__all__ = ["controller"]
