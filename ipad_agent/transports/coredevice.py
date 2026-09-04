"""Launch apps and URL payloads on a paired iPad through Apple CoreDevice.

This is the low-latency, overlay-free path for actions that do not require taps.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Generic, Literal, TypeVar

if TYPE_CHECKING:
    from ipad_agent.core.config import Config
    from ipad_agent.core.registry import IntegrationRegistry
    from ipad_agent.core.urlroutes import ValidatedURLRoute



class IPadControlError(RuntimeError):
    """Raised when CoreDevice cannot perform the requested iPad action."""

    def __init__(
        self, message: str, *, response_lost: bool = False, dispatched: bool = False,
    ) -> None:
        super().__init__(message)
        self.response_lost = bool(response_lost)
        self.uncertain = self.response_lost
        self.dispatched = bool(dispatched or response_lost)


@dataclass(frozen=True)
class LaunchResult:
    bundle_id: str
    device_id: str
    elapsed_seconds: float
    url: str | None
    locked: bool | None


UnlockState = Literal["unlocked", "locked", "unknown"]
_DispatchValue = TypeVar("_DispatchValue")


@dataclass(frozen=True)
class UnlockDispatchResult(Generic[_DispatchValue]):
    """Outcome of a mutation gated on a manual device unlock."""

    status: Literal["dispatched", "locked", "unknown"]
    value: _DispatchValue | None = None

    @property
    def dispatched(self) -> bool:
        return self.status == "dispatched"


def _wait_for_device_unlocked(
    device_id: str,
    *,
    wait_timeout: float,
    poll_interval: float,
    lock_check_timeout: float,
) -> UnlockState:
    """Poll one resolved device without dispatching or changing device state."""
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("device_id must be a non-empty string")
    if wait_timeout <= 0:
        raise ValueError("wait_timeout must be greater than zero")
    if poll_interval <= 0:
        raise ValueError("poll_interval must be greater than zero")
    if lock_check_timeout <= 0:
        raise ValueError("lock_check_timeout must be greater than zero")

    device_id = device_id.strip()
    deadline = time.monotonic() + wait_timeout
    saw_locked = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "locked" if saw_locked else "unknown"

        locked = _device_locked(device_id, min(lock_check_timeout, remaining))
        if locked is False:
            return "unlocked"
        if locked is True:
            saw_locked = True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "locked" if saw_locked else "unknown"
        time.sleep(min(poll_interval, remaining))


def wait_for_ipad_unlocked(
    device: str | None = None,
    *,
    wait_timeout: float = 10.0,
    poll_interval: float = 0.25,
    lock_check_timeout: float = 5.0,
    config: "Config | None" = None,
) -> UnlockState:
    """Return the configured iPad's lock state after bounded read-only polling.

    ``device`` overrides the configured identifier.  If neither is present,
    exactly one paired physical iPad is discovered.  The function performs
    only CoreDevice discovery and lock-state reads; it never dispatches a
    launch, UI session, transfer, or other mutation.
    """
    if device is not None and (not isinstance(device, str) or not device.strip()):
        raise ValueError("device must be a non-empty string when provided")
    # Reject invalid bounds before configuration load or device discovery.
    if wait_timeout <= 0:
        raise ValueError("wait_timeout must be greater than zero")
    if poll_interval <= 0:
        raise ValueError("poll_interval must be greater than zero")
    if lock_check_timeout <= 0:
        raise ValueError("lock_check_timeout must be greater than zero")
    if config is None:
        from ipad_agent.core.config import load_config
        config = load_config()
    device_id = _resolve_device(device, config, wait_timeout)
    return _wait_for_device_unlocked(
        device_id,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        lock_check_timeout=lock_check_timeout,
    )


def dispatch_when_unlocked(
    device_id: str,
    dispatch: Callable[[], _DispatchValue],
    *,
    wait_timeout: float = 10.0,
    poll_interval: float = 0.25,
    lock_check_timeout: float = 5.0,
) -> UnlockDispatchResult[_DispatchValue]:
    """Wait briefly for manual unlock, then dispatch one mutation at most once.

    Lock state is checked before any mutation.  Known-locked and transiently
    unknown states are polled until ``wait_timeout`` expires.  At the deadline,
    a definitive locked observation takes precedence over unknown observations.
    Once ``dispatch`` is called, its result or exception is returned directly;
    it is never retried here.
    """
    if not callable(dispatch):
        raise TypeError("dispatch must be callable")
    state = _wait_for_device_unlocked(
        device_id,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        lock_check_timeout=lock_check_timeout,
    )
    if state == "unlocked":
        return UnlockDispatchResult("dispatched", dispatch())
    return UnlockDispatchResult(state)


def _control_context(
    config: "Config | None", registry: "IntegrationRegistry | None"
) -> tuple["Config", "IntegrationRegistry"]:
    if config is None:
        from ipad_agent.core.config import load_config
        config = load_config()
    if registry is None:
        from ipad_agent.core.registry import load_registry
        registry = load_registry(enabled_addons=config.enabled_addons)
    return config, registry


def _bundle_for_target(target: str, config: "Config", registry: "IntegrationRegistry") -> str | None:
    from ipad_agent.core.registry import (
        AddonNotEnabledError, IntegrationNotFoundError, normalize_name,
    )

    # Exact bundles are a deliberately low-level route. They do not select the
    # Now browser and therefore do not require an enabled integration.
    if "." in target:
        return target
    try:
        return registry.resolve_bundle(target)
    except AddonNotEnabledError:
        # A configured low-level alias must not bypass an explicitly disabled addon.
        raise
    except IntegrationNotFoundError:
        pass
    wanted = normalize_name(target)
    for alias, bundle_id in config.bundle_aliases.items():
        if normalize_name(alias) == wanted:
            return bundle_id
    return None


def open_ipad_when_unlocked(
    target: str,
    *,
    url: str | None = None,
    device: str | None = None,
    terminate: bool = False,
    timeout: float = 15.0,
    wait_timeout: float = 10.0,
    poll_interval: float = 0.25,
    lock_check_timeout: float = 5.0,
    config: "Config | None" = None,
    registry: "IntegrationRegistry | None" = None,
) -> UnlockDispatchResult[LaunchResult]:
    """Launch once after a bounded wait for the resolved iPad to be unlocked.

    The explicit or configured device is resolved before lock preflight.  If
    neither is available, connected-device discovery runs once.  The resolved
    identifier is passed to :func:`open_ipad`, preventing a second discovery.
    A sent launch is returned or raised directly and is never retried.
    """
    _validate_open_request(target, url=url, device=device, timeout=timeout)
    config, registry = _control_context(config, registry)
    device_id = _resolve_device(device, config, timeout)

    return dispatch_when_unlocked(
        device_id,
        lambda: open_ipad(
            target,
            url=url,
            device=device_id,
            terminate=terminate,
            timeout=timeout,
            config=config,
            registry=registry,
        ),
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        lock_check_timeout=lock_check_timeout,
    )


def open_validated_route_when_unlocked(
    route: "ValidatedURLRoute",
    *,
    device: str | None = None,
    terminate: bool = False,
    timeout: float = 15.0,
    wait_timeout: float = 10.0,
    poll_interval: float = 0.25,
    lock_check_timeout: float = 5.0,
    config: "Config | None" = None,
    registry: "IntegrationRegistry | None" = None,
) -> UnlockDispatchResult[LaunchResult]:
    """Dispatch one already validated production route to its exact bundle.

    The route is rebound to the active indexed policy before device discovery.
    The concrete device is then resolved once, checked for unlock, and passed to
    one CoreDevice subprocess.  No retry occurs after dispatch.
    """
    from ipad_agent.core.urlroutes import ValidatedURLRoute, revalidate_validated_route

    if not isinstance(route, ValidatedURLRoute):
        raise TypeError("route must be a ValidatedURLRoute")
    if not isinstance(terminate, bool):
        raise TypeError("terminate must be a bool")
    config, registry = _control_context(config, registry)
    integration = registry.resolve(route.integration_id)
    if integration.bundle_id != route.bundle_id or integration.url_policy is None:
        raise ValueError("validated route target does not match the indexed integration")
    revalidate_validated_route(integration.url_policy, route)
    _validate_open_request(route.bundle_id, url=route.url, device=device, timeout=timeout)
    device_id = _resolve_device(device, config, timeout)
    return dispatch_when_unlocked(
        device_id,
        lambda: open_ipad(
            route.bundle_id,
            url=route.url,
            device=device_id,
            terminate=terminate,
            timeout=timeout,
            config=config,
            registry=registry,
        ),
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        lock_check_timeout=lock_check_timeout,
    )


def _validate_open_request(
    target: str,
    *,
    url: str | None,
    device: str | None,
    timeout: float,
) -> None:
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target must be a non-empty string")
    if url is not None and (not isinstance(url, str) or not url.strip()):
        raise ValueError("url must be a non-empty string when provided")
    if device is not None and (not isinstance(device, str) or not device.strip()):
        raise ValueError("device must be a non-empty string when provided")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")


def _resolve_device(device: str | None, config: "Config", timeout: float) -> str:
    selected = device if device is not None else config.device
    if selected is None:
        return _single_connected_ipad(timeout)
    candidates = _paired_physical_ipads(timeout)
    requested = selected.strip()
    matches = [identifier for identifier, aliases in candidates if requested in aliases]
    if len(matches) != 1:
        raise IPadControlError("Configured device is not one paired physical iPad")
    return matches[0]


def open_ipad(
    target: str,
    *,
    url: str | None = None,
    device: str | None = None,
    terminate: bool = False,
    timeout: float = 15.0,
    config: "Config | None" = None,
    registry: "IntegrationRegistry | None" = None,
) -> LaunchResult:
    """Launch an installed iPad app, optionally delivering a URL payload.

    ``target`` may be an enabled registry alias, an exact bundle ID, or an
    installed-app display name.  When ``device`` is omitted, the configured
    device is used or exactly one connected physical iPad must exist.
    The command uses CoreDevice directly: it does not start XCTest and does not
    display Apple's Automation Running overlay.
    """
    _validate_open_request(target, url=url, device=device, timeout=timeout)

    config, registry = _control_context(config, registry)
    device_id = _resolve_device(device, config, timeout)
    normalized_target = target.strip()
    bundle_id = _bundle_for_target(normalized_target, config, registry)
    if bundle_id is None:
        bundle_id = normalized_target if "." in normalized_target else _resolve_installed_app(
            normalized_target, device_id, timeout
        )
    command = [
        "xcrun", "devicectl", "device", "process", "launch",
        "--device", device_id,
    ]
    if terminate:
        command.append("--terminate-existing")
    if url is not None:
        command.extend(["--payload-url", url.strip()])
    command.append(bundle_id)

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise IPadControlError(
            f"CoreDevice launch timed out after {timeout:g} seconds",
            response_lost=True,
        ) from error
    except KeyboardInterrupt as error:
        # subprocess.run may have started devicectl before local cancellation.
        # Preserve one-call semantics and never expose command/device details.
        raise IPadControlError(
            "CoreDevice launch response was lost after dispatch",
            response_lost=True,
        ) from error
    try:
        elapsed = time.perf_counter() - started
        if completed.returncode != 0:
            # Once the launch subprocess has started, its exit status cannot
            # prove that CoreDevice rejected the request before device dispatch.
            # Do not inspect or expose output: it can contain the payload URL,
            # command, or device identifier, and this uncertain mutation must
            # never be replayed automatically.
            raise IPadControlError(
                "CoreDevice launch response was lost after dispatch",
                response_lost=True,
            )
        locked = _device_locked(device_id, min(timeout, 5.0))
        return LaunchResult(bundle_id, device_id, elapsed, url.strip() if url else None, locked)
    except IPadControlError:
        raise
    except BaseException as error:
        # Any local failure or cancellation after the launch process returned
        # cannot prove non-delivery. Keep the error stable and non-replayable.
        raise IPadControlError(
            "CoreDevice launch response was lost after dispatch",
            response_lost=True,
        ) from error


def _device_locked(device_id: str, timeout: float) -> bool | None:
    """Return the CoreDevice passcode lock state, or None if unavailable."""
    # devicectl rejects smaller values, but the subprocess bound follows the
    # caller so a nearly exhausted unlock deadline cannot inherit that minimum.
    devicectl_timeout = max(5.0, timeout)
    with tempfile.NamedTemporaryFile(suffix=".json") as output:
        try:
            completed = subprocess.run(
                [
                    "xcrun", "devicectl", "device", "info", "lockState",
                    "--device", device_id, "--json-output", output.name,
                    "--quiet", "--timeout", f"{devicectl_timeout:g}",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if completed.returncode != 0:
                return None
            payload = json.loads(Path(output.name).read_text())
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return None
    result = payload.get("result") if isinstance(payload, dict) else None
    state = result.get("passcodeRequired") if isinstance(result, dict) else None
    return state if isinstance(state, bool) else None


def _resolve_installed_app(name: str, device_id: str, timeout: float) -> str:
    with tempfile.NamedTemporaryFile(suffix=".json") as output:
        try:
            completed = subprocess.run(
                [
                    "xcrun", "devicectl", "device", "info", "apps",
                    "--device", device_id, "--include-all-apps",
                    "--json-output", output.name,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise IPadControlError(
                f"CoreDevice app discovery timed out after {timeout:g} seconds"
            ) from error
        if completed.returncode != 0:
            # Discovery output can echo device identifiers, app data, paths,
            # and command arguments. It is diagnostic-only private state.
            raise IPadControlError("CoreDevice app discovery failed")
        try:
            payload = json.loads(Path(output.name).read_text())
        except (json.JSONDecodeError, OSError) as error:
            raise IPadControlError("CoreDevice returned invalid app data") from error

    result = payload.get("result") if isinstance(payload, dict) else None
    apps = result.get("apps") if isinstance(result, dict) else None
    if not isinstance(apps, list):
        raise IPadControlError("CoreDevice returned invalid app data")
    needle = name.casefold()
    exact = []
    partial = []
    for app in apps:
        if not isinstance(app, dict):
            continue
        app_name = app.get("name")
        bundle_id = app.get("bundleIdentifier")
        if not isinstance(app_name, str) or not isinstance(bundle_id, str):
            continue
        if needle in {app_name.casefold(), bundle_id.casefold()}:
            exact.append(bundle_id)
        elif needle in app_name.casefold():
            partial.append(bundle_id)
    matches = list(dict.fromkeys(exact or partial))
    if not matches:
        raise IPadControlError(f"No installed app matches {name!r}")
    if len(matches) > 1:
        raise IPadControlError(
            f"Multiple installed apps match {name!r}; pass an exact bundle ID"
        )
    return matches[0]


def _paired_physical_ipads(timeout: float) -> list[tuple[str, set[str]]]:
    """Return canonical identifiers and aliases for paired physical iPads only."""
    with tempfile.NamedTemporaryFile(suffix=".json") as output:
        try:
            completed = subprocess.run(
                ["xcrun", "devicectl", "list", "devices", "--json-output", output.name],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise IPadControlError(
                f"CoreDevice device discovery timed out after {timeout:g} seconds"
            ) from error
        if completed.returncode != 0:
            raise IPadControlError("CoreDevice device discovery failed")
        try:
            payload = json.loads(Path(output.name).read_text())
        except (json.JSONDecodeError, OSError) as error:
            raise IPadControlError("CoreDevice returned invalid device data") from error

    result = payload.get("result") if isinstance(payload, dict) else None
    devices = result.get("devices") if isinstance(result, dict) else None
    if not isinstance(devices, list):
        raise IPadControlError("CoreDevice returned invalid device data")
    matches: list[tuple[str, set[str]]] = []
    for item in devices:
        if not isinstance(item, dict):
            continue
        hardware = item.get("hardwareProperties", {})
        connection = item.get("connectionProperties", {})
        if not isinstance(hardware, dict) or not isinstance(connection, dict):
            continue
        identifier = item.get("identifier")
        if (
            hardware.get("deviceType") != "iPad"
            or hardware.get("reality") != "physical"
            or connection.get("pairingState") != "paired"
            or not isinstance(identifier, str)
            or not identifier
        ):
            continue
        aliases = {identifier}
        udid = hardware.get("udid")
        if isinstance(udid, str) and udid:
            aliases.add(udid)
        matches.append((identifier, aliases))
    return matches


def _single_connected_ipad(timeout: float) -> str:
    """Compatibility helper requiring exactly one paired physical iPad."""
    candidates = _paired_physical_ipads(timeout)
    if not candidates:
        raise IPadControlError("No paired physical iPad was found")
    if len(candidates) > 1:
        raise IPadControlError("Multiple paired iPads found; configure one exact device")
    return candidates[0][0]


__all__ = [
    "IPadControlError",
    "LaunchResult",
    "UnlockDispatchResult",
    "UnlockState",
    "dispatch_when_unlocked",
    "open_ipad",
    "open_ipad_when_unlocked",
    "open_validated_route_when_unlocked",
    "wait_for_ipad_unlocked",
]
