"""Short-lived, optimized XCTest control for a paired physical iPad.

Use CoreDevice (``ipad_agent.coredevice``) for launches and deep links. Use this
module only when taps, typing, swipes, or UI inspection are required. Sessions
are torn down on context exit so Apple's Automation Running overlay disappears.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import plistlib
import re
import shlex
import signal
import subprocess
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator

from .bootstrap import APPIUM, APPIUM_HOME
from .paths import (
    RUNTIME_ROOT, private_mkdir, private_write_bytes, private_write_text,
    require_runtime_path,
)
from .versions import (
    APPIUM_OWNER_SCHEMA, WDA_ARTIFACT_SCHEMA, WDA_VERIFICATION_SCHEMA,
    WDA_VERIFICATION_TTL_SECONDS, XCUITEST_VERSION,
)

_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"
_SERVER: subprocess.Popen[str] | None = None
_SERVER_LOG = None
DERIVED_DATA_ROOT = RUNTIME_ROOT / "derived-data"
WDA_STATE_ROOT = RUNTIME_ROOT / "state" / "wda"
ARTIFACT_FILE = "ipad-agent-artifact.json"
OWNER = "ipad-agent"
APPIUM_OWNER_RECEIPT = WDA_STATE_ROOT / "appium-owner.json"


class XCTestControlError(RuntimeError):
    """Failure carrying transport certainty and optional human-gate metadata."""

    def __init__(
        self, message: str, *, code: str = "xctest_control_error",
        uncertain: bool = False, dispatched: bool = False,
        human_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.uncertain = bool(uncertain)
        self.dispatched = bool(dispatched)
        self.human_action = human_action

    @property
    def transport(self) -> dict[str, bool]:
        return {"dispatched": self.dispatched, "uncertain": self.uncertain}


@dataclass(frozen=True)
class XCTestConfig:
    udid: str
    platform_version: str
    development_team: str
    bootstrap_path: str
    wda_bundle_id: str
    appium_url: str = "http://127.0.0.1:4723"

    @classmethod
    def discover(cls, *, timeout: float = 30.0) -> "XCTestConfig":
        """Discover one device and a validated project-owned WDA artifact."""
        device = _discover_ipad(timeout, os.environ.get("IPAD_AGENT_DEVICE"))
        team = os.environ.get("IPAD_AGENT_TEAM_ID") or _discover_personal_team(timeout)
        bundle = os.environ.get("IPAD_AGENT_WDA_BUNDLE_ID") or default_wda_bundle(team)
        explicit = os.environ.get("IPAD_AGENT_XCTESTRUN")
        selection = make_selection(device=device, team=team, bundle_id=bundle)
        metadata = validate_artifact(artifact_directory(selection), selection=selection)
        xctestrun = Path(metadata["xctestrun"])
        if explicit:
            configured = require_runtime_path(Path(explicit).expanduser())
            if configured != xctestrun:
                raise XCTestControlError(
                    "Configured xctestrun is not the setup-owned artifact for the current selection",
                    code="wda_setup_required",
                )
        if not verified(selection):
            raise XCTestControlError(
                "The current setup-owned WDA artifact has no unexpired bounded-session verification",
                code="wda_verification_required",
            )
        return cls(
            udid=device["udid"], platform_version=device["version"], development_team=team,
            bootstrap_path=str(xctestrun.parent), wda_bundle_id=bundle,
            appium_url=os.environ.get("IPAD_AGENT_APPIUM_URL", "http://127.0.0.1:4723"),
        )


@dataclass(frozen=True)
class WDASelection:
    device_identifier: str
    device_udid: str
    platform_version: str
    team_id: str
    bundle_id: str
    source_project: str
    source_digest: str
    xcode: str
    fingerprint: str


class AppiumSession:
    def __init__(self, server_url: str, session_id: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.session_id = session_id
        self.base_url = f"{self.server_url}/session/{session_id}"
        self.teardown_result: dict[str, Any] | None = None

    def activate(self, bundle_id: str, *, timeout: float = 30.0) -> None:
        self._request("POST", "/appium/device/activate_app", {"bundleId": bundle_id}, timeout)

    def execute(self, script: str, arguments: dict[str, Any] | None = None, *, timeout: float = 30.0) -> Any:
        return self._request("POST", "/execute/sync", {"script": script, "args": [arguments or {}]}, timeout)

    def find(self, using: str, value: str, *, timeout: float = 30.0) -> str | None:
        try:
            result = self._request("POST", "/element", {"using": using, "value": value}, timeout)
        except XCTestControlError as error:
            if "no such element" in str(error).casefold():
                return None
            raise
        return result.get(_ELEMENT_KEY) if isinstance(result, dict) else None

    def wait_find(
        self,
        using: str,
        value: str,
        *,
        timeout: float = 5.0,
        interval: float = 0.1,
    ) -> str | None:
        """Poll only until a required control exists; avoids unconditional sleeps."""
        deadline = time.monotonic() + timeout
        while True:
            element = self.find(using, value, timeout=max(0.5, min(2.0, timeout)))
            if element is not None:
                return element
            if time.monotonic() >= deadline:
                return None
            time.sleep(interval)

    def find_all(self, using: str, value: str, *, timeout: float = 30.0) -> list[str]:
        result = self._request("POST", "/elements", {"using": using, "value": value}, timeout)
        if not isinstance(result, list):
            return []
        return [item[_ELEMENT_KEY] for item in result if isinstance(item, dict) and _ELEMENT_KEY in item]

    def click(self, element_id: str, *, timeout: float = 30.0) -> None:
        self._request("POST", f"/element/{element_id}/click", {}, timeout)

    def clear(self, element_id: str, *, timeout: float = 30.0) -> None:
        self._request("POST", f"/element/{element_id}/clear", {}, timeout)

    def type(self, element_id: str, text: str, *, timeout: float = 30.0) -> None:
        self._request("POST", f"/element/{element_id}/value", {"text": text, "value": list(text)}, timeout)

    def attribute(self, element_id: str, name: str, *, timeout: float = 30.0) -> Any:
        return self._request("GET", f"/element/{element_id}/attribute/{name}", None, timeout)

    def source_json(self, *, timeout: float = 60.0) -> dict[str, Any]:
        result = self.execute("mobile: source", {"format": "json"}, timeout=timeout)
        return result if isinstance(result, dict) else {}

    def _request(self, method: str, path: str, payload: Any, timeout: float) -> Any:
        return _http_json(method, f"{self.base_url}{path}", payload, timeout).get("value")


@contextlib.contextmanager
def short_session(config: XCTestConfig, *, timeout: float = 180.0) -> Iterator[AppiumSession]:
    """Start one XCTest session and fail closed unless its WDA teardown is proven."""
    config = _config_with_runtime_compatibility(config)
    ensure_appium_server(config.appium_url)
    capabilities = {
        "platformName": "iOS", "appium:automationName": "XCUITest",
        "appium:udid": config.udid, "appium:platformVersion": config.platform_version,
        "appium:xcodeOrgId": config.development_team, "appium:xcodeSigningId": "Apple Development",
        "appium:updatedWDABundleId": config.wda_bundle_id,
        "appium:useXctestrunFile": True, "appium:bootstrapPath": config.bootstrap_path,
        "appium:noReset": True, "appium:skipLogCapture": True,
        "appium:waitForIdleTimeout": 0.0, "appium:animationCoolOffTimeout": 0.0,
        "appium:disableAutomaticScreenshots": True,
        "appium:wdaStartupRetries": 1,
        "appium:wdaStartupRetryInterval": 500, "appium:newCommandTimeout": 600,
    }
    session: AppiumSession | None = None
    server_pid: int | None = None
    try:
        response = _http_json("POST", f"{config.appium_url.rstrip('/')}/session", {"capabilities": {"alwaysMatch": capabilities, "firstMatch": [{}]}}, timeout)
        value = response.get("value")
        session_id = value.get("sessionId") if isinstance(value, dict) else None
        if not session_id:
            message = value.get("message") if isinstance(value, dict) else response
            raise XCTestControlError(f"Unable to create XCTest session: {message}")
        session = AppiumSession(config.appium_url, session_id)
        ownership = _owned_appium_identity()
        if ownership is None:
            raise XCTestControlError(
                "XCTest session started through Appium whose project ownership could not be proven",
                code="wda_cleanup_incomplete",
            )
        server_pid = ownership[0]
        session._request("POST", "/appium/settings", {"settings": {"waitForIdleTimeout": 0.0, "animationCoolOffTimeout": 0.0}}, 30.0)
        yield session
    finally:
        if session is None:
            # A failed create may still have launched WDA. This is best effort;
            # the original create failure remains the truthful result.
            _terminate_wda_xcodebuild(server_pid=server_pid)
        else:
            captured: list[_OwnedWDAProcess] | None = None
            capture_error: str | None = None
            try:
                if server_pid is None:
                    raise XCTestControlError("receipt-owned Appium ancestry is unavailable")
                captured = _capture_owned_wda_descendants(server_pid)
            except XCTestControlError as error:
                capture_error = str(error)

            deletion_error: str | None = None
            try:
                _http_json("DELETE", session.base_url, None, 30.0)
            except XCTestControlError as error:
                deletion_error = str(error)

            cleanup = (
                _terminate_wda_xcodebuild(server_pid=server_pid, captured=captured)
                if capture_error is None
                else {"complete": False, "reason": "descendant_capture_failed", "detail": capture_error}
            )
            complete = isinstance(cleanup, dict) and cleanup.get("complete") is True
            session.teardown_result = {
                "session_deleted": deletion_error is None,
                "appium_ownership_proven": server_pid is not None,
                "xcodebuild_descendants_captured": cleanup.get("captured_pids", []) if isinstance(cleanup, dict) else [],
                "xcodebuild_remaining": cleanup.get("remaining_pids", []) if isinstance(cleanup, dict) else [],
            }
            if deletion_error is not None or not complete:
                details = []
                if deletion_error is not None:
                    details.append(f"session deletion failed: {deletion_error}")
                if not complete:
                    reason = cleanup.get("reason", "unknown") if isinstance(cleanup, dict) else "unknown"
                    details.append(f"WDA process cleanup was not proven: {reason}")
                raise XCTestControlError(
                    "XCTest teardown incomplete; " + "; ".join(details),
                    code="wda_cleanup_incomplete",
                    uncertain=deletion_error is not None,
                    dispatched=deletion_error is not None,
                )


def ensure_appium_server(server_url: str = "http://127.0.0.1:4723", *, timeout: float = 8.0) -> None:
    """Keep a loopback-only Appium server warm without starting XCTest."""
    global _SERVER, _SERVER_LOG
    parsed = urlparse(server_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise XCTestControlError("Appium URL must use loopback HTTP")
    address = "127.0.0.1" if parsed.hostname in {"localhost", "127.0.0.1"} else "::1"
    port = parsed.port or 4723
    base_path = parsed.path.rstrip("/") or "/"
    try:
        _http_json("GET", f"{server_url.rstrip('/')}/status", None, 0.5)
        return
    except XCTestControlError:
        pass
    local_appium = APPIUM
    appium = os.environ.get("IPAD_AGENT_APPIUM") or (str(local_appium) if local_appium.exists() else None)
    if not appium:
        raise XCTestControlError("appium is not installed or not on PATH")
    log_path = RUNTIME_ROOT / "cache" / "appium.log"
    private_mkdir(log_path.parent)
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    _SERVER_LOG = os.fdopen(fd, "w")
    appium_env = dict(os.environ)
    if Path(appium).expanduser() == local_appium:
        appium_env["APPIUM_HOME"] = str(APPIUM_HOME)
    nonce = uuid.uuid4().hex
    appium_env["IPAD_AGENT_OWNER_NONCE"] = nonce
    command = [appium, "--address", address, "--port", str(port), "--base-path", base_path]
    _SERVER = subprocess.Popen(
        command, stdout=_SERVER_LOG, stderr=subprocess.STDOUT, text=True,
        start_new_session=True, env=appium_env,
    )
    process_start = _process_start(_SERVER.pid)
    receipt = {
        "schema": APPIUM_OWNER_SCHEMA, "owner": OWNER, "pid": _SERVER.pid,
        "started_at": _utc_now(), "process_start": process_start, "nonce": nonce,
        "server_url": server_url.rstrip("/"), "executable": str(Path(appium).expanduser()),
        "command": command,
    }
    private_write_text(APPIUM_OWNER_RECEIPT, json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _SERVER.poll() is not None:
            _remove_appium_receipt_if_matches(_SERVER.pid, nonce)
            raise XCTestControlError("Appium server exited during startup", code="appium_start_failed")
        try:
            _http_json("GET", f"{server_url.rstrip('/')}/status", None, 0.5)
            return
        except XCTestControlError:
            time.sleep(0.05)
    stop_owned_appium_server()
    raise XCTestControlError("Appium server did not become ready", code="appium_start_timeout")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_json(method: str, url: str, payload: Any, timeout: float) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        opener = urllib.request.build_opener(_RejectRedirects())
        with opener.open(request, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        detail = getattr(error, "read", lambda: b"")()
        message = detail.decode(errors="replace") if detail else str(error)
        definite_response = isinstance(error, urllib.error.HTTPError)
        if definite_response and detail:
            try:
                remote_result = json.loads(detail)
            except json.JSONDecodeError:
                remote_result = None
            remote_error = _remote_control_error(method, url, remote_result)
            if remote_error is not None:
                raise remote_error from error
        dispatched = True
        uncertain = method.upper() not in {"GET", "HEAD"} and not definite_response
        raise XCTestControlError(
            message, code="wda_transport_error", uncertain=uncertain,
            dispatched=dispatched,
        ) from error
    try:
        result = json.loads(body) if body else {"value": None}
    except json.JSONDecodeError as error:
        raise XCTestControlError(
            "Appium returned invalid JSON", code="wda_invalid_response",
            uncertain=method.upper() not in {"GET", "HEAD"}, dispatched=True,
        ) from error
    remote_error = _remote_control_error(method, url, result)
    if remote_error is not None:
        raise remote_error
    return result


def _remote_control_error(method: str, url: str, result: Any) -> XCTestControlError | None:
    if not isinstance(result, dict) or not isinstance(result.get("value"), dict):
        return None
    value = result["value"]
    if not value.get("error"):
        return None
    code = (
        "developer_trust_required"
        if _is_untrusted_developer_session_failure(method, url, value)
        else "wda_remote_error"
    )
    return XCTestControlError(
        value.get("message") or value["error"], code=code, dispatched=True,
    )


def _is_untrusted_developer_session_failure(method: str, url: str, value: dict[str, Any]) -> bool:
    """Recognize only an Appium session-create failure that names WDA and trust."""
    parsed = urlparse(url)
    if method.upper() != "POST" or not parsed.path.rstrip("/").endswith("/session"):
        return False
    remote_error = str(value.get("error") or "").casefold()
    if remote_error not in {"session not created", "unknown error"}:
        return False
    detail = "\n".join(
        str(value.get(key) or "") for key in ("message", "stacktrace")
    ).casefold()
    wda_launch = (
        ("webdriveragent" in detail or "xctrunner" in detail)
        and ("launch" in detail or "start" in detail)
    )
    explicit_trust = any(marker in detail for marker in (
        "untrusted developer",
        "developer is not trusted",
        "developer has not been trusted",
        "profile has not been explicitly trusted",
        "profile has not been trusted",
        "not been explicitly trusted by the user",
    ))
    return wda_launch and explicit_trust


def _discover_ipad(timeout: float, selected: str | None = None) -> dict[str, str]:
    payload = _devicectl_json(["list", "devices"], timeout)
    matches = []
    for item in payload.get("result", {}).get("devices", []):
        hardware = item.get("hardwareProperties", {})
        properties = item.get("deviceProperties", {})
        connection = item.get("connectionProperties", {})
        paired = connection.get("pairingState") == "paired"
        connected = connection.get("tunnelState") == "connected"
        if hardware.get("deviceType") == "iPad" and (connected or paired):
            matches.append({
                "identifier": item["identifier"],
                "udid": hardware["udid"],
                "version": properties["osVersionNumber"],
            })
    if selected:
        matches = [item for item in matches if selected in {item["identifier"], item["udid"]}]
    if len(matches) != 1:
        suffix = " matching IPAD_AGENT_DEVICE" if selected else ""
        raise XCTestControlError(f"Expected one paired iPad{suffix}, found {len(matches)}")
    return matches[0]


def _discover_personal_team(timeout: float) -> str:
    completed = subprocess.run(
        ["defaults", "export", "com.apple.dt.Xcode", "-"],
        capture_output=True, timeout=timeout,
    )
    teams: set[str] = set()
    if completed.returncode == 0:
        try:
            document = plistlib.loads(completed.stdout)
        except plistlib.InvalidFileException:
            document = None
        table = document.get("IDEProvisioningTeamByIdentifier") if isinstance(document, dict) else None
        if isinstance(table, dict):
            for records in table.values():
                for record in records if isinstance(records, list) else []:
                    team = record.get("teamID") if isinstance(record, dict) else None
                    if isinstance(team, str) and re.fullmatch(r"[A-Z0-9]{10}", team):
                        teams.add(team)
    if len(teams) != 1:
        raise XCTestControlError(
            "Unable to identify exactly one Xcode provisioning team",
            code="apple_account_or_team_selection_required",
            human_action="In Xcode > Settings > Accounts, refresh the intended account and select one development team; complete Apple ID and 2FA prompts yourself.",
        )
    return next(iter(teams))


def _discover_wda_bundle(device_id: str, timeout: float) -> str:
    payload = _devicectl_json(["device", "info", "apps", "--device", device_id], timeout)
    for app in payload.get("result", {}).get("apps", []):
        bundle = app.get("bundleIdentifier")
        if isinstance(bundle, str) and "WebDriverAgentRunner" in bundle:
            return bundle.removesuffix(".xctrunner")
    raise XCTestControlError("Installed WebDriverAgentRunner was not found")


def _devicectl_json(arguments: list[str], timeout: float) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".json") as output:
        completed = subprocess.run(
            ["xcrun", "devicectl", *arguments, "--json-output", output.name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if completed.returncode != 0:
            raise XCTestControlError((completed.stderr or completed.stdout).strip())
        try:
            return json.loads(Path(output.name).read_text())
        except (json.JSONDecodeError, OSError) as error:
            raise XCTestControlError("CoreDevice returned invalid JSON") from error


def default_wda_bundle(team_id: str) -> str:
    clean = re.sub(r"[^a-z0-9]", "", team_id.casefold())
    if not clean:
        raise XCTestControlError("A development team is required to select a WDA bundle ID")
    return f"io.ipad-agent.wda.{clean}"


def locate_driver_wda_project() -> Path:
    """Locate WDA only beneath the pinned Appium XCUITest driver's home."""
    candidates = [
        APPIUM_HOME / "node_modules" / "appium-xcuitest-driver" / "node_modules" / "appium-webdriveragent" / "WebDriverAgent.xcodeproj",
        APPIUM_HOME / "node_modules" / "appium-xcuitest-driver" / "WebDriverAgent.xcodeproj",
    ]
    candidates.extend(APPIUM_HOME.glob("node_modules/**/appium-webdriveragent/WebDriverAgent.xcodeproj"))
    root = APPIUM_HOME.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        package = resolved.parent / "package.json"
        driver_package = next((p for p in resolved.parents if p.name == "appium-xcuitest-driver"), None)
        try:
            wda_name = json.loads(package.read_text()).get("name")
            driver_version = json.loads((driver_package / "package.json").read_text()).get("version") if driver_package else None
        except (OSError, json.JSONDecodeError):
            continue
        if wda_name == "appium-webdriveragent" and driver_version == XCUITEST_VERSION:
            return resolved
    raise XCTestControlError(
        f"Pinned XCUITest driver {XCUITEST_VERSION} does not expose driver-owned WebDriverAgent under {APPIUM_HOME}"
    )


