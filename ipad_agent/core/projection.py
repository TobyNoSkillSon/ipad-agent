"""Public compatibility-result projection with recursive private-field redaction."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_PRIVATE_RESULT_KEYS = frozenset({
    "argv",
    "attempt_id",
    "command",
    "device",
    "device_id",
    "raw_command",
    "snapshot_cleanup_error",
    "snapshot_path",
    "stderr",
    "stdout",
    "url",
})


def public_result(value: Any) -> Any:
    """Clone a result while removing transport-private fields at every depth."""
    if isinstance(value, Mapping):
        return {
            key: public_result(item)
            for key, item in value.items()
            if not (isinstance(key, str) and key.casefold() in _PRIVATE_RESULT_KEYS)
        }
    if isinstance(value, list):
        return [public_result(item) for item in value]
    if isinstance(value, tuple):
        return tuple(public_result(item) for item in value)
    return value


__all__ = ["public_result"]
