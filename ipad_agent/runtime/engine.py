#!/usr/bin/env python3
"""Small, persistent Unix-socket runtime for CoreDevice and XCTest control.

The module imports device backends only when a command needs one.  In particular, importing this file never starts Appium, WDA, or HID.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import socket
import stat
import subprocess
import sys
import time
from typing import Any

from ipad_agent.core.operations import (
    OperationError, OperationPhase, OperationResult, OperationSpec, SafetyClass,
)
from ipad_agent.core.projection import public_result

PACKAGE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
from ipad_agent.core.paths import (
    descriptor_has_extended_acl,
    has_extended_acl,
    private_mkdir,
    private_runtime_socket_path,
    private_write_bytes,
    private_write_text,
    require_runtime_artifact_path,
    require_runtime_path,
    runtime_path,
)

DEFAULT_SOCKET_PATH = private_runtime_socket_path(REPOSITORY_ROOT)
DEFAULT_IDLE_TTL = 600.0
MAX_REQUEST_BYTES = 1024 * 1024
RUNTIME_PROTOCOL = "ipad-agent.runtime/v1"
SOCKET_OWNER_SCHEMA = "ipad-agent.runtime-socket-owner/v1"
SOCKET_OWNER = "ipad-agent"
_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
_REGISTRY_SNAPSHOT_SCHEMA = "ipad-agent.registry-snapshot/v2"


def _env_float(name: str, default: float, *, minimum: float = 0.01) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _compact_error(error: BaseException) -> str:
    message = " ".join(str(error).split()) or error.__class__.__name__
    return message[:500]


class RuntimeTeardownError(RuntimeError):
    """Persistent fail-closed state after one incomplete WDA teardown."""

    code = "wda_cleanup_incomplete"

    def __init__(self, cause: BaseException | None = None) -> None:
        super().__init__(
            "WDA teardown is incomplete; session ownership and context are retained "
            "for recovery, and further mutations are blocked"
        )
        self.uncertain = bool(getattr(cause, "uncertain", False))
        self.dispatched = bool(getattr(cause, "dispatched", False))


def _registry_contract(registry: Any) -> dict[str, Any]:
    """Return the deterministic registry surface used by runtime routing."""
    from ipad_agent.core.registry import IntegrationRegistry

    if not isinstance(registry, IntegrationRegistry):
        raise ValueError("runtime registry must be an IntegrationRegistry")
    integrations = []
    for integration_id in sorted(registry.integrations):
        integration = registry.integrations[integration_id]
        policy = integration.url_policy
        integrations.append({
            "category": integration.category,
            "manifest": integration.to_dict(),
            "url_policy": None if policy is None else {
                "sha256": policy.sha256,
                "normalized": _json_plain(policy.normalized),
            },
        })
    return {
        "enabled_addons": sorted(registry.enabled_addons),
        "integrations": integrations,
        # Disabled-addon index routing is part of resolution too: it decides
        # whether a name is unknown or explicitly gated.
        "disabled_aliases": dict(sorted(registry._disabled_aliases.items())),
        "disabled_bundles": dict(sorted(registry._disabled_bundles.items())),
    }


def _json_plain(value: Any) -> Any:
    """Project immutable policy mappings/tuples to deterministic JSON values."""
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        return {key: _json_plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_plain(item) for item in value]
    return value


def registry_snapshot(registry: Any) -> dict[str, Any]:
    """Serialize and bind manifests plus material URL-policy sidecar bytes."""
    contract = _registry_contract(registry)
    digest = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    policies = {
        integration_id: integration.policy_sha256
        for integration_id, integration in sorted(registry.integrations.items())
        if integration.policy_sha256 is not None
    }
    return {
        "schema": _REGISTRY_SNAPSHOT_SCHEMA,
        "index_path": str(registry.index_path),
        "enabled_addons": list(contract["enabled_addons"]),
        "policy_sha256": policies,
        "contract_sha256": digest,
    }


def registry_from_snapshot(value: Any) -> Any:
    """Strictly reconstruct and verify one detached-runtime registry."""
    if not isinstance(value, dict):
        raise ValueError("registry snapshot must be an object")
    expected = {"schema", "index_path", "enabled_addons", "policy_sha256", "contract_sha256"}
    if set(value) != expected:
        raise ValueError("invalid registry snapshot fields")
    if value.get("schema") != _REGISTRY_SNAPSHOT_SCHEMA:
        raise ValueError("unsupported registry snapshot schema")
    index_path = value.get("index_path")
    addons = value.get("enabled_addons")
    digest = value.get("contract_sha256")
    policy_digests = value.get("policy_sha256")
    if not isinstance(index_path, str) or not index_path or "\x00" in index_path:
        raise ValueError("registry snapshot index_path must be a non-empty path")
    if not isinstance(addons, list) or not all(isinstance(item, str) and item for item in addons):
        raise ValueError("registry snapshot enabled_addons must be an array of strings")
    if addons != sorted(set(addons)):
        raise ValueError("registry snapshot enabled_addons must be sorted and unique")
    if not isinstance(policy_digests, dict) or not all(
        isinstance(key, str) and isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item)
        for key, item in policy_digests.items()
    ):
        raise ValueError("registry snapshot policy digests are invalid")
    if list(policy_digests) != sorted(policy_digests):
        raise ValueError("registry snapshot policy digests must be sorted")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("registry snapshot contract digest is invalid")
    from ipad_agent.core.registry import IntegrationRegistry

    registry = IntegrationRegistry(index_path, enabled_addons=addons)
    actual_snapshot = registry_snapshot(registry)
    actual = actual_snapshot["contract_sha256"]
    if actual_snapshot["policy_sha256"] != policy_digests:
        raise ValueError("registry URL policies changed after caller validation")
    if not secrets.compare_digest(actual, digest):
        raise ValueError("registry contract changed after caller validation")
    return registry


def _runtime_socket_path(path: Path) -> Path | None:
    try:
        return require_runtime_path(path)
    except ValueError:
        return None


def _require_socket_path(socket_path: Path) -> Path:
    """Admit repository-runtime test sockets or this checkout's short endpoint."""
    runtime_candidate = _runtime_socket_path(Path(socket_path))
    if runtime_candidate is not None:
        return runtime_candidate
    candidate = Path(socket_path)
    if ".." in candidate.parts:
        raise ValueError(f"unsafe socket path traversal: {candidate}")
    candidate = Path(os.path.abspath(candidate))
    expected = private_runtime_socket_path(REPOSITORY_ROOT)
    if candidate != expected:
        raise ValueError(f"socket path is outside the private runtime boundary: {candidate}")
    try:
        parent_info = candidate.parent.lstat()
    except FileNotFoundError:
        return candidate
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise ValueError(f"runtime socket parent is not a real directory: {candidate.parent}")
    if hasattr(os, "geteuid") and parent_info.st_uid != os.geteuid():
        raise PermissionError(f"runtime socket parent is not owned by the current user: {candidate.parent}")
    if stat.S_IMODE(parent_info.st_mode) & ~0o700:
        raise PermissionError(f"runtime socket parent is not private: {candidate.parent}")
    if has_extended_acl(candidate.parent):
        raise PermissionError(f"runtime socket parent has an extended ACL: {candidate.parent}")
    return candidate