def make_selection(*, device: dict[str, str], team: str, bundle_id: str, xcode: str | None = None) -> WDASelection:
    project = locate_driver_wda_project()
    digest = _source_digest(project)
    if xcode is None:
        code, out, err = _run_process(["xcodebuild", "-version"], timeout=20)
        if code:
            raise XCTestControlError(err or out or "xcodebuild is unavailable")
        xcode = " | ".join(out.splitlines())
    fields = {
        "driver": XCUITEST_VERSION, "source": str(project), "source_digest": digest,
        "team_id": team, "bundle_id": bundle_id, "device_udid": device["udid"],
        "platform_version": device["version"], "xcode": xcode,
    }
    fingerprint = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return WDASelection(
        device_identifier=device["identifier"], device_udid=device["udid"],
        platform_version=device["version"], team_id=team, bundle_id=bundle_id,
        source_project=str(project), source_digest=digest, xcode=xcode, fingerprint=fingerprint,
    )


def artifact_directory(selection: WDASelection) -> Path:
    return DERIVED_DATA_ROOT / selection.fingerprint


def _parse_apple_platform_version(version: str, *, source: str) -> tuple[int, ...]:
    """Parse a release version without accepting labels or command noise."""
    if not isinstance(version, str) or re.fullmatch(
        r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))+", version
    ) is None:
        raise XCTestControlError(
            f"{source} returned an invalid platform version",
            code="wda_sdk_invalid",
        )
    return tuple(int(component) for component in version.split("."))


