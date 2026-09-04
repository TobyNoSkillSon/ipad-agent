"""Bounded screenshot observation for one separately authorized action.

Importing this module does not create a runtime or contact a device.  The
observer is an internal test aid; it does not authorize, route, or retry the
action supplied by its caller.
"""
from __future__ import annotations

import inspect
import math
from numbers import Number
import time
from typing import Any, Callable, NamedTuple

from ipad_agent.runtime import Runtime


class _ObservationFailure(NamedTuple):
    """Redacted failure metadata; exception messages may contain private state."""

    stage: str
    error_type: str
    uncertain: bool
    dispatched: bool


class _ScreenshotObservation(NamedTuple):
    """Immutable outcome of one bounded observation attempt."""

    action_result: Any
    screenshot_path: str | None
    settle_seconds: float
    action_status: str
    capture_status: str
    teardown_status: str
    failures: tuple[_ObservationFailure, ...]


def _failure(stage: str, error: BaseException) -> _ObservationFailure:
    return _ObservationFailure(
        stage=stage,
        error_type=type(error).__name__,
        uncertain=bool(
            getattr(error, "uncertain", False)
            or getattr(error, "response_lost", False)
        ),
        dispatched=bool(getattr(error, "dispatched", False)),
    )


def _validate_action(action: object) -> Callable[[], Any]:
    if not callable(action):
        raise TypeError("action must be a zero-argument callable")
    try:
        signature = inspect.signature(action)
    except (TypeError, ValueError) as error:
        raise TypeError("action must have an inspectable zero-argument signature") from error
    try:
        signature.bind()
    except TypeError as error:
        raise TypeError("action must be callable without arguments") from error
    return action


def _validate_settle_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Number) or isinstance(value, complex):
        raise TypeError("settle_seconds must be a finite real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("settle_seconds must be finite")
    if not 0.25 <= normalized <= 10.0:
        raise ValueError("settle_seconds must be between 0.25 and 10.0")
    return normalized


def screenshot_after(
    action: Callable[[], Any], *, settle_seconds: Number = 5.0
) -> _ScreenshotObservation:
    """Observe one authorized action once, then close the bounded WDA context.

    Returned statuses describe observation mechanics only.  In particular,
    ``action_status == "returned"`` does not mean the semantic action
    succeeded; callers must inspect the unchanged ``action_result``.
    Exceptions are represented by redacted structural failure metadata so an
    action or teardown failure remains visible without exposing private logs.
    """
    checked_action = _validate_action(action)
    requested_settle = _validate_settle_seconds(settle_seconds)

    runtime = Runtime()
    action_result: Any = None
    screenshot_path: str | None = None
    action_status = "not_invoked"
    capture_status = "not_attempted"
    teardown_status = "pending"
    failures: list[_ObservationFailure] = []

    try:
        try:
            runtime.ensure_session()
        except Exception as error:
            failures.append(_failure("heat", error))
        else:
            try:
                action_result = checked_action()
                action_status = "returned"
            except Exception as error:
                action_status = "raised"
                failures.append(_failure("action", error))
            else:
                try:
                    time.sleep(requested_settle)
                except Exception as error:
                    failures.append(_failure("settle", error))
                else:
                    try:
                        screenshot_path = runtime.screenshot()
                        capture_status = "captured"
                    except Exception as error:
                        capture_status = "failed"
                        failures.append(_failure("capture", error))
    finally:
        try:
            runtime.teardown()
            teardown_status = "complete"
        except Exception as error:
            teardown_status = "failed"
            failures.append(_failure("teardown", error))

    return _ScreenshotObservation(
        action_result=action_result,
        screenshot_path=screenshot_path,
        settle_seconds=requested_settle,
        action_status=action_status,
        capture_status=capture_status,
        teardown_status=teardown_status,
        failures=tuple(failures),
    )


__all__ = ["screenshot_after"]
