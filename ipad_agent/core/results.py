"""Kernel-native control for the paired iPad.

Import once. ``show`` displays content or opens destinations; ``ipad`` performs
short native UI actions. Bare calls print a compact outcome while retaining the
complete result mapping for follow-up code.
"""
from __future__ import annotations

import json
from typing import Any

from ipad_agent.runtime import engine as runtime
from ipad_agent.transports.coredevice import IPadControlError
from ipad_agent.transports.display import IPadShowError, show as _show
from ipad_agent.core.operations import OperationSpec
from ipad_agent.core.projection import public_result


class IPadResult(dict[str, Any]):
    """Full device result with a token-light representation in the kernel."""

    def __repr__(self) -> str:
        return self.summary

    def _repr_pretty_(self, printer: Any, cycle: bool) -> None:
        printer.text(self.summary)

    @property
    def summary(self) -> str:
        if self.get("ok") is not True:
            if self.get("locked") is True:
                return "locked"
            message = _brief(str(self.get("error") or "iPad command failed"))
            # Legacy result mappings may predate structural operation metadata.
            # New senders always set ``uncertain`` from OperationPhase.
            legacy_unknown = "outcome is unknown" in message.casefold()
            if self.get("uncertain") is True or legacy_unknown:
                suffix = "" if "do not retry" in message.casefold() else "; do not retry"
                return f"uncertain: {message}{suffix}"
            return f"failed: {message}"
        route = self.get("route")
        if route == "now":
            return "shown"
        if route == "now-status":
            return "ready" if self.get("ready") else "not ready"
        if route == "now-stop":
            return "stopped" if self.get("stopped") else "already stopped"
        if route == "coredevice":
            return "locked" if self.get("locked") is True else "accepted"
        path = self.get("path")
        if path == "status":
            state = self.get("result")
            return "ready" if isinstance(state, dict) and state.get("session") else "idle"
        if path == "coredevice":
            state = self.get("result")
            return "locked" if isinstance(state, dict) and state.get("locked") is True else "accepted"
        if path == "daemon":
            return "stopped"
        if path == "batch":
            results = self.get("result")
            if isinstance(results, list):
                completed = sum(isinstance(item, dict) and item.get("ok") is True for item in results)
                return f"done: {completed}/{len(results)}"
        result = self.get("result")
        if isinstance(result, dict) and result.get("file"):
            return "saved"
        return "done"


def _brief(message: str, limit: int = 240) -> str:
    compact = " ".join(message.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _failed(error: BaseException | str, *, uncertain: bool = False) -> IPadResult:
    message = " ".join(str(error).split())
    return IPadResult({"ok": False, "error": message, "uncertain": uncertain})


def _result_for_request(result: dict[str, Any], request: dict[str, Any]) -> IPadResult:
    public = public_result(result)
    if public.get("path") == "batch" and isinstance(public.get("result"), list):
        children = public["result"]
        failed = next((child for child in children if isinstance(child, dict) and child.get("ok") is not True), None)
        if failed is not None:
            public["ok"] = False
            public["error"] = str(failed.get("error") or "batch command failed")
            public["uncertain"] = any(
                isinstance(child, dict) and child.get("uncertain") is True for child in children
            )
    return IPadResult(public)


def ipad(
    *args: object, timeout: float = runtime.CLIENT_RESPONSE_TIMEOUT,
    config: Any = None, registry: Any = None,
    operation: OperationSpec | None = None,
) -> IPadResult:
    """Execute one compact native-control opcode exactly once."""
    if not args:
        return _failed("ipad requires an opcode")
    if timeout <= 0:
        return _failed("timeout must be positive")
    try:
        rendered: list[str] = []
        for index, value in enumerate(args):
            if index == 1 and str(args[0]).casefold() == "b" and isinstance(value, list):
                rendered.append(json.dumps(value, separators=(",", ":"), ensure_ascii=False))
            else:
                rendered.append(str(value))
        request = runtime.argv_request(rendered)
        if operation is not None:
            if not isinstance(operation, OperationSpec):
                raise TypeError("operation must be an OperationSpec")
            request["_operation"] = operation.to_dict()
        result = runtime.dispatch_client(request, timeout=timeout, config=config, registry=registry)
    except (TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        return _failed(error)
    if not isinstance(result, dict):
        return _failed("iPad runtime returned a non-object response")
    return _result_for_request(result, request)


def show(
    op: object, *args: object, config: Any = None, registry: Any = None, **options: object
) -> IPadResult:
    """Display semantic content or open a destination on the iPad."""
    try:
        result = _show(op, *args, config=config, registry=registry, **options)
    except IPadControlError as error:
        uncertain = bool(getattr(error, "uncertain", False))
        message = (
            "CoreDevice response was lost after dispatch"
            if uncertain else "CoreDevice rejected the request before acceptance"
        )
        return _failed(message, uncertain=uncertain)
    except (IPadShowError, OSError, TimeoutError, ValueError) as error:
        return _failed(error, uncertain=bool(getattr(error, "uncertain", False)))
    if not isinstance(result, dict):
        return _failed("iPad display returned a non-object response")
    return IPadResult(public_result(result))


__all__ = ["IPadResult", "ipad", "show"]