def _discover_iphoneos_sdk_version(*, timeout: float = 20.0) -> str:
    """Return the selected Xcode's structurally validated device SDK version."""
    command = ["xcrun", "--sdk", "iphoneos", "--show-sdk-version"]
    code, out, err = _run_process(command, timeout=timeout)
    if code:
        detail = " ".join((err or out).split())
        suffix = f": {detail}" if detail else ""
        raise XCTestControlError(
            f"Unable to discover the installed iPhoneOS SDK with xcrun{suffix}",
            code="wda_sdk_unavailable",
        )
    _parse_apple_platform_version(out, source="xcrun iPhoneOS SDK discovery")
    return out


def _runtime_platform_version(device_version: str, sdk_version: str) -> str:
    """Cap WDA deployment compatibility at the installed same-family SDK."""
    device = _parse_apple_platform_version(device_version, source="Device discovery")
    sdk = _parse_apple_platform_version(sdk_version, source="xcrun iPhoneOS SDK discovery")
    if device[0] != sdk[0]:
        raise XCTestControlError(
            "The paired iPad OS and installed iPhoneOS SDK are from incompatible major families",
            code="wda_sdk_incompatible",
        )
    width = max(len(device), len(sdk))
    device_comparable = device + (0,) * (width - len(device))
    sdk_comparable = sdk + (0,) * (width - len(sdk))
    return sdk_version if device_comparable > sdk_comparable else device_version