def _ensure_socket_parent(socket_path: Path) -> None:
    runtime_candidate = _runtime_socket_path(socket_path)
    if runtime_candidate is not None:
        private_mkdir(runtime_candidate.parent)
        return
    path = _require_socket_path(socket_path)
    try:
        os.mkdir(path.parent, 0o700)
    except FileExistsError:
        pass
    # Revalidate after creation (or a creation race) before binding.
    _require_socket_path(path)


def _cleanup_short_socket_parent(socket_path: Path) -> None:
    if _runtime_socket_path(socket_path) is not None:
        return
    try:
        path = _require_socket_path(socket_path)
        path.parent.rmdir()
    except (FileNotFoundError, OSError, ValueError):
        pass


def _socket_metadata_path(socket_path: Path) -> Path:
    path = _require_socket_path(socket_path)
    if _runtime_socket_path(path) is not None:
        return require_runtime_path(path.with_name(path.name + ".owner.json"))
    digest = hashlib.sha256(os.fsencode(path)).hexdigest()[:16]
    return runtime_path("state", f"runtime-socket-{digest}.owner.json")


def _read_private_json(path: Path) -> dict[str, Any] | None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            return None
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            return None
        if stat.S_IMODE(info.st_mode) & ~0o600:
            return None
        if descriptor_has_extended_acl(descriptor):
            return None
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return value if isinstance(value, dict) else None


def _owned_socket_metadata(socket_path: Path) -> dict[str, Any] | None:
    """Return metadata only when it proves this exact private socket endpoint."""
    try:
        path = _require_socket_path(socket_path)
        socket_info = path.lstat()
    except (OSError, ValueError):
        return None
    if not stat.S_ISSOCK(socket_info.st_mode):
        return None
    if hasattr(os, "geteuid") and socket_info.st_uid != os.geteuid():
        return None
    if stat.S_IMODE(socket_info.st_mode) & ~0o600:
        return None
    if has_extended_acl(path):
        return None
    value = _read_private_json(_socket_metadata_path(path))
    if value is None:
        return None
    expected = {"schema", "owner", "protocol", "nonce", "socket", "inode", "pid", "uid"}
    nonce = value.get("nonce")
    valid = (
        set(value) == expected
        and value.get("schema") == SOCKET_OWNER_SCHEMA
        and value.get("owner") == SOCKET_OWNER
        and value.get("protocol") == RUNTIME_PROTOCOL
        and isinstance(nonce, str) and _NONCE_RE.fullmatch(nonce) is not None
        and value.get("socket") == str(path)
        and value.get("inode") == socket_info.st_ino
        and isinstance(value.get("pid"), int) and value["pid"] > 1
        and value.get("uid") == (os.geteuid() if hasattr(os, "geteuid") else socket_info.st_uid)
    )
    return value if valid else None


def _authenticated_payload(payload: dict[str, Any], nonce: str) -> dict[str, Any]:
    value = dict(payload)
    value["_protocol"] = RUNTIME_PROTOCOL
    value["_nonce"] = nonce
    return value


