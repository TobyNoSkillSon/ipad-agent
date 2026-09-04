"""Operation safety, dispatch, retry, and evidence contracts.

This module is deliberately independent of the runtime.  It gives transports a
structured way to distinguish a command which was never sent from one whose
response was lost after dispatch.  In particular, callers must not infer that
distinction from exception or error text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping


SCHEMA = "ipad_agent.operation/v1"
PROJECTION_METADATA_KEY = "_operation"


class _WireEnum(str, Enum):
    """A string enum whose value is directly suitable for JSON messages."""

    def __str__(self) -> str:
        return self.value


class OperationPhase(_WireEnum):
    """How far an operation got at the dispatch boundary."""

    NOT_SENT = "not_sent"
    SENT = "sent"
    RESPONSE_RECEIVED = "response_received"
    RESPONSE_LOST = "response_lost"

    # Concise aliases for clients which model receipt rather than a response.
    RECEIVED = "response_received"
    LOST = "response_lost"


class SafetyClass(_WireEnum):
    OBSERVE = "observe"
    NAVIGATE = "navigate"
    TRANSIENT = "transient"
    PERSISTENT = "persistent"
    PROTECTED = "protected"


class RetryClass(_WireEnum):
    SAFE_REPEAT = "safe_repeat"
    INSPECT_THEN_DECIDE = "inspect_then_decide"
    NEVER_AUTOMATED = "never_automated"


_DEFAULT_RETRY = {
    SafetyClass.OBSERVE: RetryClass.SAFE_REPEAT,
    SafetyClass.NAVIGATE: RetryClass.SAFE_REPEAT,
    SafetyClass.TRANSIENT: RetryClass.INSPECT_THEN_DECIDE,
    SafetyClass.PERSISTENT: RetryClass.INSPECT_THEN_DECIDE,
    SafetyClass.PROTECTED: RetryClass.NEVER_AUTOMATED,
}
_RETRY_SEVERITY = {
    RetryClass.SAFE_REPEAT: 0,
    RetryClass.INSPECT_THEN_DECIDE: 1,
    RetryClass.NEVER_AUTOMATED: 2,
}
_SENSITIVE = frozenset({SafetyClass.PERSISTENT, SafetyClass.PROTECTED})


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _json_clone(value: Any, field_name: str = "value") -> Any:
    """Return a plain JSON value or raise a field-specific error."""

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must contain only JSON values") from error


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


@dataclass(frozen=True)
class OperationAuthority:
    """Explicit human or caller authority for a sensitive operation.

    All fields are intentionally required.  ``scope`` should describe the exact
    operation authorized; ``authority_id`` lets daemon evidence refer back to
    the grant without relying on prose in an error message.
    """

    authority_id: str
    granted_by: str
    scope: str
    granted_at: str

    def __post_init__(self) -> None:
        for name in ("authority_id", "granted_by", "scope", "granted_at"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {
            "authority_id": self.authority_id,
            "granted_by": self.granted_by,
            "scope": self.scope,
            "granted_at": self.granted_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationAuthority":
        return cls(
            authority_id=value.get("authority_id"),  # type: ignore[arg-type]
            granted_by=value.get("granted_by"),  # type: ignore[arg-type]
            scope=value.get("scope"),  # type: ignore[arg-type]
            granted_at=value.get("granted_at"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class OperationSpec:
    """Safety and retry policy attached to one intended operation."""

    operation_id: str
    name: str
    safety_class: SafetyClass
    retry_class: RetryClass | None = None
    authority: OperationAuthority | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _required_text(self.operation_id, "operation_id"))
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        try:
            safety = SafetyClass(self.safety_class)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid safety_class") from error
        object.__setattr__(self, "safety_class", safety)

        retry = _DEFAULT_RETRY[safety] if self.retry_class is None else self.retry_class
        try:
            retry = RetryClass(retry)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid retry_class") from error
        if safety is SafetyClass.PERSISTENT and retry is RetryClass.SAFE_REPEAT:
            raise ValueError("persistent operations cannot be safe_repeat")
        if safety is SafetyClass.PROTECTED and retry is not RetryClass.NEVER_AUTOMATED:
            raise ValueError("protected operations must be never_automated")
        object.__setattr__(self, "retry_class", retry)

        if self.authority is not None and not isinstance(self.authority, OperationAuthority):
            raise ValueError("authority must be an OperationAuthority")
        if safety in _SENSITIVE and self.authority is None:
            raise ValueError(f"{safety.value} operations require explicit authority fields")
        object.__setattr__(self, "metadata", _json_clone(dict(self.metadata), "metadata"))

    @property
    def has_explicit_authority(self) -> bool:
        return self.authority is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "name": self.name,
            "safety_class": self.safety_class.value,
            "retry_class": self.retry_class.value,
            "authority": None if self.authority is None else self.authority.to_dict(),
            "metadata": _json_clone(self.metadata),
        }

    def to_message(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "kind": "operation", "operation": self.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationSpec":
        raw_authority = value.get("authority")
        authority = None
        if raw_authority is not None:
            authority = OperationAuthority.from_dict(_mapping(raw_authority, "authority"))
        return cls(
            operation_id=value.get("operation_id"),  # type: ignore[arg-type]
            name=value.get("name"),  # type: ignore[arg-type]
            safety_class=value.get("safety_class"),  # type: ignore[arg-type]
            retry_class=value.get("retry_class"),  # type: ignore[arg-type]
            authority=authority,
            metadata=_mapping(value.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True)
class OperationError:
    """Machine-readable failure information; ``code`` drives logic, not text."""

    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "error.code"))
        object.__setattr__(self, "message", _required_text(self.message, "error.message"))
        object.__setattr__(self, "details", _json_clone(dict(self.details), "error.details"))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": _json_clone(self.details)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationError":
        return cls(
            code=value.get("code"),  # type: ignore[arg-type]
            message=value.get("message"),  # type: ignore[arg-type]
            details=_mapping(value.get("details", {}), "error.details"),
        )


def _coerce_error(error: OperationError | None, *, code: str, message: str) -> OperationError:
    return error if error is not None else OperationError(code, message)


@dataclass(frozen=True)
class OperationResult:
    """Outcome at the operation/transport boundary.

    ``uncertain`` is derived exclusively from ``phase``.  A response-lost
    result can therefore never accidentally appear certain because an error
    string changed.
    """

    operation: OperationSpec
    phase: OperationPhase
    ok: bool | None = None
    response: Any = None
    error: OperationError | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, OperationSpec):
            raise ValueError("operation must be an OperationSpec")
        try:
            phase = OperationPhase(self.phase)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid operation phase") from error
        object.__setattr__(self, "phase", phase)
        if self.error is not None and not isinstance(self.error, OperationError):
            raise ValueError("error must be an OperationError")

        if phase is OperationPhase.RESPONSE_RECEIVED:
            if not isinstance(self.ok, bool):
                raise ValueError("response_received requires a boolean ok value")
            if self.ok and self.error is not None:
                raise ValueError("a successful response cannot contain an error")
            if not self.ok and self.error is None:
                raise ValueError("a failed response requires a structured error")
        else:
            if self.ok is not None:
                raise ValueError(f"{phase.value} requires ok=None")
            if self.response is not None:
                raise ValueError(f"{phase.value} cannot contain a response")
        object.__setattr__(self, "response", _json_clone(self.response, "response"))

    @classmethod
    def not_sent(cls, operation: OperationSpec, error: OperationError | None = None) -> "OperationResult":
        return cls(
            operation,
            OperationPhase.NOT_SENT,
            error=_coerce_error(error, code="not_sent", message="operation was not dispatched"),
        )

    @classmethod
    def sent(cls, operation: OperationSpec) -> "OperationResult":
        return cls(operation, OperationPhase.SENT)

    @classmethod
    def succeeded(cls, operation: OperationSpec, response: Any = None) -> "OperationResult":
        return cls(operation, OperationPhase.RESPONSE_RECEIVED, ok=True, response=response)

    @classmethod
    def failed(cls, operation: OperationSpec, error: OperationError) -> "OperationResult":
        return cls(operation, OperationPhase.RESPONSE_RECEIVED, ok=False, error=error)

    @classmethod
    def response_lost(
        cls, operation: OperationSpec, error: OperationError | None = None
    ) -> "OperationResult":
        return cls(
            operation,
            OperationPhase.RESPONSE_LOST,
            error=_coerce_error(error, code="response_lost", message="response was lost after dispatch"),
        )

    @property
    def dispatched(self) -> bool:
        return self.phase is not OperationPhase.NOT_SENT

    @property
    def response_received(self) -> bool:
        return self.phase is OperationPhase.RESPONSE_RECEIVED

    @property
    def uncertain(self) -> bool:
        return self.phase is OperationPhase.RESPONSE_LOST

    @property
    def complete(self) -> bool:
        return self.phase is not OperationPhase.SENT

    @property
    def automated_retry_allowed(self) -> bool:
        if self.phase is OperationPhase.SENT:
            return False
        return self.operation.retry_class is RetryClass.SAFE_REPEAT

    @property
    def projection_metadata(self) -> dict[str, Any]:
        authority_id = None if self.operation.authority is None else self.operation.authority.authority_id
        return {
            "schema": SCHEMA,
            "operation_id": self.operation.operation_id,
            "name": self.operation.name,
            "safety_class": self.operation.safety_class.value,
            "retry_class": self.operation.retry_class.value,
            "phase": self.phase.value,
            "dispatched": self.dispatched,
            "response_received": self.response_received,
            "uncertain": self.uncertain,
            "complete": self.complete,
            "automated_retry_allowed": self.automated_retry_allowed,
            "authority_id": authority_id,
        }

    def to_plain_result(self, *, metadata_key: str = PROJECTION_METADATA_KEY) -> dict[str, Any]:
        """Project onto the existing plain-result shape without losing policy."""

        metadata_key = _required_text(metadata_key, "metadata_key")
        if self.response_received and self.ok and isinstance(self.response, Mapping):
            plain = _json_clone(dict(self.response), "response")
        elif self.response_received and self.ok:
            plain = {"result": _json_clone(self.response, "response")}
        else:
            plain = {}
        plain["ok"] = self.ok is True
        if self.phase is OperationPhase.SENT:
            plain["pending"] = True
        if self.error is not None:
            plain["error"] = self.error.message
            plain["error_info"] = self.error.to_dict()
        if self.uncertain:
            plain["uncertain"] = True
        plain[metadata_key] = self.projection_metadata
        return plain

    # A convenient noun for evidence-producing callers.
    def to_evidence(self, *, include_response: bool = True) -> dict[str, Any]:
        value = self.to_message()
        if not include_response:
            value["result"]["response"] = None
            value["result"]["response_omitted"] = self.response is not None
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation.to_dict(),
            "phase": self.phase.value,
            "ok": self.ok,
            "response": _json_clone(self.response),
            "error": None if self.error is None else self.error.to_dict(),
        }

    def to_message(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "kind": "operation_result", "result": self.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationResult":
        raw_error = value.get("error")
        error = None if raw_error is None else OperationError.from_dict(_mapping(raw_error, "error"))
        return cls(
            operation=OperationSpec.from_dict(_mapping(value.get("operation"), "operation")),
            phase=value.get("phase"),  # type: ignore[arg-type]
            ok=value.get("ok"),  # type: ignore[arg-type]
            response=value.get("response"),
            error=error,
        )


@dataclass(frozen=True)
class BatchResult:
    """Deterministic aggregation of operation results."""

    batch_id: str
    results: tuple[OperationResult, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "batch_id", _required_text(self.batch_id, "batch_id"))
        object.__setattr__(self, "results", tuple(self.results))
        if not self.results:
            raise ValueError("a batch requires at least one operation result")
        if not all(isinstance(item, OperationResult) for item in self.results):
            raise ValueError("batch results must be OperationResult values")
        operation_ids = [item.operation.operation_id for item in self.results]
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError("operation_id values must be unique within a batch")
        object.__setattr__(self, "metadata", _json_clone(dict(self.metadata), "metadata"))

    @classmethod
    def aggregate(
        cls, batch_id: str, results: Iterable[OperationResult], *, metadata: Mapping[str, Any] | None = None
    ) -> "BatchResult":
        return cls(batch_id, tuple(results), {} if metadata is None else metadata)

    @property
    def phase_counts(self) -> dict[str, int]:
        return {
            phase.value: sum(item.phase is phase for item in self.results)
            for phase in (
                OperationPhase.NOT_SENT,
                OperationPhase.SENT,
                OperationPhase.RESPONSE_RECEIVED,
                OperationPhase.RESPONSE_LOST,
            )
        }

    @property
    def counts(self) -> dict[str, int]:
        return {
            "total": len(self.results),
            "succeeded": sum(item.ok is True for item in self.results),
            "failed": sum(item.ok is False for item in self.results),
            "not_sent": sum(item.phase is OperationPhase.NOT_SENT for item in self.results),
            "pending": sum(item.phase is OperationPhase.SENT for item in self.results),
            "uncertain": sum(item.uncertain for item in self.results),
        }

    @property
    def ok(self) -> bool:
        return all(item.phase is OperationPhase.RESPONSE_RECEIVED and item.ok is True for item in self.results)

    @property
    def uncertain(self) -> bool:
        return any(item.uncertain for item in self.results)

    @property
    def complete(self) -> bool:
        return all(item.complete for item in self.results)

    @property
    def retry_class(self) -> RetryClass:
        return max(
            (item.operation.retry_class for item in self.results),
            key=lambda item: _RETRY_SEVERITY[item],
        )

    @property
    def projection_metadata(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "batch_id": self.batch_id,
            "counts": self.counts,
            "phase_counts": self.phase_counts,
            "uncertain": self.uncertain,
            "complete": self.complete,
            "retry_class": self.retry_class.value,
        }

    def to_plain_result(self, *, metadata_key: str = PROJECTION_METADATA_KEY) -> dict[str, Any]:
        metadata_key = _required_text(metadata_key, "metadata_key")
        return {
            "ok": self.ok,
            "path": "batch",
            "result": [item.to_plain_result(metadata_key=metadata_key) for item in self.results],
            "uncertain": self.uncertain,
            metadata_key: self.projection_metadata,
        }

    def to_evidence(self, *, include_responses: bool = True) -> dict[str, Any]:
        value = self.to_message()
        if not include_responses:
            for result in value["batch"]["results"]:
                result["response_omitted"] = result.get("response") is not None
                result["response"] = None
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "results": [item.to_dict() for item in self.results],
            "metadata": _json_clone(self.metadata),
        }

    def to_message(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "kind": "batch_result", "batch": self.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BatchResult":
        raw_results = value.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("batch.results must be an array")
        return cls(
            batch_id=value.get("batch_id"),  # type: ignore[arg-type]
            results=tuple(OperationResult.from_dict(_mapping(item, "batch result")) for item in raw_results),
            metadata=_mapping(value.get("metadata", {}), "batch.metadata"),
        )


MessageValue = OperationSpec | OperationResult | BatchResult


def to_message(value: MessageValue) -> dict[str, Any]:
    """Serialize an operation object to a daemon/evidence-safe JSON object."""

    if isinstance(value, (OperationSpec, OperationResult, BatchResult)):
        return value.to_message()
    raise TypeError("value must be an OperationSpec, OperationResult, or BatchResult")


def from_message(message: Mapping[str, Any]) -> MessageValue:
    """Deserialize one versioned operation message."""

    if message.get("schema") != SCHEMA:
        raise ValueError("unsupported operation message schema")
    kind = message.get("kind")
    if kind == "operation":
        return OperationSpec.from_dict(_mapping(message.get("operation"), "operation"))
    if kind == "operation_result":
        return OperationResult.from_dict(_mapping(message.get("result"), "result"))
    if kind == "batch_result":
        return BatchResult.from_dict(_mapping(message.get("batch"), "batch"))
    raise ValueError("unsupported operation message kind")


def dumps_message(value: MessageValue) -> str:
    """Encode one operation message for newline-delimited daemon transport."""

    return json.dumps(to_message(value), separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def loads_message(payload: str | bytes | bytearray) -> MessageValue:
    """Decode a daemon/evidence message and restore its typed contract."""

    try:
        value = json.loads(payload)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid operation message JSON") from error
    return from_message(_mapping(value, "message"))


# Readable compatibility aliases for callers which prefer shorter nouns.
Operation = OperationSpec
OperationOutcome = OperationResult
BatchOutcome = BatchResult
Authority = OperationAuthority
Phase = OperationPhase
Safety = SafetyClass
Retry = RetryClass


__all__ = [
    "Authority",
    "BatchOutcome",
    "BatchResult",
    "MessageValue",
    "Operation",
    "OperationAuthority",
    "OperationError",
    "OperationOutcome",
    "OperationPhase",
    "OperationResult",
    "OperationSpec",
    "PROJECTION_METADATA_KEY",
    "Phase",
    "Retry",
    "RetryClass",
    "SCHEMA",
    "Safety",
    "SafetyClass",
    "dumps_message",
    "from_message",
    "loads_message",
    "to_message",
]