def _xctestrun_products(
    selection: WDASelection, artifact: dict[str, Any]
) -> tuple[Path, Path, bytes]:
    """Return the receipt-owned xctestrun and its original Products directory."""
    try:
        root = require_runtime_path(artifact_directory(selection))
        source_value = artifact["xctestrun"]
        source = require_runtime_path(source_value)
        products = require_runtime_path(root / "Build" / "Products")
        expected_hash = artifact["product"]["xctestrun_sha256"]
        runtime = artifact["runtime"]
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise XCTestControlError(
            f"WDA xctestrun path provenance mismatch: {error}",
            code="wda_setup_required",
        ) from error
    provenance_matches = (
        root.name == selection.fingerprint
        and artifact.get("fingerprint") == selection.fingerprint
        and isinstance(source_value, str)
        and source_value == str(source)
        and source.parent == products
        and isinstance(runtime, dict)
        and runtime.get("xctestrun") == str(source)
        and isinstance(expected_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_hash) is not None
    )
    if not provenance_matches or source.is_symlink() or not source.is_file():
        raise XCTestControlError(
            "WDA xctestrun is not the exact setup-owned Build/Products file",
            code="wda_setup_required",
        )
    try:
        source_bytes = source.read_bytes()
    except OSError as error:
        raise XCTestControlError(
            f"Cannot read setup-owned WDA xctestrun: {error}",
            code="wda_setup_required",
        ) from error
    if hashlib.sha256(source_bytes).hexdigest() != expected_hash:
        raise XCTestControlError(
            "WDA setup-owned xctestrun hash mismatch",
            code="wda_setup_required",
        )
    return products, source, source_bytes


def _xctestrun_alias_name(selection: WDASelection, runtime_version: str) -> str:
    """Return the one per-device filename Appium 12.8.2 probes directly."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", selection.device_udid) is None:
        raise XCTestControlError("WDA has an unsafe device identifier", code="wda_setup_required")
    _parse_apple_platform_version(runtime_version, source="WDA runtime compatibility")
    return f"{selection.device_udid}_{runtime_version}.xctestrun"


def _materialize_xctestrun_alias(
    selection: WDASelection, artifact: dict[str, Any], runtime_version: str
) -> Path:
    """Refresh one mutable Appium alias beside the receipt-owned xctestrun.

    Appium injects its port into the per-device file. Keeping that copy in the
    original Build/Products directory preserves ``__TESTROOT__`` references
    without changing the canonical xctestrun covered by the artifact receipt.
    """
    products, source, source_bytes = _xctestrun_products(selection, artifact)
    alias = require_runtime_path(
        products / _xctestrun_alias_name(selection, runtime_version)
    )
    if alias == source:
        raise XCTestControlError(
            "WDA compatibility alias collides with the setup-owned xctestrun",
            code="wda_setup_required",
        )
    private_write_bytes(alias, source_bytes)
    try:
        alias_bytes = alias.read_bytes()
    except OSError as error:
        raise XCTestControlError(
            f"Cannot verify WDA xctestrun alias: {error}",
            code="wda_setup_required",
        ) from error
    if alias.is_symlink() or not alias.is_file() or alias_bytes != source_bytes:
        raise XCTestControlError(
            "WDA xctestrun alias is not hash-identical to the setup-owned file",
            code="wda_setup_required",
        )
    return products


def _clean_generated_xctestrun_aliases(
    selection: WDASelection, products: Path
) -> list[Path]:
    """Remove only Appium per-device xctestrun copies before a rebuild."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", selection.device_udid) is None:
        raise XCTestControlError("WDA has an unsafe device identifier", code="wda_setup_required")
    pattern = re.compile(
        rf"{re.escape(selection.device_udid)}_(?:\d+(?:\.\d+)*)?\.xctestrun"
    )
    removed: list[Path] = []
    if not products.exists():
        return removed
    products = require_runtime_path(products)
    for candidate in products.glob(f"{selection.device_udid}_*.xctestrun"):
        if pattern.fullmatch(candidate.name) is None:
            continue
        candidate = require_runtime_path(candidate)
        if not candidate.is_file() or candidate.is_symlink():
            raise XCTestControlError(
                "WDA generated xctestrun alias is not a regular file",
                code="wda_setup_required",
            )
        candidate.unlink()
        removed.append(candidate)
    return removed


def _config_with_runtime_compatibility(config: XCTestConfig) -> XCTestConfig:
    """Validate an owned Products path and apply the bounded SDK compatibility."""
    try:
        configured = require_runtime_path(config.bootstrap_path)
        relative = configured.relative_to(DERIVED_DATA_ROOT)
    except (OSError, ValueError):
        # Explicitly constructed external configs retain their existing behavior.
        return config
    if not relative.parts:
        raise XCTestControlError(
            "WDA bootstrap path does not identify a fingerprinted artifact",
            code="wda_setup_required",
        )
    root = require_runtime_path(DERIVED_DATA_ROOT / relative.parts[0])
    artifact = validate_artifact(root)
    try:
        selection = WDASelection(
            artifact["device_identifier"], artifact["device_udid"],
            artifact["platform_version"], artifact["team_id"], artifact["bundle_id"],
            artifact["source_project"], artifact["source_digest"], artifact["xcode"],
            artifact["fingerprint"],
        )
        products, _, _ = _xctestrun_products(selection, artifact)
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise XCTestControlError(
            f"WDA runtime provenance mismatch: {error}",
            code="wda_setup_required",
        ) from error
    config_matches = (
        configured == products
        and config.udid == selection.device_udid
        and config.platform_version == selection.platform_version
        and config.development_team == selection.team_id
        and config.wda_bundle_id == selection.bundle_id
    )
    if not config_matches:
        raise XCTestControlError(
            "WDA runtime path or selection mismatch",
            code="wda_setup_required",
        )
    runtime_version = _runtime_platform_version(
        selection.platform_version, _discover_iphoneos_sdk_version()
    )
    products = _materialize_xctestrun_alias(selection, artifact, runtime_version)
    return replace(
        config, platform_version=runtime_version, bootstrap_path=str(products)
    )