def _probe_owned_daemon_state(socket_path: Path, metadata: dict[str, Any]) -> str:
    """Return authenticated, occupied, or stale without dispatching a device op."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connected = False
    try:
        sock.settimeout(CLIENT_CONNECT_TIMEOUT if "CLIENT_CONNECT_TIMEOUT" in globals() else 0.35)
        sock.connect(str(socket_path))
        connected = True
        probe = _authenticated_payload({"_probe": True}, metadata["nonce"])
        sock.sendall((json.dumps(probe, separators=(",", ":")) + "\n").encode())
        raw = _recv_line(sock)
        value = json.loads(raw)
        authenticated = (
            isinstance(value, dict)
            and value.get("ok") is True
            and value.get("_protocol") == RUNTIME_PROTOCOL
            and secrets.compare_digest(str(value.get("_nonce") or ""), metadata["nonce"])
        )
        return "authenticated" if authenticated else "occupied"
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        # A listener that accepted a connection may be wedged, but it is not a
        # stale pathname and must never be unlinked from under that process.
        return "occupied" if connected else "stale"
    finally:
        sock.close()


def _probe_owned_daemon(socket_path: Path, metadata: dict[str, Any]) -> bool:
    return _probe_owned_daemon_state(socket_path, metadata) == "authenticated"


def response(ok: bool, started: float, path: str, *, error: str | None = None, result: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "ms": max(0, round((time.perf_counter() - started) * 1000)),
        "path": path,
    }
    if error:
        payload["error"] = error
    if result is not None:
        payload["result"] = result
    return payload


def _execution_failure(
    error: BaseException, operation: OperationSpec, started: float, path: str
) -> dict[str, Any]:
    details: dict[str, Any] = {"type": type(error).__name__}
    if isinstance(getattr(error, "code", None), str):
        details["transport_code"] = error.code
    if isinstance(getattr(error, "dispatched", None), bool):
        details["dispatched"] = error.dispatched
    structured = OperationError(
        str(getattr(error, "code", None) or "execution_failed"),
        _compact_error(error),
        details,
    )
    outcome = (
        OperationResult.response_lost(operation, structured)
        if getattr(error, "uncertain", False) is True
        else OperationResult.failed(operation, structured)
    )
    payload = outcome.to_plain_result()
    payload["ms"] = max(0, round((time.perf_counter() - started) * 1000))
    payload["path"] = path
    return payload


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)


class Runtime:
    """One serialized command executor and one lazily-held XCTest context."""

    def __init__(self, *, idle_ttl: float = DEFAULT_IDLE_TTL, config: Any = None, registry: Any = None) -> None:
        if idle_ttl <= 0:
            raise ValueError("idle TTL must be greater than zero")
        self.idle_ttl = idle_ttl
        self.config = config
        self.registry = registry
        self.session: Any = None
        self._session_context: Any = None
        self._last_used: float | None = None
        self.active_app: str | None = None
        self._element_cache: dict[tuple[str, str], str] = {}
        self._wda_default_app: str | None = None
        self._teardown_failure: dict[str, Any] | None = None
        self._teardown_exception: RuntimeTeardownError | None = None

    def configure(self, config: Any, registry: Any = None) -> None:
        """Install one validated request snapshot without touching the environment."""
        from ipad_agent.core.config import Config
        from ipad_agent.core.registry import IntegrationRegistry, load_registry

        if not isinstance(config, Config):
            raise ValueError("runtime config must be a Config")
        selected_registry = (
            registry if registry is not None
            else load_registry(enabled_addons=config.enabled_addons)
        )
        if not isinstance(selected_registry, IntegrationRegistry):
            raise ValueError("runtime registry must be an IntegrationRegistry")
        if self.session is not None and self.config is not None:
            config_changed = config != self.config
            registry_changed = (
                self.registry is None
                or registry_snapshot(selected_registry) != registry_snapshot(self.registry)
            )
            if config_changed or registry_changed:
                raise RuntimeError("cannot change daemon configuration while an XCTest session is active")
        self.config = config
        self.registry = selected_registry

    def _ensure_context(self) -> tuple[Any, Any]:
        if self.config is None:
            from ipad_agent.core.config import load_config
            self.configure(load_config())
        elif self.registry is None:
            self.configure(self.config)
        return self.config, self.registry

    @property
    def hot(self) -> bool:
        return self.session is not None

    def _raise_teardown_failure(self) -> None:
        if self._teardown_exception is not None:
            raise self._teardown_exception

    def _expire(self) -> None:
        self._raise_teardown_failure()
        if self.session is not None and self._last_used is not None:
            if time.monotonic() - self._last_used >= self.idle_ttl:
                self.teardown()

    def status(self) -> dict[str, Any]:
        try:
            self._expire()
        except RuntimeTeardownError:
            # The failed state is the status. Do not retry context exit.
            pass
        idle = None if self._last_used is None else max(0.0, time.monotonic() - self._last_used)
        teardown = self._teardown_failure or {
            "state": "pending" if self.hot else "not_pending",
            "recoverable": False,
        }
        return {
            "daemon": True,
            "healthy": self._teardown_failure is None,
            "session": self.hot,
            "app": self.active_app,
            "idle_s": round(idle, 1) if idle is not None else None,
            "ttl_s": self.idle_ttl,
            "teardown": dict(teardown),
        }

    def ensure_session(self) -> Any:
        self._raise_teardown_failure()
        self._expire()
        if self.session is not None:
            self._last_used = time.monotonic()
            return self.session
        # This is the only path that imports/discovers XCTest or opens WDA.
        from ipad_agent.transports import wda

        runtime_config, _registry = self._ensure_context()
        config_timeout = _env_float("IPAD_AGENT_RUNTIME_DISCOVERY_TIMEOUT", 30.0)
        session_timeout = _env_float("IPAD_AGENT_RUNTIME_SESSION_TIMEOUT", 180.0)
        device = wda._discover_ipad(config_timeout, runtime_config.device)
        team = runtime_config.team_id
        wda_bundle = runtime_config.wda_bundle_id
        configured_xctestrun = runtime_config.xctestrun
        if not all(isinstance(value, str) and value for value in (team, wda_bundle, configured_xctestrun)):
            raise wda.XCTestControlError(
                "Normal runtime requires setup-owned WDA team, bundle, and xctestrun state; "
                "run: python3 -m ipad_agent setup --phase wda --apply --json",
                code="wda_setup_required",
            )
        selection = wda.make_selection(device=device, team=team, bundle_id=wda_bundle)
        artifact = wda.validate_artifact(
            wda.artifact_directory(selection), selection=selection
        )
        if configured_xctestrun != artifact["xctestrun"]:
            raise wda.XCTestControlError(
                "Configured xctestrun is not the setup-owned artifact for the current selection; "
                "run: python3 -m ipad_agent setup --phase wda --apply --json",
                code="wda_setup_required",
            )
        if not wda.verified(selection):
            raise wda.XCTestControlError(
                "The current setup-owned WDA artifact has no unexpired bounded-session verification; "
                "run: python3 -m ipad_agent setup --phase verify --apply --json",
                code="wda_verification_required",
            )
        xctest_config = wda.XCTestConfig(
            udid=device["udid"],
            platform_version=device["version"],
            development_team=team,
            bootstrap_path=str(Path(artifact["xctestrun"]).parent),
            wda_bundle_id=wda_bundle,
            appium_url=runtime_config.appium_url,
        )
        context = wda.short_session(xctest_config, timeout=session_timeout)
        # short_session owns teardown once its __enter__ succeeds.
        session = context.__enter__()
        self._session_context = context
        self.session = session
        self._last_used = time.monotonic()
        # CoreDevice launches may happen before this daemon exists. One cheap
        # active-app query makes short aliases resolve correctly after heating.
        try:
            info = session.execute("mobile: activeAppInfo", {}, timeout=2.0)
            bundle = info.get("bundleId") if isinstance(info, dict) else None
            if isinstance(bundle, str) and bundle:
                self.active_app = bundle
        except Exception:
            pass
        return session

    def touch(self) -> None:
        self._last_used = time.monotonic()

    def teardown(self) -> None:
        self._raise_teardown_failure()
        context = self._session_context
        if context is not None:
            # Exactly one exit attempt. On failure keep the context, session,
            # owner receipt, and teardown evidence intact for explicit recovery.
            try:
                context.__exit__(None, None, None)
            except Exception as error:
                failure = RuntimeTeardownError(error)
                self._teardown_exception = failure
                self._teardown_failure = {
                    "state": "failed",
                    "code": failure.code,
                    "recoverable": True,
                    "session_ownership_retained": self.session is not None,
                    "context_retained": self._session_context is context,
                    "mutations_blocked": True,
                }
                raise failure from error
        self._session_context = None
        self.session = None
        self._last_used = None
        self._element_cache.clear()
        self._wda_default_app = None
        self._teardown_failure = None
        self._teardown_exception = None

    def open_app(self, target: str, url: str | None = None):
        from ipad_agent.transports.coredevice import open_ipad

        config, registry = self._ensure_context()
        timeout = _env_float("IPAD_AGENT_RUNTIME_COREDEVICE_TIMEOUT", 15.0)
        result = open_ipad(
            target, url=url, device=config.device, timeout=timeout,
            config=config, registry=registry,
        )
        self.active_app = result.bundle_id
        self._element_cache.clear()
        if self.session is not None:
            # Multiwindow iPadOS may report a Dock/Files view service at WDA's
            # detection point even when the requested app is visible. Pin WDA
            # queries to the intended bundle instead of guessing from geometry.
            self._set_default_application(result.bundle_id)
            self.touch()
        return result

    def _set_default_application(self, bundle_id: str) -> None:
        if self.session is None or self._wda_default_app == bundle_id:
            return
        self.session._request(
            "POST",
            "/appium/settings",
            {"settings": {"defaultActiveApplication": bundle_id}},
            5.0,
        )
        self._wda_default_app = bundle_id

    def selector(self, value: str) -> dict[str, Any]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("selector must be non-empty")
        value = value.strip()
        _, registry = self._ensure_context()
        from ipad_agent.core.registry import AddonNotEnabledError
        # Qualified selectors and selectors for the active app are supplied by
        # the explicit integration registry.  Unknown literals remain useful
        # for one-off controls without becoming persistent aliases.
        try:
            return registry.resolve_selector(value)
        except AddonNotEnabledError:
            raise
        except (KeyError, ValueError):
            pass
        if self.active_app:
            try:
                return registry.resolve_selector(self.active_app, value)
            except AddonNotEnabledError:
                raise
            except (KeyError, ValueError):
                pass
        # Useful for one-off controls without making element IDs persistent.
        for prefix, using in (
            ("accessibility id=", "accessibility id"),
            ("accessibility=", "accessibility id"),
            ("xpath=", "xpath"),
            ("predicate=", "-ios predicate string"),
            ("class=", "class name"),
        ):
            if value.casefold().startswith(prefix):
                literal = value[len(prefix):]
                if literal:
                    return {"using": using, "value": literal}
        return {"using": "accessibility id", "value": value}

    def _find(self, selector: str) -> tuple[Any, dict[str, Any]]:
        session = self.ensure_session()
        recipe = self.selector(selector)
        bundle = recipe.get("_bundle")
        if isinstance(bundle, str):
            self._set_default_application(bundle)
        cache_key = ((bundle or self.active_app or "").casefold(), selector)
        if recipe.get("cache") is True and cache_key in self._element_cache:
            return self._element_cache[cache_key], recipe
        timeout = _env_float("IPAD_AGENT_RUNTIME_COMMAND_TIMEOUT", 10.0)
        element = session.find(recipe["using"], recipe["value"], timeout=timeout)
        if element is not None and recipe.get("cache") is True:
            self._element_cache[cache_key] = element
        return element, recipe

    def tap_selector(self, selector: str) -> None:
        element, recipe = self._find(selector)
        if element is None:
            if isinstance(recipe.get("x"), (int, float)) and isinstance(recipe.get("y"), (int, float)):
                self.tap_point(float(recipe["x"]), float(recipe["y"]))
                return
            raise RuntimeError(f"control not found: {selector}")
        try:
            self.session.click(element, timeout=_env_float("IPAD_AGENT_RUNTIME_COMMAND_TIMEOUT", 10.0))
        except Exception:
            bundle = recipe.get("_bundle")
            cache_key = ((bundle or self.active_app or "").casefold(), selector)
            self._element_cache.pop(cache_key, None)
            # Never retry a tap: an interrupted response does not prove the
            # device failed to execute it.
            raise

    def tap_point(self, x: float, y: float) -> None:
        if not (0 <= x <= 4096 and 0 <= y <= 4096):
            raise ValueError("tap coordinates must be between 0 and 4096")
        session = self.ensure_session()
        session.execute("mobile: tap", {"x": x, "y": y}, timeout=_env_float("IPAD_AGENT_RUNTIME_COMMAND_TIMEOUT", 10.0))

    def clear_type(self, selector: str, text: str) -> None:
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        element, _ = self._find(selector)
        if element is None:
            raise RuntimeError(f"control not found: {selector}")
        timeout = _env_float("IPAD_AGENT_RUNTIME_COMMAND_TIMEOUT", 10.0)
        self.session.clear(element, timeout=timeout)
        self.session.type(element, text, timeout=timeout)

    def type_active(self, text: str) -> None:
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        session = self.ensure_session()
        timeout = _env_float("IPAD_AGENT_RUNTIME_COMMAND_TIMEOUT", 10.0)
        key = "element-6066-11e4-a52e-4f735466cecf"
        try:
            active = session._request("GET", "/element/active", None, timeout)
        except Exception as error:
            raise RuntimeError(f"active element is unsupported: {_compact_error(error)}") from error
        # AppiumSession._request already unwraps the WDA response's value;
        # accept the outer shape too for alternate compatible backends.
        element = None
        if isinstance(active, dict):
            element = active.get(key)
            if element is None and isinstance(active.get("value"), dict):
                element = active["value"].get(key)
        if not element:
            raise RuntimeError("no active element")
        session.type(element, text, timeout=timeout)

    def swipe(self, direction: str, count: int = 1) -> None:
        if direction not in {"left", "right", "up", "down"}:
            raise ValueError("swipe direction must be left, right, up, or down")
        if count < 1 or count > 20:
            raise ValueError("swipe count must be between 1 and 20")
        session = self.ensure_session()
        timeout = _env_float("IPAD_AGENT_RUNTIME_COMMAND_TIMEOUT", 10.0)
        for _ in range(count):
            session.execute("mobile: swipe", {"direction": direction}, timeout=timeout)

    def ready(self, selector: str, seconds: float = 5.0) -> None:
        if seconds < 0 or seconds > 120:
            raise ValueError("readiness timeout must be between 0 and 120 seconds")
        session = self.ensure_session()
        recipe = self.selector(selector)
        bundle = recipe.get("_bundle")
        if isinstance(bundle, str):
            self._set_default_application(bundle)
        element = session.wait_find(recipe["using"], recipe["value"], timeout=seconds)
        if element is None:
            raise RuntimeError(f"control not ready: {selector}")

    def screenshot(self, output: str | None = None) -> str:
        if output is not None and (not isinstance(output, str) or not output.strip()):
            raise ValueError("screenshot output must be a non-empty path string")
        target = require_runtime_artifact_path(output or "ipad-latest.png")
        # Validate output authority before contacting WDA.  Invalid paths must
        # remain a certain, pre-dispatch rejection.
        session = self.ensure_session()
        encoded = session._request(
            "GET", "/screenshot", None, _env_float("IPAD_AGENT_RUNTIME_COMMAND_TIMEOUT", 10.0)
        )
        if not isinstance(encoded, str):
            raise RuntimeError("WDA returned no screenshot")
        payload = base64.b64decode(encoded, validate=True)
        private_write_bytes(target, payload)
        return str(target)

    def execute(self, request: dict[str, Any]) -> tuple[str, Any, bool]:
        """Execute one wire request. Return (path, result, stop_daemon)."""
        op = request.get("op")
        if not isinstance(op, str):
            raise ValueError("request requires an opcode")
        op = op.casefold()
        if self._teardown_failure is not None and op not in {"q", "x"}:
            self._raise_teardown_failure()
        if op == "o":
            target = request.get("app")
            if not isinstance(target, str) or not target.strip():
                raise ValueError("o requires APP")
            url = request.get("url")
            if url is not None:
                raise ValueError(
                    "raw URL opcode dispatch is unsupported; use a declared semantic integration command"
                )
            launch = self.open_app(target, None)
            return "coredevice", {"bundle": launch.bundle_id, "device": launch.device_id, "locked": launch.locked}, False
        if op == "h":
            self.ensure_session()
            self.touch()
            return "wda", {"session": True}, False
        if op == "q":
            return "status", self.status(), False
        if op == "x":
            self.teardown()
            return "daemon", {"stopped": True}, True
        if op == "t":
            self.tap_selector(_required_string(request, "selector"))
            self.touch()
            return "wda", None, False
        if op == "p":
            self.tap_point(_number(request, "x"), _number(request, "y"))
            self.touch()
            return "wda", None, False
        if op == "y":
            self.clear_type(_required_string(request, "selector"), _required_string(request, "text"))
            self.touch()
            return "wda", None, False
        if op == "k":
            self.type_active(_required_string(request, "text"))
            self.touch()
            return "wda", None, False
        if op == "s":
            count = request.get("count", 1)
            if isinstance(count, bool) or not isinstance(count, int):
                raise ValueError("swipe count must be an integer")
            self.swipe(_required_string(request, "direction"), count)
            self.touch()
            return "wda", None, False
        if op == "w":
            seconds = request.get("seconds", 5.0)
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
                raise ValueError("readiness timeout must be numeric")
            self.ready(_required_string(request, "selector"), float(seconds))
            self.touch()
            return "wda", None, False
        if op == "c":
            output = request.get("output")
            if output is not None and not isinstance(output, str):
                raise ValueError("screenshot output must be a path string")
            path = self.screenshot(output)
            self.touch()
            return "wda", {"file": path}, False
        if op == "b":
            batch = request.get("batch")
            if not isinstance(batch, list):
                raise ValueError("b requires a JSON array")
            if not batch or len(batch) > 20:
                raise ValueError("batch must contain between 1 and 20 commands")
            results: list[dict[str, Any]] = []
            stop_daemon = False
            for item in batch:
                child_started = time.perf_counter()
                child: dict[str, Any] | None = None
                child_operation: OperationSpec | None = None
                try:
                    child = wire_request(item)
                    if str(child.get("op", "")).casefold() == "b":
                        raise ValueError("nested batches are not allowed")
                    child_operation = _operation_for_request(child)
                    child_path, child_result, should_stop = self.execute(child)
                    child_payload = response(True, child_started, child_path, result=child_result)
                    child_payload["_operation"] = OperationResult.succeeded(
                        child_operation, child_payload
                    ).projection_metadata
                    results.append(child_payload)
                except Exception as error:
                    path = _path_for_request(child)
                    if child_operation is not None:
                        results.append(_execution_failure(error, child_operation, child_started, path))
                    else:
                        results.append(response(False, child_started, path, error=_compact_error(error)))
                    break
                if should_stop:
                    stop_daemon = True
                    break
            return "batch", results, stop_daemon
        raise ValueError(f"unknown opcode: {op}")


def _required_string(request: dict[str, Any], name: str) -> str:
    value = request.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _number(request: dict[str, Any], name: str) -> float:
    value = request.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _path_for_request(request: Any) -> str:
    if isinstance(request, dict):
        op = request.get("op")
        if isinstance(op, str):
            return {"o": "coredevice", "q": "status", "x": "daemon", "b": "batch"}.get(op.casefold(), "wda")
    return "runtime"


def wire_request(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if isinstance(item, list) and item and all(isinstance(part, str) for part in item):
        return argv_request(item)
    if isinstance(item, str):
        return argv_request(shlex.split(item))
    raise ValueError("batch entries must be opcode strings, argument arrays, or objects")


def argv_request(args: list[str]) -> dict[str, Any]:
    if not args:
        raise ValueError("missing opcode")
    op = args[0].casefold()
    if op == "o" and len(args) in (2, 3):
        return {"op": op, "app": args[1], "url": args[2] if len(args) == 3 else None}
    if op in {"h", "q", "x"} and len(args) == 1:
        return {"op": op}
    if op == "t" and len(args) == 2:
        return {"op": op, "selector": args[1]}
    if op == "p" and len(args) == 3:
        return {"op": op, "x": float(args[1]), "y": float(args[2])}
    if op == "y" and len(args) == 3:
        return {"op": op, "selector": args[1], "text": args[2]}
    if op == "k" and len(args) == 2:
        return {"op": op, "text": args[1]}
    if op == "s" and len(args) in (2, 3):
        return {"op": op, "direction": args[1], "count": int(args[2]) if len(args) == 3 else 1}
    if op == "w" and len(args) in (2, 3):
        return {"op": op, "selector": args[1], "seconds": float(args[2]) if len(args) == 3 else 5.0}
    if op == "c" and len(args) in (1, 2):
        return {"op": op, "output": args[1] if len(args) == 2 else None}
    if op == "b" and len(args) == 2:
        batch = json.loads(args[1])
        return {"op": op, "batch": batch}
    raise ValueError("invalid opcode or arguments")


class Daemon:
    def __init__(self, socket_path: Path, *, idle_ttl: float, nonce: str | None = None) -> None:
        self.socket_path = _require_socket_path(socket_path)
        self.runtime = Runtime(idle_ttl=idle_ttl)
        self.stop = False
        self._listener: socket.socket | None = None
        self._socket_inode: int | None = None
        selected_nonce = nonce or secrets.token_hex(32)
        if not isinstance(selected_nonce, str) or _NONCE_RE.fullmatch(selected_nonce) is None:
            raise ValueError("daemon nonce must be 64 lowercase hexadecimal characters")
        self.nonce = selected_nonce

    def _bind(self) -> socket.socket:
        _ensure_socket_parent(self.socket_path)
        try:
            self.socket_path.lstat()
        except FileNotFoundError:
            endpoint_exists = False
        else:
            endpoint_exists = True
        if endpoint_exists:
            ownership = _owned_socket_metadata(self.socket_path)
            if ownership is None:
                raise RuntimeError(f"refusing to replace unowned socket at {self.socket_path}")
            probe_state = _probe_owned_daemon_state(self.socket_path, ownership)
            if probe_state != "stale":
                detail = "already running" if probe_state == "authenticated" else "is occupied"
                raise RuntimeError(f"daemon {detail} at {self.socket_path}")
            # Revalidate after the failed connection.  Only the exact socket
            # proven by its private owner receipt may be treated as stale.
            current = _owned_socket_metadata(self.socket_path)
            if current != ownership:
                raise RuntimeError(f"socket ownership changed during stale check at {self.socket_path}")
            if not _unlink_socket_inode(self.socket_path, ownership["inode"]):
                raise RuntimeError(f"socket ownership changed during stale removal at {self.socket_path}")
            _unlink_metadata_if_equal(_socket_metadata_path(self.socket_path), ownership)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound_inode: int | None = None
        try:
            listener.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            socket_info = self.socket_path.lstat()
            if not stat.S_ISSOCK(socket_info.st_mode):
                raise RuntimeError("bound runtime endpoint is not a socket")
            bound_inode = socket_info.st_ino
            self._socket_inode = bound_inode
            listener.listen(8)
            listener.settimeout(0.5)
            owner = {
                "schema": SOCKET_OWNER_SCHEMA,
                "owner": SOCKET_OWNER,
                "protocol": RUNTIME_PROTOCOL,
                "nonce": self.nonce,
                "socket": str(self.socket_path),
                "inode": socket_info.st_ino,
                "pid": os.getpid(),
                "uid": os.geteuid() if hasattr(os, "geteuid") else socket_info.st_uid,
            }
            private_write_text(
                _socket_metadata_path(self.socket_path),
                json.dumps(owner, sort_keys=True, separators=(",", ":")),
            )
        except Exception:
            listener.close()
            if bound_inode is not None:
                ownership = _owned_socket_metadata(self.socket_path)
                if ownership is not None and ownership.get("nonce") == self.nonce:
                    _unlink_socket_inode(self.socket_path, bound_inode)
                    _unlink_metadata_if_equal(_socket_metadata_path(self.socket_path), ownership)
                else:
                    # Receipt creation may itself have failed.  Remove only the
                    # exact socket inode created by this bind attempt.
                    _unlink_socket_inode(self.socket_path, bound_inode)
            _cleanup_short_socket_parent(self.socket_path)
            raise
        self._listener = listener
        return listener

    def serve(self) -> None:
        listener = self._bind()
        try:
            while not self.stop:
                try:
                    self.runtime._expire()
                except RuntimeTeardownError:
                    # Retained failure remains queryable through status. Never
                    # retry the teardown mutation from the idle loop.
                    pass
                try:
                    conn, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._handle(conn)
        finally:
            shutdown_error: Exception | None = None
            try:
                self.runtime.teardown()
            except Exception as error:
                shutdown_error = error
            with contextlib.suppress(OSError):
                listener.close()
            # Only the daemon that bound this authenticated endpoint removes
            # it.  Both nonce and inode must still match its owner receipt.
            ownership = _owned_socket_metadata(self.socket_path)
            if (
                ownership is not None
                and ownership.get("nonce") == self.nonce
                and ownership.get("inode") == self._socket_inode
                and _unlink_socket_inode(self.socket_path, self._socket_inode)
            ):
                _unlink_metadata_if_equal(_socket_metadata_path(self.socket_path), ownership)
            _cleanup_short_socket_parent(self.socket_path)
            if shutdown_error is not None:
                raise RuntimeError(
                    "daemon shutdown failed because WDA teardown is incomplete; "
                    "owned recovery state was not reported clean"
                ) from shutdown_error

    def _handle(self, conn: socket.socket) -> None:
        started = time.perf_counter()
        request: Any = None
        authenticated = False
        try:
            conn.settimeout(_env_float("IPAD_AGENT_RUNTIME_SOCKET_TIMEOUT", 240.0))
            raw = _recv_line(conn)
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            supplied_nonce = request.get("_nonce")
            authenticated = (
                request.get("_protocol") == RUNTIME_PROTOCOL
                and isinstance(supplied_nonce, str)
                and secrets.compare_digest(supplied_nonce, self.nonce)
            )
            if not authenticated:
                raise PermissionError("runtime protocol authentication failed")
            if request.get("_probe") is True:
                if set(request) != {"_probe", "_protocol", "_nonce"}:
                    raise ValueError("protocol probe cannot carry a command")
                payload = response(True, started, "protocol", result={"daemon": True})
            else:
                if "browser_bundle" in request or "_browser_bundle" in request:
                    raise ValueError(
                        "legacy browser_bundle runtime fields are unsupported; use a v2 config snapshot"
                    )
                if "_config" not in request or "_registry" not in request:
                    raise ValueError("runtime request requires config and registry snapshots")
                from ipad_agent.core.config import config_from_snapshot

                config = config_from_snapshot(request["_config"])
                registry = registry_from_snapshot(request["_registry"])
                self.runtime.configure(config, registry)
                # Parsing the structural operation contract is also the
                # authority gate for protected and persistent requests.
                operation = _operation_for_request(request)
                try:
                    path, result, should_stop = self.runtime.execute(request)
                except Exception as error:
                    payload = _execution_failure(
                        error, operation, started, _path_for_request(request)
                    )
                else:
                    batch_failed = path == "batch" and isinstance(result, list) and any(
                        isinstance(item, dict) and item.get("ok") is not True for item in result
                    )
                    payload = response(
                        not batch_failed,
                        started,
                        path,
                        error="batch stopped on failed command" if batch_failed else None,
                        result=result,
                    )
                    payload["_operation"] = OperationResult.succeeded(
                        operation, payload
                    ).projection_metadata
                    if path == "batch" and isinstance(result, list):
                        payload["uncertain"] = any(
                            isinstance(item, dict) and item.get("uncertain") is True
                            for item in result
                        )
                    if should_stop:
                        self.stop = True
        except Exception as error:
            payload = response(False, started, _path_for_request(request), error=_compact_error(error))
        try:
            if authenticated:
                payload = _authenticated_payload(payload, self.nonce)
                conn.sendall(
                    (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
                )
        except OSError:
            pass
        finally:
            conn.close()


def _unlink_socket_inode(path: Path, inode: int | None) -> bool:
    if not isinstance(inode, int):
        return False
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISSOCK(info.st_mode) or info.st_ino != inode:
        return False
    path.unlink()
    return True


def _unlink_metadata_if_equal(path: Path, expected: dict[str, Any]) -> bool:
    if _read_private_json(path) != expected:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def _recv_line(conn: socket.socket) -> str:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise ValueError("request is too large")
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    if not chunks:
        raise ValueError("empty request")
    return b"".join(chunks).split(b"\n", 1)[0].decode("utf-8")


CLIENT_CONNECT_TIMEOUT = 0.35
CLIENT_START_TIMEOUT = 5.0
CLIENT_RESPONSE_TIMEOUT = 240.0


def _client_socket_path() -> Path:
    return private_runtime_socket_path(REPOSITORY_ROOT)


def _client_error(message: str, path: str = "client") -> dict[str, Any]:
    return {"ok": False, "ms": 0, "path": path, "error": " ".join(message.split())[:500]}


def _operation_for_request(request: dict[str, Any]) -> OperationSpec:
    raw = request.get("_operation")
    if raw is not None:
        if not isinstance(raw, dict):
            raise ValueError("_operation must be an object")
        return OperationSpec.from_dict(raw)
    op = str(request.get("op") or "").casefold()
    if op == "b":
        batch = request.get("batch")
        children = [wire_request(item) for item in batch] if isinstance(batch, list) else []
        mutating = any(str(item.get("op") or "").casefold() in {"o", "t", "p", "y", "k", "s", "x", "b"} for item in children)
        safety = SafetyClass.TRANSIENT if mutating else SafetyClass.OBSERVE
    elif op in {"t", "p", "y", "k", "s", "x"} or (op == "o" and request.get("url") is not None):
        safety = SafetyClass.TRANSIENT
    elif op in {"o", "h"}:
        safety = SafetyClass.NAVIGATE
    else:
        safety = SafetyClass.OBSERVE
    operation_id = request.get("_operation_id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        operation_id = f"opcode:{op or 'unknown'}"
    return OperationSpec(operation_id, f"ipad opcode {op or 'unknown'}", safety)


def _project_transport(result: OperationResult, *, path: str = "daemon") -> dict[str, Any]:
    if result.phase is OperationPhase.RESPONSE_RECEIVED and isinstance(result.response, dict):
        plain = dict(result.response)
        # A daemon response can carry the device-side execution phase.  Do not
        # overwrite response_lost merely because the local socket replied.
        plain.setdefault("_operation", result.projection_metadata)
        return public_result(plain)
    plain = result.to_plain_result()
    plain.setdefault("path", path)
    return public_result(plain)


def _client_send(
    request: dict[str, Any], operation: OperationSpec, *, timeout: float
) -> OperationResult:
    """Send once, recording transport phase rather than interpreting error prose."""
    socket_path = _client_socket_path()
    authenticated = "_config" in request or "_registry" in request
    metadata = _owned_socket_metadata(socket_path) if authenticated else None
    if authenticated and metadata is None:
        return OperationResult.not_sent(
            operation,
            OperationError("untrusted_endpoint", "daemon socket ownership is not proven"),
        )
    outbound = (
        _authenticated_payload(request, metadata["nonce"])
        if metadata is not None else dict(request)
    )
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(CLIENT_CONNECT_TIMEOUT)
        sock.connect(str(socket_path))
        if metadata is not None and _owned_socket_metadata(socket_path) != metadata:
            sock.close()
            return OperationResult.not_sent(
                operation,
                OperationError("endpoint_changed", "daemon endpoint changed before dispatch"),
            )
    except OSError as error:
        sock.close()
        return OperationResult.not_sent(
            operation,
            OperationError("connect_failed", "daemon was not connected", {"type": type(error).__name__}),
        )
    try:
        sock.settimeout(timeout)
        # A partial write is still an uncertain dispatch boundary.  Nothing
        # after this point may resend the command.
        sock.sendall((json.dumps(outbound, separators=(",", ":")) + "\n").encode())
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        if not chunks:
            return OperationResult.response_lost(
                operation, OperationError("transport_closed", "daemon closed after dispatch")
            )
        value = json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))
        if not isinstance(value, dict):
            return OperationResult.response_lost(
                operation, OperationError("invalid_response", "daemon response was not an object")
            )
        if metadata is not None:
            response_nonce = value.get("_nonce")
            if (
                value.get("_protocol") != RUNTIME_PROTOCOL
                or not isinstance(response_nonce, str)
                or not secrets.compare_digest(response_nonce, metadata["nonce"])
            ):
                return OperationResult.response_lost(
                    operation,
                    OperationError("authentication_lost", "daemon response authentication failed"),
                )
            value.pop("_protocol", None)
            value.pop("_nonce", None)
        return OperationResult.succeeded(operation, value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return OperationResult.response_lost(
            operation,
            OperationError("response_lost", "daemon response was lost after dispatch", {"type": type(error).__name__}),
        )
    finally:
        sock.close()


def _client_daemon_running() -> bool:
    path = _client_socket_path()
    metadata = _owned_socket_metadata(path)
    return metadata is not None and _probe_owned_daemon(path, metadata)


def _client_start_daemon() -> bool:
    path = _client_socket_path()
    nonce = secrets.token_hex(32)
    command = [
        sys.executable, "-m", "ipad_agent.runtime.daemon", "--socket", str(path),
        "--nonce", nonce,
    ]
    try:
        subprocess.Popen(
            command,
            cwd=str(REPOSITORY_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return False
    deadline = time.monotonic() + CLIENT_START_TIMEOUT
    while time.monotonic() < deadline:
        if _client_daemon_running():
            return True
        time.sleep(0.05)
    return False


def _client_direct_open(
    request: dict[str, Any], operation: OperationSpec, config: Any, registry: Any
) -> OperationResult:
    started = time.perf_counter()
    try:
        from ipad_agent.transports.coredevice import open_ipad

        timeout = _env_float("IPAD_AGENT_RUNTIME_COREDEVICE_TIMEOUT", 15.0)
        result = open_ipad(
            request["app"], url=request.get("url"), device=config.device,
            timeout=timeout, config=config, registry=registry,
        )
        payload = response(
            True,
            started,
            "coredevice",
            result={"bundle": result.bundle_id, "device": result.device_id, "locked": result.locked},
        )
        return OperationResult.succeeded(operation, payload)
    except Exception as error:
        if getattr(error, "uncertain", False):
            return OperationResult.response_lost(
                operation,
                OperationError("coredevice_response_lost", _compact_error(error)),
            )
        payload = response(False, started, "coredevice", error=_compact_error(error))
        return OperationResult.succeeded(operation, payload)


def dispatch_client(
    request: dict[str, Any], *, timeout: float = CLIENT_RESPONSE_TIMEOUT,
    config: Any = None, registry: Any = None,
) -> dict[str, Any]:
    """Route one kernel request directly or through the persistent daemon."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    op = request.get("op")
    if not isinstance(op, str):
        return _client_error("missing opcode")
    try:
        operation = _operation_for_request(request)
        if op.casefold() == "o" and request.get("url") is not None:
            raise ValueError(
                "raw URL opcode dispatch is unsupported; use a declared semantic integration command"
            )
        if config is None:
            from ipad_agent.core.config import load_config
            config = load_config()
        if registry is None:
            from ipad_agent.core.registry import load_registry
            registry = load_registry(enabled_addons=config.enabled_addons)
        if "browser_bundle" in request or "_browser_bundle" in request:
            raise ValueError(
                "legacy browser_bundle runtime fields are unsupported; pass a validated Config"
            )
        from ipad_agent.core.config import config_snapshot
        wire = dict(request)
        wire["_config"] = config_snapshot(config)
        wire["_registry"] = registry_snapshot(registry)
    except Exception as error:
        try:
            fallback = OperationSpec("rejected", "rejected request", SafetyClass.OBSERVE)
            return _project_transport(OperationResult.not_sent(
                fallback, OperationError("request_rejected", _compact_error(error))
            ), path="client")
        except Exception:
            return _client_error(_compact_error(error))

    daemon_result = _client_send(wire, operation, timeout=timeout)
    if daemon_result.phase is OperationPhase.RESPONSE_RECEIVED:
        return _project_transport(daemon_result)
    if daemon_result.phase is OperationPhase.RESPONSE_LOST:
        return _project_transport(daemon_result)

    lowered = op.casefold()
    if lowered == "o":
        return _project_transport(_client_direct_open(request, operation, config, registry), path="coredevice")
    if lowered == "q":
        payload = {
            "ok": True, "ms": 0, "path": "status",
            "result": {"daemon": False, "session": False, "app": None, "idle_s": None, "ttl_s": None},
        }
        return _project_transport(OperationResult.succeeded(operation, payload), path="status")
    if lowered == "x":
        payload = {"ok": True, "ms": 0, "path": "daemon", "result": {"stopped": True, "daemon": False}}
        return _project_transport(OperationResult.succeeded(operation, payload))
    if not _client_start_daemon():
        return _project_transport(OperationResult.not_sent(
            operation, OperationError("daemon_start_failed", f"unable to start daemon at {_client_socket_path()}")
        ))
    result = _client_send(wire, operation, timeout=timeout)
    return _project_transport(result)


def run_daemon(socket_path: Path, idle_ttl: float, *, nonce: str | None = None) -> int:
    daemon = Daemon(_require_socket_path(socket_path), idle_ttl=idle_ttl, nonce=nonce)

    def stop(_signum: int, _frame: Any) -> None:
        daemon.stop = True
        if daemon._listener is not None:
            with contextlib.suppress(OSError):
                daemon._listener.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        daemon.serve()
    except RuntimeError as error:
        emit(response(False, time.perf_counter(), "daemon", error=str(error)))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="persistent iPad CoreDevice/XCTest runtime")
    parser.add_argument("command", choices=("daemon",), nargs="?", default="daemon")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--idle-ttl", type=float, default=_env_float("IPAD_AGENT_RUNTIME_IDLE_TTL", DEFAULT_IDLE_TTL))
    parser.add_argument("--nonce")
    args = parser.parse_args(argv)
    return run_daemon(args.socket, args.idle_ttl, nonce=args.nonce)


if __name__ == "__main__":
    raise SystemExit(main())