def build_for_testing(selection: WDASelection, *, apply: bool, timeout: int = 900) -> dict[str, Any]:
    """Build and validate one fingerprinted WDA artifact.  Dry-run is pure."""
    derived = artifact_directory(selection)
    command = [
        "xcodebuild", "build-for-testing", "-project", selection.source_project,
        "-scheme", "WebDriverAgentRunner", "-destination", f"id={selection.device_udid}",
        "-derivedDataPath", str(derived), f"DEVELOPMENT_TEAM={selection.team_id}",
        "CODE_SIGN_IDENTITY=Apple Development", "CODE_SIGNING_ALLOWED=YES",
        f"PRODUCT_BUNDLE_IDENTIFIER={selection.bundle_id}",
    ]
    if not apply:
        return {"ok": True, "changed": False, "fingerprint": selection.fingerprint, "command": command}
    # Deliberately omit Xcode's provisioning-update and device-registration
    # switches. A missing profile is an Apple security gate for a person in
    # Xcode, not authority for this process to mutate account/device state.
    try:
        existing = validate_artifact(derived, selection=selection)
        return {"ok": True, "changed": False, "fingerprint": selection.fingerprint, "artifact": existing}
    except XCTestControlError:
        pass
    private_mkdir(derived)
    products = derived / "Build" / "Products"
    _clean_generated_xctestrun_aliases(selection, products)
    code, out, err = _run_process(command, timeout=timeout)
    if code:
        detail = " ".join((err or out).split())[-2000:]
        lower = detail.casefold()
        provisioning_tokens = (
            "provisioning profile", "no profiles for", "requires a provisioning profile",
            "register device", "device registration", "profile doesn't include",
            "failed to register bundle identifier", "communication with apple failed",
        )
        if any(token in lower for token in provisioning_tokens):
            raise XCTestControlError(
                "WDA has no usable pre-existing provisioning. Open the driver-owned "
                "WebDriverAgent project in Xcode and complete signing, provisioning, and "
                "any device registration yourself, then rerun the WDA setup phase.",
                code="provisioning_required",
                human_action="Complete WDA signing and provisioning yourself in Xcode; ipad-agent will not update provisioning or register devices automatically.",
            )
        raise XCTestControlError(f"WDA build-for-testing failed: {detail}")
    xctestruns = sorted(products.glob("WebDriverAgentRunner_*.xctestrun"))
    apps = sorted(products.glob("**/WebDriverAgentRunner-Runner.app"))
    if len(xctestruns) != 1 or len(apps) != 1:
        raise XCTestControlError("WDA build did not produce exactly one .xctestrun and signed runner app")
    signature = _signature_metadata(apps[0])
    product = _product_metadata(apps[0], xctestruns[0], derived)
    if signature.get("team_id") != selection.team_id:
        raise XCTestControlError("WDA runner signature team does not match the selected development team")
    signed_bundle = str(signature.get("bundle_id") or "")
    if not signed_bundle.startswith(selection.bundle_id):
        raise XCTestControlError("WDA runner signature bundle ID does not match the selected WDA bundle")
    metadata = {
        "schema": WDA_ARTIFACT_SCHEMA, "owner": OWNER, "fingerprint": selection.fingerprint,
        "source_project": selection.source_project, "source_digest": selection.source_digest,
        "driver_version": XCUITEST_VERSION, "xcode": selection.xcode,
        "device_identifier": selection.device_identifier, "device_udid": selection.device_udid,
        "platform_version": selection.platform_version, "team_id": selection.team_id,
        "bundle_id": selection.bundle_id, "xctestrun": str(xctestruns[0]),
        "runner_app": str(apps[0]), "signature": signature, "product": product,
        "runtime": {
            "team_id": selection.team_id, "wda_bundle_id": selection.bundle_id,
            "xctestrun": str(xctestruns[0]), "wda_fingerprint": selection.fingerprint,
        },
    }
    private_write_text(derived / ARTIFACT_FILE, json.dumps(metadata, sort_keys=True, separators=(",", ":")))
    return {"ok": True, "changed": True, "fingerprint": selection.fingerprint, "artifact": validate_artifact(derived, selection=selection)}


def validate_artifact(directory: str | os.PathLike[str], *, selection: WDASelection | None = None) -> dict[str, Any]:
    """Strongly validate one complete setup-owned artifact receipt and product."""
    try:
        root = require_runtime_path(directory)
        root.relative_to(DERIVED_DATA_ROOT)
        payload = json.loads((root / ARTIFACT_FILE).read_text())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise XCTestControlError(f"WDA artifact provenance is unavailable: {error}") from error
    if not isinstance(payload, dict):
        raise XCTestControlError("WDA artifact provenance must be a JSON object")
    required_strings = (
        "schema", "owner", "fingerprint", "source_project", "source_digest",
        "driver_version", "xcode", "device_identifier", "device_udid",
        "platform_version", "team_id", "bundle_id", "xctestrun", "runner_app",
    )
    missing = [
        key for key in required_strings
        if not isinstance(payload.get(key), str) or not payload[key]
    ]
    for key in ("signature", "product", "runtime"):
        if not isinstance(payload.get(key), dict) or not payload[key]:
            missing.append(key)
    if missing:
        raise XCTestControlError(
            "WDA artifact provenance omits required metadata: " + ", ".join(sorted(missing))
        )
    if payload["schema"] != WDA_ARTIFACT_SCHEMA or payload["owner"] != OWNER:
        raise XCTestControlError("WDA artifact is not owned by ipad-agent")
    if Path(root).name != payload["fingerprint"]:
        raise XCTestControlError("WDA artifact fingerprint/path mismatch")
    if selection is not None:
        expected = {
            "fingerprint": selection.fingerprint, "source_project": selection.source_project,
            "source_digest": selection.source_digest, "device_identifier": selection.device_identifier,
            "device_udid": selection.device_udid, "platform_version": selection.platform_version,
            "team_id": selection.team_id, "bundle_id": selection.bundle_id,
            "driver_version": XCUITEST_VERSION, "xcode": selection.xcode,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise XCTestControlError("WDA artifact provenance does not match the current selection")
    for key in ("xctestrun", "runner_app"):
        try:
            path = require_runtime_path(payload[key])
            path.relative_to(root)
        except (TypeError, ValueError) as error:
            raise XCTestControlError(f"WDA artifact {key} escapes its owned DerivedData") from error
        if not path.exists():
            raise XCTestControlError(f"WDA artifact is missing {key}")
    expected_products = require_runtime_path(root / "Build" / "Products")
    if require_runtime_path(payload["xctestrun"]).parent != expected_products:
        raise XCTestControlError(
            "WDA artifact xctestrun is not in its original Build/Products directory"
        )
    try:
        document = plistlib.loads(Path(payload["xctestrun"]).read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise XCTestControlError("WDA .xctestrun is not a valid property list") from error
    if not isinstance(document, dict) or not document:
        raise XCTestControlError("WDA .xctestrun contains no test configuration")
    if not any(isinstance(value, dict) and isinstance(value.get("TestBundlePath"), str) for value in document.values()):
        raise XCTestControlError("WDA .xctestrun contains no test bundle path")
    signature = _signature_metadata(Path(payload["runner_app"]))
    if signature != payload["signature"]:
        raise XCTestControlError("WDA signature provenance changed")
    if signature.get("team_id") != payload["team_id"] or not str(signature.get("bundle_id") or "").startswith(payload["bundle_id"]):
        raise XCTestControlError("WDA signature no longer matches artifact metadata")
    product = _product_metadata(Path(payload["runner_app"]), Path(payload["xctestrun"]), root)
    if payload["product"] != product:
        raise XCTestControlError("WDA product, architecture, or plist provenance changed")
    expected_runtime = {
        "team_id": payload["team_id"], "wda_bundle_id": payload["bundle_id"],
        "xctestrun": payload["xctestrun"], "wda_fingerprint": payload["fingerprint"],
    }
    if payload["runtime"] != expected_runtime:
        raise XCTestControlError("WDA runtime receipt fields do not match artifact provenance")
    return payload


def verification_path(fingerprint: str) -> Path:
    return WDA_STATE_ROOT / f"{fingerprint}.json"


def verify_bounded_session(selection: WDASelection, *, apply: bool, timeout: float = 180.0, appium_url: str = "http://127.0.0.1:4723") -> dict[str, Any]:
    artifact = validate_artifact(artifact_directory(selection), selection=selection)
    if not apply:
        return {"ok": True, "changed": False, "planned": "bounded_appium_wda_session", "timeout_seconds": timeout}
    receipt_path = verification_path(selection.fingerprint)
    # A new live verification supersedes any prior success. If this attempt's
    # cleanup is incomplete, doctor must not continue reporting the old receipt.
    try:
        receipt_path.unlink()
    except FileNotFoundError:
        pass
    config = XCTestConfig(
        selection.device_udid, selection.platform_version, selection.team_id,
        str(Path(artifact["xctestrun"]).parent), selection.bundle_id, appium_url,
    )
    started = time.monotonic()
    with short_session(config, timeout=timeout) as session:
        pass
    teardown = session.teardown_result
    if not _verification_teardown_proven(teardown):
        raise XCTestControlError(
            "Bounded WDA verification teardown was not proven complete",
            code="wda_cleanup_incomplete",
        )
    verified_at = datetime.now(timezone.utc)
    receipt = {
        "schema": WDA_VERIFICATION_SCHEMA, "owner": OWNER,
        "fingerprint": selection.fingerprint, "device_udid": selection.device_udid,
        "team_id": selection.team_id, "bundle_id": selection.bundle_id,
        "verified_at": verified_at.isoformat().replace("+00:00", "Z"),
        "expires_at": (verified_at + timedelta(seconds=WDA_VERIFICATION_TTL_SECONDS)).isoformat().replace("+00:00", "Z"),
        "verification_tuple": _verification_tuple(selection, artifact),
        "teardown": teardown,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    private_write_text(receipt_path, json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return {"ok": True, "changed": True, "receipt": receipt}


def _verification_teardown_proven(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    captured = value.get("xcodebuild_descendants_captured")
    return (
        value.get("session_deleted") is True
        and value.get("appium_ownership_proven") is True
        and isinstance(captured, list)
        and all(isinstance(pid, int) and not isinstance(pid, bool) and pid > 1 for pid in captured)
        and len(captured) == len(set(captured))
        and value.get("xcodebuild_remaining") == []
    )


def verified(selection: WDASelection) -> bool:
    try:
        payload = json.loads(verification_path(selection.fingerprint).read_text())
        artifact = validate_artifact(artifact_directory(selection), selection=selection)
        expires = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
        verified_at = datetime.fromisoformat(str(payload["verified_at"]).replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, XCTestControlError):
        return False
    teardown_proven = _verification_teardown_proven(payload.get("teardown"))
    required = {
        "schema": WDA_VERIFICATION_SCHEMA, "owner": OWNER,
        "fingerprint": selection.fingerprint, "device_udid": selection.device_udid,
        "team_id": selection.team_id, "bundle_id": selection.bundle_id,
        "verification_tuple": _verification_tuple(selection, artifact),
    }
    return (
        all(payload.get(key) == value for key, value in required.items())
        and teardown_proven
        and verified_at <= datetime.now(timezone.utc) < expires
        and expires - verified_at == timedelta(seconds=WDA_VERIFICATION_TTL_SECONDS)
    )


def _verification_tuple(selection: WDASelection, artifact: dict[str, Any]) -> dict[str, str]:
    return {
        "fingerprint": selection.fingerprint, "device_udid": selection.device_udid,
        "platform_version": selection.platform_version, "team_id": selection.team_id,
        "bundle_id": selection.bundle_id, "source_digest": selection.source_digest,
        "xctestrun_sha256": _sha256_file(Path(artifact["xctestrun"])),
    }


def _source_digest(project: Path) -> str:
    """Fingerprint all build-relevant driver-owned WDA source, not two manifest files."""
    root = project.parent
    allowed_names = {"package.json", "project.pbxproj", "Info.plist", "PrivacyInfo.xcprivacy"}
    allowed_suffixes = {".h", ".m", ".mm", ".c", ".cc", ".cpp", ".swift", ".plist", ".xcconfig", ".entitlements", ".storyboard", ".xib", ".strings", ".json"}
    files: list[Path] = []
    for path in root.rglob("*"):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in {".git", "build", "DerivedData", "node_modules"} for part in relative.parts[:-1]):
            continue
        if path.is_symlink():
            raise XCTestControlError(f"Cannot fingerprint symlinked WDA source: {relative}")
        if path.is_file() and (path.name in allowed_names or path.suffix in allowed_suffixes):
            files.append(path)
    if not files or project / "project.pbxproj" not in files:
        raise XCTestControlError("Cannot fingerprint driver-owned WDA source tree")
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        try:
            data = path.read_bytes()
        except OSError as error:
            raise XCTestControlError(f"Cannot fingerprint driver-owned WDA source: {path}") from error
        digest.update(len(relative).to_bytes(4, "big") + relative)
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise XCTestControlError(f"Cannot hash WDA product: {path}") from error
    return digest.hexdigest()


def _product_metadata(app: Path, xctestrun: Path, root: Path) -> dict[str, Any]:
    info_path = app / "Info.plist"
    try:
        info = plistlib.loads(info_path.read_bytes())
        document = plistlib.loads(xctestrun.read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise XCTestControlError("WDA product plist validation failed") from error
    if not isinstance(info, dict) or not isinstance(document, dict):
        raise XCTestControlError("WDA product plist has an invalid structure")
    executable_name = info.get("CFBundleExecutable")
    bundle_id = info.get("CFBundleIdentifier")
    platforms = info.get("CFBundleSupportedPlatforms")
    if not isinstance(executable_name, str) or not executable_name or not isinstance(bundle_id, str):
        raise XCTestControlError("WDA runner Info.plist omits its executable or bundle identifier")
    if not isinstance(platforms, list) or "iPhoneOS" not in platforms:
        raise XCTestControlError("WDA runner is not an iPhoneOS device product")
    executable = app / executable_name
    if not executable.is_file() or executable.is_symlink():
        raise XCTestControlError("WDA runner executable is missing or unsafe")
    code, out, err = _run_process(["lipo", "-archs", str(executable)], timeout=30)
    architectures = sorted(set(re.findall(r"\b(?:arm64e?|x86_64|i386)\b", out or err))) if code == 0 else []
    if "arm64" not in architectures:
        raise XCTestControlError("WDA runner does not contain the arm64 device architecture")
    configurations = [value for value in document.values() if isinstance(value, dict)]
    bundle_paths = [value.get("TestBundlePath") for value in configurations]
    if not any(isinstance(value, str) and "WebDriverAgentRunner" in value and value.endswith(".xctest") for value in bundle_paths):
        raise XCTestControlError("WDA .xctestrun does not reference the WebDriverAgentRunner test bundle")
    host_paths = [value.get("TestHostPath") for value in configurations if value.get("TestHostPath") is not None]
    if host_paths and not any(isinstance(value, str) and "WebDriverAgentRunner-Runner.app" in value for value in host_paths):
        raise XCTestControlError("WDA .xctestrun does not reference the runner app product")
    for path in (app, xctestrun, executable):
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as error:
            raise XCTestControlError("WDA product escapes owned DerivedData") from error
    return {
        "architectures": architectures, "bundle_id": bundle_id,
        "executable": executable_name, "info_plist_sha256": _sha256_file(info_path),
        "runner_executable_sha256": _sha256_file(executable),
        "xctestrun_sha256": _sha256_file(xctestrun),
    }


def _signature_metadata(app: Path) -> dict[str, Any]:
    verify_code, _, verify_error = _run_process(["codesign", "--verify", "--strict", str(app)], timeout=30)
    if verify_code:
        raise XCTestControlError(f"WDA runner strict code-signature verification failed: {verify_error}".rstrip())
    code, out, err = _run_process(["codesign", "-d", "--verbose=4", str(app)], timeout=30)
    detail = "\n".join((out, err))
    if code:
        raise XCTestControlError("WDA runner does not have a readable code signature")
    values: dict[str, str] = {}
    for line in detail.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            if key in {"Identifier", "TeamIdentifier", "Authority"} and key not in values:
                values[key] = value.strip()
    if not values.get("TeamIdentifier") or not values.get("Identifier") or "Apple Development" not in detail:
        raise XCTestControlError("WDA runner is not signed by an Apple Development identity")

    profile = app / "embedded.mobileprovision"
    if not profile.is_file() or profile.is_symlink():
        raise XCTestControlError("WDA runner omits its embedded provisioning profile")
    pcode, pout, perr = _run_process(["security", "cms", "-D", "-i", str(profile)], timeout=30)
    if pcode:
        raise XCTestControlError(f"Cannot decode WDA provisioning profile: {perr or pout}")
    try:
        provision = plistlib.loads(pout.encode())
    except plistlib.InvalidFileException as error:
        raise XCTestControlError("WDA provisioning profile is invalid") from error
    if not isinstance(provision, dict):
        raise XCTestControlError("WDA provisioning profile has an invalid structure")
    teams = provision.get("TeamIdentifier", [])
    if not isinstance(teams, list) or values["TeamIdentifier"] not in teams:
        raise XCTestControlError("WDA provisioning profile team does not match its signature")
    expiration = provision.get("ExpirationDate")
    if not isinstance(expiration, datetime):
        raise XCTestControlError("WDA provisioning profile omits its expiration")
    expiration = expiration.replace(tzinfo=expiration.tzinfo or timezone.utc)
    if expiration <= datetime.now(timezone.utc):
        raise XCTestControlError("WDA provisioning profile has expired")
    profile_certificates = provision.get("DeveloperCertificates", [])
    profile_hashes = {
        hashlib.sha1(bytes(value)).hexdigest().upper()
        for value in profile_certificates
        if isinstance(value, (bytes, bytearray))
    }
    if not profile_hashes:
        raise XCTestControlError("WDA provisioning profile omits developer certificates")
    with tempfile.TemporaryDirectory() as temporary:
        prefix = Path(temporary) / "signer"
        extract_code, _, extract_error = _run_process(
            ["codesign", "-d", f"--extract-certificates={prefix}", str(app)], timeout=30
        )
        leaf = Path(str(prefix) + "0")
        if extract_code or not leaf.is_file():
            raise XCTestControlError(
                f"Cannot extract the WDA signing certificate: {extract_error}".rstrip()
            )
        certificate_sha1 = hashlib.sha1(leaf.read_bytes()).hexdigest().upper()
    if certificate_sha1 not in profile_hashes:
        raise XCTestControlError(
            "WDA signing certificate is not authorized by its provisioning profile"
        )
    entitlements = provision.get("Entitlements")
    application_identifier = entitlements.get("application-identifier") if isinstance(entitlements, dict) else None
    if not isinstance(application_identifier, str) or not application_identifier.startswith(values["TeamIdentifier"] + "."):
        raise XCTestControlError("WDA provisioning application identifier does not match its team")
    return {
        "team_id": values["TeamIdentifier"], "bundle_id": values["Identifier"],
        "authority": "Apple Development", "certificate_sha1": certificate_sha1,
        "profile_expires_at": expiration.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile_uuid": provision.get("UUID"),
        "free_team": bool(provision.get("LocalProvision")),
        "profile_name": provision.get("Name"),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _process_start(pid: int) -> str | None:
    code, out, _ = _run_process(["ps", "-o", "lstart=", "-p", str(pid)], timeout=5)
    value = " ".join(out.split())
    return value if code == 0 and value else None


def _remove_appium_receipt_if_matches(pid: int, nonce: str) -> None:
    try:
        payload = json.loads(APPIUM_OWNER_RECEIPT.read_text())
        if payload.get("pid") == pid and payload.get("nonce") == nonce:
            APPIUM_OWNER_RECEIPT.unlink()
    except (OSError, json.JSONDecodeError):
        pass


@dataclass(frozen=True)
class _OwnedWDAProcess:
    pid: int
    parent_pid: int
    process_start: str
    command: str


def _owned_appium_identity(receipt: dict[str, Any] | None = None) -> tuple[int, str, str, bool] | None:
    """Return receipt-owned Appium identity only while PID ancestry is usable."""
    if receipt is None:
        try:
            receipt = json.loads(APPIUM_OWNER_RECEIPT.read_text())
        except (OSError, json.JSONDecodeError):
            return None
    pid = receipt.get("pid")
    nonce = receipt.get("nonce")
    process_start = receipt.get("process_start")
    executable = receipt.get("executable")
    receipt_command = receipt.get("command")
    valid = (
        receipt.get("schema") == APPIUM_OWNER_SCHEMA and receipt.get("owner") == OWNER
        and isinstance(pid, int) and pid > 1
        and isinstance(nonce, str) and len(nonce) == 32
        and isinstance(process_start, str) and process_start == _process_start(pid)
        and isinstance(executable, str) and bool(executable)
        and isinstance(receipt_command, list) and bool(receipt_command)
        and receipt_command[0] == executable
        and all(isinstance(value, str) and value for value in receipt_command)
    )
    if not valid:
        return None
    direct_owned = _SERVER is not None and _SERVER.pid == pid and _SERVER.poll() is None
    if direct_owned:
        return pid, nonce, process_start, True
    code, command, _ = _run_process(
        ["ps", "eww", "-o", "command=", "-p", str(pid)], timeout=5
    )
    expected_command = all(value in command for value in receipt_command)
    cross_process_owned = (
        code == 0 and executable in command and expected_command
        and f"IPAD_AGENT_OWNER_NONCE={nonce}" in command
    )
    return (pid, nonce, process_start, False) if cross_process_owned else None


def _is_owned_wda_xcodebuild_command(command: str) -> bool:
    """Constrain teardown to XCTest launched from project-owned DerivedData."""
    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    xcodebuild_indexes = [
        index for index, value in enumerate(arguments)
        if Path(value).name == "xcodebuild"
    ]
    if not xcodebuild_indexes or "test-without-building" not in arguments:
        return False
    for value in arguments:
        if not value.endswith(".xctestrun"):
            continue
        try:
            candidate = require_runtime_path(Path(value))
            relative = candidate.relative_to(DERIVED_DATA_ROOT)
        except (OSError, ValueError):
            continue
        if len(relative.parts) >= 2 and relative.parts[0] not in {"", ".", ".."}:
            return True
    return False


def _capture_owned_wda_descendants(server_pid: int) -> list[_OwnedWDAProcess]:
    """Capture qualifying descendants before the receipt-owned ancestry is broken."""
    pending = [server_pid]
    seen = {server_pid}
    captured: list[_OwnedWDAProcess] = []
    while pending:
        parent = pending.pop()
        code, output, error = _run_process(["pgrep", "-P", str(parent)], timeout=5)
        if code == 1:
            continue
        if code != 0:
            raise XCTestControlError(
                f"Cannot capture Appium descendant ancestry: {error or output or f'pgrep exited {code}'}",
                code="wda_cleanup_incomplete",
            )
        children = [int(value) for value in output.split() if value.isdigit()]
        for pid in children:
            if pid <= 1 or pid in seen:
                continue
            seen.add(pid)
            process_start = _process_start(pid)
            command_code, command, command_error = _run_process(
                ["ps", "-o", "command=", "-p", str(pid)], timeout=5
            )
            if process_start is None or command_code != 0:
                raise XCTestControlError(
                    f"Appium descendant {pid} changed while ownership ancestry was captured: {command_error}",
                    code="wda_cleanup_incomplete",
                )
            pending.append(pid)
            if _is_owned_wda_xcodebuild_command(command):
                captured.append(_OwnedWDAProcess(pid, parent, process_start, command))
    return captured


def _record_is_alive(process: _OwnedWDAProcess) -> bool:
    return _process_start(process.pid) == process.process_start


def _wait_for_records(records: list[_OwnedWDAProcess], deadline: float) -> list[_OwnedWDAProcess]:
    remaining = [process for process in records if _record_is_alive(process)]
    while remaining and time.monotonic() < deadline:
        time.sleep(0.05)
        remaining = [process for process in remaining if _record_is_alive(process)]
    return remaining


def _signal_records(records: list[_OwnedWDAProcess], sent_signal: signal.Signals) -> list[int]:
    signalled: list[int] = []
    for process in records:
        if not _is_owned_wda_xcodebuild_command(process.command) or not _record_is_alive(process):
            continue
        try:
            os.kill(process.pid, sent_signal)
            signalled.append(process.pid)
        except ProcessLookupError:
            pass
        except OSError:
            # The bounded wait and final liveness proof report this honestly.
            pass
    return signalled


def _terminate_wda_xcodebuild(
    *, server_pid: int | None = None,
    captured: list[_OwnedWDAProcess] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Boundedly terminate only ancestry- and command-proven WDA xcodebuild PIDs."""
    if server_pid is None:
        ownership = _owned_appium_identity()
        if ownership is None:
            return {"complete": False, "reason": "ownership_not_proven", "captured_pids": [], "remaining_pids": []}
        server_pid = ownership[0]
    try:
        records = list(captured) if captured is not None else _capture_owned_wda_descendants(server_pid)
    except XCTestControlError as error:
        return {
            "complete": False, "reason": "descendant_capture_failed",
            "detail": str(error), "captured_pids": [], "remaining_pids": [],
        }
    if any(not _is_owned_wda_xcodebuild_command(process.command) for process in records):
        return {
            "complete": False, "reason": "descendant_constraint_failed",
            "captured_pids": sorted(process.pid for process in records),
            "remaining_pids": sorted(process.pid for process in records if _record_is_alive(process)),
        }

    timeout = max(0.0, float(timeout))
    deadline = time.monotonic() + timeout
    terminated = _signal_records(records, signal.SIGTERM)
    term_deadline = min(deadline, time.monotonic() + min(1.0, timeout / 2.0))
    remaining = _wait_for_records(records, term_deadline)
    killed = _signal_records(remaining, signal.SIGKILL)
    remaining = _wait_for_records(remaining, deadline)
    if remaining:
        return {
            "complete": False, "reason": "descendant_termination_timeout",
            "captured_pids": sorted(process.pid for process in records),
            "terminated_pids": sorted(terminated), "killed_pids": sorted(killed),
            "remaining_pids": sorted(process.pid for process in remaining),
        }
    try:
        final = _capture_owned_wda_descendants(server_pid)
    except XCTestControlError as error:
        return {
            "complete": False, "reason": "descendant_final_proof_failed", "detail": str(error),
            "captured_pids": sorted(process.pid for process in records),
            "terminated_pids": sorted(terminated), "killed_pids": sorted(killed),
            "remaining_pids": [],
        }
    return {
        "complete": not final,
        "reason": "complete" if not final else "new_wda_descendant_detected",
        "captured_pids": sorted(process.pid for process in records),
        "terminated_pids": sorted(terminated), "killed_pids": sorted(killed),
        "remaining_pids": sorted(process.pid for process in final),
    }


def _wait_for_appium_exit(pid: int, *, direct_owned: bool, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if direct_owned and _SERVER is not None and _SERVER.pid == pid and _SERVER.poll() is not None:
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return True
        time.sleep(0.05)
    return False


def stop_owned_appium_server(*, timeout: float = 10.0) -> dict[str, Any]:
    """Stop receipt-owned Appium and only its constrained, captured WDA descendants."""
    global _SERVER
    try:
        receipt = json.loads(APPIUM_OWNER_RECEIPT.read_text())
    except FileNotFoundError:
        return {"stopped": False, "reason": "no_owned_server_receipt"}
    except (OSError, json.JSONDecodeError):
        return {"stopped": False, "reason": "invalid_owned_server_receipt"}
    identity = _owned_appium_identity(receipt)
    pid = receipt.get("pid")
    if identity is None:
        return {"stopped": False, "reason": "ownership_not_proven", "pid": pid if isinstance(pid, int) else None}
    pid, nonce, process_start, direct_owned = identity

    # Capture and clean descendants before stopping Appium destroys ancestry.
    descendants = _terminate_wda_xcodebuild(server_pid=pid, timeout=timeout)
    if isinstance(descendants, dict) and descendants.get("complete") is not True:
        return {
            "stopped": False, "reason": "descendant_cleanup_incomplete", "pid": pid,
            "descendants": descendants,
        }
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as error:
        return {"stopped": False, "reason": f"terminate_failed:{type(error).__name__}", "pid": pid}
    timeout = max(0.0, float(timeout))
    deadline = time.monotonic() + timeout
    exited = _wait_for_appium_exit(pid, direct_owned=direct_owned, deadline=deadline)
    killed = False
    if not exited and _process_start(pid) == process_start:
        try:
            os.kill(pid, signal.SIGKILL)
            killed = True
        except ProcessLookupError:
            exited = True
        except OSError as error:
            return {"stopped": False, "reason": f"kill_failed:{type(error).__name__}", "pid": pid}
        if not exited:
            exited = _wait_for_appium_exit(
                pid, direct_owned=direct_owned,
                deadline=time.monotonic() + min(2.0, max(0.1, timeout)),
            )
    if not exited:
        return {"stopped": False, "reason": "terminate_timeout", "pid": pid, "descendants": descendants}

    _remove_appium_receipt_if_matches(pid, nonce)
    if _SERVER is not None and _SERVER.pid == pid:
        _SERVER = None
    return {"stopped": True, "pid": pid, "killed": killed, "descendants": descendants}


def _run_process(command: list[str], *, timeout: float) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", str(error)


__all__ = [
    "AppiumSession", "WDASelection", "XCTestConfig", "XCTestControlError",
    "artifact_directory", "build_for_testing", "default_wda_bundle",
    "ensure_appium_server", "locate_driver_wda_project", "make_selection",
    "short_session", "stop_owned_appium_server", "validate_artifact", "verification_path", "verified",
    "verify_bounded_session",
]
