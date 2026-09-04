"""Read-only, rerunnable host/device/signing/WDA state inspection."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse

from ipad_agent.maintenance.bootstrap import APPIUM, APPIUM_HOME, node_remediation, resolve_node_toolchain
from ipad_agent.core.config import Config, load_config
from ipad_agent.core.paths import require_runtime_path
from ipad_agent.maintenance.versions import APPIUM_VERSION, DOCTOR_SCHEMA, XCUITEST_VERSION, version_tuple
from ipad_agent.transports import airdrop, wda


@dataclass
class Check:
    id: str
    status: str
    message: str
    stage: str = "host"
    evidence: dict[str, Any] | None = None
    human_action: str | None = None
    remediation: str | None = None


class _DoctorReport(dict[str, Any]):
    """Public JSON projection carrying an in-process-only transition report."""

    def __init__(self, public: dict[str, Any], internal: dict[str, Any]) -> None:
        super().__init__(public)
        self._internal = internal


def run_doctor(config: Config | None = None) -> dict[str, Any]:
    """Return stable redacted v2 diagnostics without persisting probe state."""
    try:
        selected_config = config or load_config()
        internal = _run_doctor(selected_config)
    except Exception as error:
        message = " ".join(str(error).split())[:2000] or type(error).__name__
        check = Check(
            "doctor.internal", "fail", message, remediation="Fix the reported local configuration or tool error, then rerun: python3 -m ipad_agent doctor --json",
        )
        internal = _report([check], {})
    return _DoctorReport(public_report(internal), internal)


def internal_report(report: dict[str, Any]) -> dict[str, Any]:
    """Recover rich state only for setup transitions in this process."""
    value = getattr(report, "_internal", None)
    return value if isinstance(value, dict) else report


def _run_doctor(config: Config) -> dict[str, Any]:
    checks: list[Check] = []
    selected: dict[str, Any] = {"device_identifier": None, "device_udid": None, "team_id": None, "wda_bundle_id": None, "wda_fingerprint": None, "xctestrun": None, "wda_artifact_receipt": None}

    checks.append(Check("host.macos", "pass" if sys.platform == "darwin" else "fail", platform.platform(), remediation=None if sys.platform == "darwin" else "Run ipad-agent on a Mac; CoreDevice and physical-device XCTest are unavailable on this host."))
    py_ok = sys.version_info >= (3, 11)
    checks.append(Check("host.python", "pass" if py_ok else "fail", platform.python_version(), remediation=None if py_ok else "Run this checkout with Python 3.11 or newer; do not install packages with pip."))

    xcode = _run(["xcodebuild", "-version"])
    xcode_ok = xcode[0] == 0
    xcode_message = (xcode[1] or xcode[2] or "xcodebuild unavailable").splitlines()[0]
    checks.append(Check("host.xcode", "pass" if xcode_ok else "fail", xcode_message, evidence={"version": " | ".join(xcode[1].splitlines())} if xcode[1] else None, remediation=None if xcode_ok else "Install full Xcode, open it once, and select it with: sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer"))

    if xcode_ok:
        license_probe = _run(["xcodebuild", "-license", "check"])
        license_ok = license_probe[0] == 0
        checks.append(Check("host.xcode_license", "pass" if license_ok else "action_required", "Xcode license accepted" if license_ok else "Xcode license is not accepted", human_action=None if license_ok else "In Terminal, run `sudo xcodebuild -license`, read the license, and accept it; then rerun doctor."))
        first = _run(["xcodebuild", "-checkFirstLaunchStatus"])
        first_ok = first[0] == 0
        checks.append(Check("host.xcode_first_launch", "pass" if first_ok else "action_required", "Xcode first-launch components are ready" if first_ok else "Xcode first-launch setup is incomplete", human_action=None if first_ok else "Open Xcode and complete its first-launch component installation, or run `sudo xcodebuild -runFirstLaunch`; then rerun doctor."))
    else:
        checks.extend([_skipped("host.xcode_license", "host", "Full Xcode is unavailable"), _skipped("host.xcode_first_launch", "host", "Full Xcode is unavailable")])

    device_find = _run(["xcrun", "--find", "devicectl"]) if xcode_ok else (127, "", "")
    devicectl_ok = device_find[0] == 0
    checks.append(Check("host.devicectl", "pass" if devicectl_ok else ("fail" if xcode_ok else "skipped"), device_find[1] or device_find[2] or "devicectl unavailable", remediation=None if devicectl_ok or not xcode_ok else "Select a full Xcode installation that provides `xcrun devicectl`; no static macOS-version assumption is used."))

    toolchain = resolve_node_toolchain()
    node_ok = bool(toolchain["compatible"])
    checks.append(Check("host.node", "pass" if node_ok else "fail", f"Node {toolchain.get('node_version')}" if node_ok else "No compatible Node.js/npm toolchain was found", evidence={key: toolchain.get(key) for key in ("node", "node_version", "npm", "npm_version")}, remediation=None if node_ok else node_remediation()))
    checks.append(Check("host.npm", "pass" if node_ok else "fail", f"npm {toolchain.get('npm_version')}" if node_ok else "npm 10+ paired with a compatible Node.js is unavailable", evidence={"path": toolchain.get("npm"), "version": toolchain.get("npm_version")}, remediation=None if node_ok else node_remediation()))

    _config_checks(config, checks)
    _airdrop_checks(config, checks, xcode_ok=xcode_ok)
    appium_ok, driver_ok = _automation_checks(checks, node_ok)

    devices: list[dict[str, Any]] = []
    devices_observable = False
    if devicectl_ok:
        device_code, devices, device_error = _devices_probe()
        devices_observable = device_code == 0
    else:
        device_error = "devicectl unavailable"
    paired = [item for item in devices if _is_paired_ipad(item)]
    if config.device:
        paired = [item for item in paired if config.device in _device_ids(item)]
    device: dict[str, str] | None = None
    if not devicectl_ok:
        checks.append(_skipped("device.paired", "device", "devicectl is unavailable"))
    elif not devices_observable:
        checks.append(Check("device.paired", "unknown", "CoreDevice device list could not be read", "device", evidence={"error": device_error}, remediation="Reconnect the iPad and rerun `xcrun devicectl list devices`; if it succeeds, rerun doctor."))
    elif len(paired) == 1:
        item = paired[0]
        props = item.get("deviceProperties", {}); hardware = item.get("hardwareProperties", {})
        device = {"identifier": str(item.get("identifier")), "udid": str(hardware.get("udid")), "version": str(props.get("osVersionNumber"))}
        selected["device_identifier"] = device["identifier"]; selected["device_udid"] = device["udid"]
        checks.append(Check("device.paired", "pass", "One selected paired physical iPad is available", "device", {"identifier": device["identifier"], "udid": device["udid"], "model": hardware.get("marketingName"), "os": device["version"]}))
    elif not paired:
        suffix = " matching device.id" if config.device else ""
        checks.append(Check("device.paired", "action_required", f"No paired physical iPad{suffix} was found", "device", human_action="Connect the intended iPad by cable, unlock it, tap Trust on the iPad, approve Trust This Computer on the Mac if shown, then rerun doctor."))
    else:
        checks.append(Check("device.paired", "action_required", "Multiple paired physical iPads are available", "device", {"count": len(paired)}, human_action="Choose the intended iPad, then set its CoreDevice identifier or UDID as device.id in .runtime/config/config.toml and rerun doctor."))

    if device:
        props = paired[0].get("deviceProperties", {})
        developer = props.get("developerModeStatus")
        enabled = developer == "enabled"
        checks.append(Check("device.developer_mode", "pass" if enabled else "action_required", "Developer Mode is enabled" if enabled else f"Developer Mode is {developer or 'not enabled'}", "device", human_action=None if enabled else "On iPad, open Settings > Privacy & Security > Developer Mode, turn it on, restart the iPad, confirm Enable, then unlock it and rerun doctor."))
        locked = _lock_state(device["identifier"])
        checks.append(Check("device.unlocked", "action_required" if locked is True else ("pass" if locked is False else "unknown"), "iPad requires authentication" if locked is True else ("iPad is unlocked" if locked is False else "iPad lock state could not be read"), "device", human_action="Unlock the iPad with Face ID, Touch ID, or its passcode and leave it awake; ipad-agent will never request or enter the passcode." if locked is True else None, remediation="Reconnect the iPad and rerun doctor to inspect lock state." if locked is None else None))
        browser_bundle = config.browser_bundle
        app_code, apps, app_error = _apps_probe(device["identifier"])
        installed = app_code == 0 and _exact_bundle_installed(apps, browser_bundle)
        status = "pass" if installed else ("action_required" if app_code == 0 else "unknown")
        browser_name = config.browser
        checks.append(Check("device.browser", status, f"{browser_name} ({browser_bundle}) is installed" if installed else (f"{browser_name} ({browser_bundle}) is not installed" if app_code == 0 else "Installed apps could not be inspected"), "device", evidence={"bundle_id": browser_bundle, "error": app_error or None}, human_action=None if status != "action_required" else f"On iPad, install or restore {browser_name} from the App Store, open it once, then rerun doctor.", remediation="Rerun `xcrun devicectl device info apps --device <device-id>` after reconnecting the iPad." if status == "unknown" else None))
    else:
        checks.extend([_skipped("device.developer_mode", "device", "No device is selected"), _skipped("device.unlocked", "device", "No device is selected"), _skipped("device.browser", "device", "No device is selected")])

    identity_probe = _run(["security", "find-identity", "-v", "-p", "codesigning"])
    identities = _apple_development_identities(identity_probe[1]) if identity_probe[0] == 0 else []
    identity_sha1s = {item["sha1"] for item in identities}
    preference_teams = _xcode_provisioning_teams()
    identity_teams = _identity_team_evidence(identity_sha1s)
    linked_pairs = sorted(
        (sha1, team_id)
        for sha1, teams in identity_teams.items()
        for team_id in teams
    )
    available_teams = sorted(set(preference_teams) | {item[1] for item in linked_pairs})
    configured_team = config.team_id
    candidates = [
        pair for pair in linked_pairs
        if configured_team is None or pair[1] == configured_team
    ]
    unlinked_identities = sorted(identity_sha1s - set(identity_teams))
    if len(candidates) == 1 and not unlinked_identities:
        identity_sha1, team = candidates[0]
        selected["team_id"] = team
        checks.append(Check(
            "signing.identity", "pass", "One Apple Development identity is cryptographically tied to the selected team", "signing",
            {
                "team_id": team,
                "identity_count": len(identities),
                "linked_identity_count": len({item[0] for item in linked_pairs}),
                "team_sources": identity_teams[identity_sha1][team],
            },
        ))
    elif not identities:
        team = None
        message = (identity_probe[2] or identity_probe[1]).casefold()
        keychain = "keychain" in message or "interaction is not allowed" in message
        action = "Unlock the login keychain in Keychain Access, approve any keychain prompt yourself, then rerun doctor." if keychain else "In Xcode > Settings > Accounts, sign in to the intended Apple account and use Manage Certificates to create an Apple Development certificate; complete any Apple ID, 2FA, signing, provisioning, or keychain prompts yourself, then rerun doctor."
        checks.append(Check("signing.identity", "action_required", "No usable Apple Development identity is available", "signing", human_action=action))
    elif configured_team and not candidates:
        team = None
        checks.append(Check("signing.identity", "action_required", "The configured development team has no matching local Apple Development identity", "signing", {"configured_team": configured_team, "available_teams": available_teams}, human_action="In Xcode > Settings > Accounts, select the intended Apple account and refresh its team/provisioning data. Complete Apple ID, 2FA, signing, or keychain prompts yourself, then rerun doctor."))
    elif not linked_pairs:
        team = None
        checks.append(Check("signing.identity", "action_required", "Installed Apple Development identities cannot be tied to a team", "signing", {"identity_count": len(identities), "preference_teams": sorted(preference_teams)}, human_action="In Xcode > Settings > Accounts, refresh the intended team's signing certificate and provisioning profiles. Complete Apple ID, 2FA, signing, provisioning, or keychain prompts yourself, then rerun doctor."))
    else:
        team = None
        checks.append(Check("signing.identity", "action_required", "Signing identity/team selection is ambiguous", "signing", {"candidate_count": len(candidates), "unlinked_identity_count": len(unlinked_identities), "teams": sorted({item[1] for item in candidates})}, human_action="Remove or revoke obsolete local Apple Development identities, or set automation.team_id to a team with exactly one matching identity; complete keychain or account prompts yourself, then rerun doctor."))

    bundle = config.wda_bundle_id or (wda.default_wda_bundle(team) if team else None)
    selected["wda_bundle_id"] = bundle
    checks.append(Check("signing.selection", "pass" if team and bundle else "skipped", f"Selected team {team} and WDA bundle {bundle}" if team and bundle else "Signing selection is incomplete", "signing", {"team_id": team, "bundle_id": bundle} if team and bundle else None))

    selection = None
    source_ok = False
    if driver_ok:
        try:
            source = wda.locate_driver_wda_project()
            source_ok = True
            checks.append(Check("automation.wda_source", "pass", "Driver-owned WebDriverAgent source located", "wda", {"project": str(source), "driver_version": XCUITEST_VERSION}))
        except wda.XCTestControlError as error:
            checks.append(Check("automation.wda_source", "fail", str(error), "wda", remediation="Run: python3 -m ipad_agent setup --phase host --apply --json"))
    else:
        checks.append(_skipped("automation.wda_source", "wda", "Pinned XCUITest driver is unavailable"))

    if source_ok and device and team and bundle and xcode_ok:
        try:
            selection = wda.make_selection(device=device, team=team, bundle_id=bundle, xcode=" | ".join(xcode[1].splitlines()))
            selected["wda_fingerprint"] = selection.fingerprint
            artifact = wda.validate_artifact(wda.artifact_directory(selection), selection=selection)
            selected["xctestrun"] = artifact["xctestrun"]
            selected["wda_artifact_receipt"] = str(wda.artifact_directory(selection) / wda.ARTIFACT_FILE)
            checks.append(Check("automation.wda_build", "pass", "Fingerprinted WDA build-for-testing artifact exists", "wda", {"fingerprint": selection.fingerprint, "xctestrun": artifact["xctestrun"], "runtime": artifact.get("runtime")}))
            checks.append(Check("automation.wda_provenance", "pass", "WDA source, device, team, bundle, xctestrun, product, architecture, and signature provenance match", "wda", {"signature": artifact.get("signature"), "product": artifact.get("product")}))
            runtime_matches = config.team_id == team and config.wda_bundle_id == bundle and config.xctestrun == artifact["xctestrun"]
            checks.append(Check("automation.runtime_config", "pass" if runtime_matches else "fail", "Normal runtime config selects this owned WDA artifact" if runtime_matches else "Normal runtime config does not select this owned WDA artifact", "wda", {"configured_xctestrun": config.xctestrun, "artifact_xctestrun": artifact["xctestrun"], "fingerprint": selection.fingerprint}, remediation=None if runtime_matches else "Run: python3 -m ipad_agent setup --phase wda --apply --json"))
            is_verified = wda.verified(selection)
            checks.append(_developer_trust_check(session_verified=is_verified))
            checks.append(Check("automation.session_verified", "pass" if is_verified else "fail", "Bounded Appium/WDA session verification succeeded" if is_verified else "This exact WDA fingerprint has not completed bounded session verification", "verify", remediation=None if is_verified else "Run only when the iPad is awake and unlocked: python3 -m ipad_agent setup --phase verify --apply --json"))
        except wda.XCTestControlError as error:
            checks.append(Check("automation.wda_build", "fail", "No valid build-for-testing artifact exists for the current fingerprint", "wda", {"error": str(error)}, remediation="Run: python3 -m ipad_agent setup --phase wda --apply --json"))
            checks.append(_skipped("automation.wda_provenance", "wda", "No valid current artifact"))
            checks.append(_skipped("automation.runtime_config", "wda", "No valid current artifact"))
            checks.append(_skipped("device.developer_trust", "verify", "No signed current WDA artifact"))
            checks.append(_skipped("automation.session_verified", "verify", "No valid current WDA artifact"))
    else:
        checks.extend([_skipped("automation.wda_build", "wda", "WDA build prerequisites are incomplete"), _skipped("automation.wda_provenance", "wda", "WDA build prerequisites are incomplete"), _skipped("automation.runtime_config", "wda", "WDA build prerequisites are incomplete"), _skipped("device.developer_trust", "verify", "No signed current WDA artifact"), _skipped("automation.session_verified", "verify", "No valid current WDA artifact")])

    return _report(checks, selected)


def _developer_trust_check(*, session_verified: bool) -> Check:
    """Report only launch evidence; receipt absence is not a trust failure."""
    if session_verified:
        return Check(
            "device.developer_trust", "pass",
            "The bounded WDA launch did not report an untrusted developer",
            "verify",
        )
    return Check(
        "device.developer_trust", "skipped",
        "Trust is requested only after an actual bounded WDA launch reports an untrusted developer",
        "verify",
    )


def _config_checks(config: Config, checks: list[Check]) -> None:
    endpoint = urlparse(config.appium_url)
    try:
        port = endpoint.port or 4723
    except ValueError:
        port = 0
    local = endpoint.scheme == "http" and endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and 1 <= port <= 65535
    checks.append(Check("config.appium_url", "pass" if local else "fail", "Appium endpoint is loopback-only" if local else "Appium URL is not safe", "host", remediation=None if local else "Set automation.appium_url to http://127.0.0.1:4723 or another loopback HTTP port."))
    host_ok = config.display_host is None or _reachable_private_ipv4(config.display_host)
    checks.append(Check("config.display_host", "pass" if host_ok else "fail", "Display host is discoverable/private" if host_ok else "Display host is not one RFC1918 IPv4 address", "host", remediation=None if host_ok else "Set display.host to the Mac's reachable RFC1918 IPv4 address, never wildcard or loopback."))


def _airdrop_checks(config: Config, checks: list[Check], *, xcode_ok: bool) -> None:
    """Report optional local-transfer readiness without exposing its policy."""
    sources_ready = all(_project_regular_file(path) for path in (
        airdrop.HELPER_SOURCE, airdrop.HELPER_BUILD_SCRIPT,
    ))
    swift = _run(["xcrun", "--sdk", "macosx", "swiftc", "--version"]) if xcode_ok else (127, "", "")
    swift_ok = xcode_ok and swift[0] == 0 and sources_ready
    checks.append(Check(
        "host.swift", "pass" if swift_ok else ("fail" if xcode_ok else "skipped"),
        "Swift and the project-owned AirDrop helper sources are buildable" if swift_ok else "The AirDrop helper build prerequisites are incomplete",
        "host", {"buildable": swift_ok},
        remediation=None if swift_ok or not xcode_ok else "Select a full Xcode installation with the macOS SDK and Swift compiler, restore the project-owned helper sources if needed, then rerun host setup.",
    ))

    policy_configured = bool(
        config.airdrop_allowed_roots
        and config.airdrop_allowed_extensions
        and config.airdrop_max_bytes is not None
    )
    checks.append(Check(
        "airdrop.policy", "pass" if policy_configured else "fail",
        "AirDrop local-file policy is configured" if policy_configured else "AirDrop local-file policy is not configured",
        "host", {"configured": policy_configured},
        remediation=None if policy_configured else "Configure AirDrop allowed_roots, allowed_extensions, and max_bytes explicitly in the project-local config before local file transfer; setup will not choose them.",
    ))

    helper_ready = _airdrop_helper_ready()
    checks.append(Check(
        "airdrop.helper", "pass" if helper_ready else "fail",
        "The project-owned AirDrop helper is built and ready" if helper_ready else "The project-owned AirDrop helper is not built and ready",
        "host", {"ready": helper_ready},
        remediation=None if helper_ready else "Run: python3 -m ipad_agent setup --phase host --apply --json",
    ))


def _project_regular_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
        return path.resolve(strict=True) == path and stat.S_ISREG(metadata.st_mode)
    except OSError:
        return False


def _airdrop_helper_ready() -> bool:
    """Accept only a current, owned executable at the fixed runtime location."""
    helper = airdrop.HELPER_BINARY
    try:
        metadata = helper.lstat()
        sources = (airdrop.HELPER_SOURCE, airdrop.HELPER_BUILD_SCRIPT)
        return (
            helper.is_file()
            and not helper.is_symlink()
            and metadata.st_uid == os.getuid()
            and os.access(helper, os.X_OK)
            and all(_project_regular_file(path) for path in sources)
            and metadata.st_mtime_ns >= max(path.stat().st_mtime_ns for path in sources)
        )
    except OSError:
        return False


def _installed_npm_package_version(path: Path, *, expected_name: str) -> str | None:
    """Read repository-local npm metadata without executing package code."""
    try:
        candidate = require_runtime_path(path)
        descriptor = os.open(
            candidate,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 1_000_000:
                return None
            with os.fdopen(descriptor, "r", encoding="utf-8", closefd=True) as handle:
                descriptor = -1
                payload = json.load(handle)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("name") != expected_name:
        return None
    version = payload.get("version")
    return version if isinstance(version, str) and version else None


def _automation_checks(checks: list[Check], node_ok: bool) -> tuple[bool, bool]:
    if not node_ok:
        checks.append(_skipped("automation.appium", "host", "Compatible Node.js/npm is unavailable"))
        checks.append(_skipped("automation.xcuitest_driver", "host", "Pinned Appium is unavailable"))
        return False, False

    appium_package = APPIUM.parents[1] / "appium" / "package.json"
    version = _installed_npm_package_version(appium_package, expected_name="appium")
    appium_ok = version == APPIUM_VERSION
    checks.append(Check(
        "automation.appium", "pass" if appium_ok else "fail",
        f"Appium {version}" if version else "Repository-local Appium is unavailable",
        "host", {"path": str(APPIUM), "version": version},
        remediation=None if appium_ok else "Run: python3 -m ipad_agent setup --phase host --apply --json",
    ))
    if not appium_ok:
        checks.append(_skipped("automation.xcuitest_driver", "host", "Pinned Appium is unavailable"))
        return False, False

    driver_package = APPIUM_HOME / "node_modules" / "appium-xcuitest-driver" / "package.json"
    version = _installed_npm_package_version(
        driver_package, expected_name="appium-xcuitest-driver"
    )
    ok = version == XCUITEST_VERSION
    checks.append(Check(
        "automation.xcuitest_driver", "pass" if ok else "fail",
        f"XCUITest driver {version}" if version else "Repository-local XCUITest driver is unavailable",
        "host", {"version": version, "appium_home": str(APPIUM_HOME)},
        remediation=None if ok else "Run: python3 -m ipad_agent setup --phase host --apply --json",
    ))
    return appium_ok, ok


_OPTIONAL_TRANSFER_CHECKS = {"host.swift", "airdrop.policy", "airdrop.helper"}
_OPTIONAL_WDA_CHECKS = {
    "host.node", "host.npm", "config.appium_url", "device.developer_mode",
    "signing.identity", "signing.selection", "automation.appium",
    "automation.xcuitest_driver", "automation.wda_source", "automation.wda_build",
    "automation.wda_provenance", "automation.runtime_config",
    "device.developer_trust", "automation.session_verified",
}


def _report(checks: list[Check], selected: dict[str, Any]) -> dict[str, Any]:
    # Optional AirDrop and WDA readiness must not make ordinary CoreDevice app
    # launches look unavailable. Their failed checks still carry remediation.
    optional = _OPTIONAL_TRANSFER_CHECKS | _OPTIONAL_WDA_CHECKS
    blocking = [
        item for item in checks
        if item.status in {"fail", "action_required", "unknown"}
        and item.id not in optional
    ]
    statuses = {item.id: item.status for item in checks}
    if statuses.get("device.unlocked") == "action_required" or statuses.get("device.developer_mode") == "action_required":
        blocking = [item for item in blocking if item.stage not in {"wda", "verify"}]
    elif statuses.get("signing.identity") == "action_required":
        blocking = [item for item in blocking if item.stage not in {"wda", "verify"}]
    if not blocking:
        state, code = "ready", 0
    elif any(item.status == "fail" for item in blocking):
        state, code = "needs_agent_action", 20
    elif any(item.status == "unknown" for item in blocking):
        state, code = "blocked", 30
    else:
        state, code = "action_required", 10
    return {"schema": DOCTOR_SCHEMA, "state": state, "ready": not blocking, "exit_code": code, "selected": selected, "checks": [asdict(item) for item in checks], "next": [item.id for item in blocking]}


_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:/(?:[^\s\"'`<>]+/?)+|[A-Za-z]:\\(?:[^\s\"'`<>]+\\?)*)"
)
_BUNDLE_ID = re.compile(r"\b(?:[A-Za-z][A-Za-z0-9-]*\.){2,}[A-Za-z0-9-]+\b")
_DEVICE_OR_HASH = re.compile(
    r"\b(?:[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}|[0-9A-Fa-f]{24,64}|"
    r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})\b"
)
_TEAM_ID = re.compile(r"\b[A-Z0-9]{10}\b")
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


def public_text(value: Any) -> str:
    """Redact identifiers and local state from one diagnostic text field."""
    text = " ".join(str(value).split())[:2000]
    text = _ABSOLUTE_PATH.sub("<local-path>", text)
    text = _BUNDLE_ID.sub("<bundle-id>", text)
    text = _DEVICE_OR_HASH.sub("<private-id>", text)
    text = _TEAM_ID.sub("<team-id>", text)
    text = _EMAIL.sub("<account>", text)
    return text


def public_report(report: dict[str, Any]) -> dict[str, Any]:
    """Project rich probe state onto stable, useful, non-identifying evidence."""
    selected = report.get("selected") if isinstance(report.get("selected"), dict) else {}
    checks = [
        _public_check(item)
        for item in report.get("checks", [])
        if isinstance(item, dict)
    ]
    return {
        "schema": report.get("schema", DOCTOR_SCHEMA),
        "state": report.get("state", "needs_agent_action"),
        "ready": bool(report.get("ready")),
        "exit_code": int(report.get("exit_code", 20)),
        "selected": {
            "device": bool(selected.get("device_identifier") and selected.get("device_udid")),
            "signing": bool(selected.get("team_id") and selected.get("wda_bundle_id")),
            "wda_artifact": bool(selected.get("xctestrun")),
            "verified": _check_status_from_items(checks, "automation.session_verified") == "pass",
        },
        "checks": checks,
        "next": [str(value) for value in report.get("next", []) if isinstance(value, str)],
    }


def _check_status_from_items(checks: list[dict[str, Any]], identifier: str) -> str | None:
    return next((str(item.get("status")) for item in checks if item.get("id") == identifier), None)


def _public_check(check: dict[str, Any]) -> dict[str, Any]:
    identifier = str(check.get("id") or "doctor.internal")
    status = str(check.get("status") or "fail")
    message = public_text(check.get("message") or "Diagnostic check did not complete")
    if identifier == "doctor.internal":
        message = "Doctor could not complete a local configuration or tool check"
    elif identifier == "host.devicectl":
        message = "CoreDevice tooling is available" if status == "pass" else "CoreDevice tooling is unavailable"
    elif identifier == "signing.selection":
        message = "Signing and WDA bundle selection is complete" if status == "pass" else "Signing selection is incomplete"
    elif identifier == "automation.wda_source" and status == "pass":
        message = "Driver-owned WebDriverAgent source is available"
    elif identifier == "automation.wda_build" and status == "pass":
        message = "A current setup-owned WDA build artifact is valid"
    elif identifier == "automation.wda_provenance" and status == "pass":
        message = "WDA build provenance is valid"
    elif identifier == "host.swift":
        message = "Swift can build the project-owned AirDrop helper" if status == "pass" else "Swift cannot currently build the project-owned AirDrop helper"
    elif identifier == "airdrop.policy":
        message = "AirDrop local-file policy is configured" if status == "pass" else "AirDrop local-file policy requires explicit configuration"
    elif identifier == "airdrop.helper":
        message = "The project-owned AirDrop helper is built and ready" if status == "pass" else "The project-owned AirDrop helper is not ready"

    evidence = check.get("evidence")
    safe: dict[str, Any] = {}
    allowed: dict[str, tuple[str, ...]] = {
        "host.xcode": ("version",),
        "host.node": ("node_version", "npm_version"),
        "host.npm": ("version",),
        "host.swift": ("buildable",),
        "airdrop.policy": ("configured",),
        "airdrop.helper": ("ready",),
        "device.paired": ("count", "model", "os"),
        "signing.identity": (
            "identity_count", "linked_identity_count", "candidate_count",
            "unlinked_identity_count",
        ),
        "automation.appium": ("version",),
        "automation.xcuitest_driver": ("version",),
        "automation.wda_source": ("driver_version",),
    }
    if isinstance(evidence, dict):
        for key in allowed.get(identifier, ()):
            value = evidence.get(key)
            if isinstance(value, bool) or isinstance(value, (int, float)):
                safe[key] = value
            elif isinstance(value, str) and value:
                safe[key] = public_text(value)
    if identifier == "automation.wda_build" and status == "pass":
        safe["artifact_validated"] = True
    elif identifier == "automation.wda_provenance" and status == "pass":
        safe["provenance_validated"] = True
    elif identifier == "automation.runtime_config":
        safe["matches_owned_artifact"] = status == "pass"

    return {
        "id": identifier,
        "status": status,
        "message": message,
        "stage": str(check.get("stage") or "host"),
        "evidence": safe or None,
        "human_action": public_text(check["human_action"]) if check.get("human_action") else None,
        "remediation": public_text(check["remediation"]) if check.get("remediation") else None,
    }


def _skipped(identifier: str, stage: str, reason: str) -> Check:
    return Check(identifier, "skipped", reason, stage)


def _apple_development_identities(value: str) -> list[dict[str, str]]:
    """Read identity fingerprints without treating the certificate label as a team ID."""
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in value.splitlines():
        match = re.search(r"\b([0-9A-Fa-f]{40})\b.*\"Apple Development:", line)
        if match and match.group(1).upper() not in seen:
            sha1 = match.group(1).upper()
            seen.add(sha1)
            result.append({"sha1": sha1})
    return result


def _xcode_provisioning_teams() -> dict[str, list[str]]:
    """Return deduplicated DEVELOPMENT_TEAM values from Xcode's plist preferences."""
    code, out, _ = _run(["defaults", "export", "com.apple.dt.Xcode", "-"], timeout=20)
    if code or not out:
        return {}
    try:
        document = plistlib.loads(out.encode())
    except plistlib.InvalidFileException:
        return {}
    table = document.get("IDEProvisioningTeamByIdentifier") if isinstance(document, dict) else None
    teams: dict[str, list[str]] = {}
    if not isinstance(table, dict):
        return teams
    for records in table.values():
        if not isinstance(records, list):
            continue
        for record in records:
            team = record.get("teamID") if isinstance(record, dict) else None
            if isinstance(team, str) and re.fullmatch(r"[A-Z0-9]{10}", team):
                teams.setdefault(team, []).append("xcode_preferences")
    return {team: sorted(set(sources)) for team, sources in sorted(teams.items())}


def _identity_team_evidence(identity_sha1s: set[str]) -> dict[str, dict[str, list[str]]]:
    """Tie installed signing identities to teams using certificate/profile evidence."""
    result = _certificate_identity_teams(identity_sha1s)
    profile_links = _provisioning_identity_teams(identity_sha1s)
    for sha1, teams in profile_links.items():
        for team, sources in teams.items():
            result.setdefault(sha1, {}).setdefault(team, []).extend(sources)
    return {
        sha1: {
            team: sorted(set(sources))
            for team, sources in sorted(teams.items())
        }
        for sha1, teams in sorted(result.items())
        if teams
    }


def _certificate_identity_teams(identity_sha1s: set[str]) -> dict[str, dict[str, list[str]]]:
    """Read the team OU from the exact keychain certificates reported as identities."""
    if not identity_sha1s:
        return {}
    code, out, _ = _run(["security", "find-certificate", "-a", "-Z", "-p"], timeout=20)
    if code or not out:
        return {}
    pattern = re.compile(
        r"SHA-1 hash:\s*([0-9A-Fa-f]{40}).*?"
        r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)",
        re.DOTALL,
    )
    result: dict[str, dict[str, list[str]]] = {}
    for match in pattern.finditer(out):
        sha1 = match.group(1).upper()
        if sha1 not in identity_sha1s:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".pem", encoding="utf-8") as certificate:
            certificate.write(match.group(2) + "\n")
            certificate.flush()
            cert_code, subject, _ = _run(
                ["openssl", "x509", "-in", certificate.name, "-noout", "-subject", "-nameopt", "RFC2253"],
                timeout=10,
            )
        if cert_code:
            continue
        teams = set(re.findall(r"(?:^|,)OU=([A-Z0-9]{10})(?=,|$)", subject.removeprefix("subject=").strip()))
        for team in teams:
            result.setdefault(sha1, {}).setdefault(team, []).append("certificate_subject")
    return result


def _provisioning_identity_teams(identity_sha1s: set[str]) -> dict[str, dict[str, list[str]]]:
    """Return exact identity/team links from valid CMS-decoded provisioning profiles."""
    if not identity_sha1s:
        return {}
    roots = (
        Path.home() / "Library" / "Developer" / "Xcode" / "UserData" / "Provisioning Profiles",
        Path.home() / "Library" / "MobileDevice" / "Provisioning Profiles",
    )
    links: dict[str, dict[str, list[str]]] = {}
    profiles: list[Path] = []
    for root in roots:
        if root.is_dir() and not root.is_symlink():
            profiles.extend(path for path in root.glob("*.mobileprovision") if path.is_file() and not path.is_symlink())
    for path in sorted(set(profiles))[:256]:
        code, out, _ = _run(["security", "cms", "-D", "-i", str(path)], timeout=10)
        if code or not out:
            continue
        try:
            profile = plistlib.loads(out.encode())
        except plistlib.InvalidFileException:
            continue
        if not isinstance(profile, dict):
            continue
        expiration = profile.get("ExpirationDate")
        if not isinstance(expiration, datetime):
            continue
        expires = expiration.replace(tzinfo=expiration.tzinfo or timezone.utc)
        if expires <= datetime.now(timezone.utc):
            continue
        certificates = profile.get("DeveloperCertificates", [])
        hashes = {
            hashlib.sha1(bytes(value)).hexdigest().upper()
            for value in certificates
            if isinstance(value, (bytes, bytearray))
        }
        matched = hashes.intersection(identity_sha1s)
        values = profile.get("TeamIdentifier", [])
        teams = {
            team for team in values if isinstance(team, str) and re.fullmatch(r"[A-Z0-9]{10}", team)
        } if isinstance(values, list) else set()
        for sha1 in matched:
            for team in teams:
                links.setdefault(sha1, {}).setdefault(team, []).append("verified_provisioning_profile")
    return links


def _verified_provisioning_teams(identity_sha1s: set[str]) -> dict[str, list[str]]:
    """Compatibility projection of cryptographically linked provisioning teams."""
    teams: dict[str, list[str]] = {}
    for linked in _provisioning_identity_teams(identity_sha1s).values():
        for team, sources in linked.items():
            teams.setdefault(team, []).extend(sources)
    return {team: sorted(set(sources)) for team, sources in sorted(teams.items())}


def _version(value: str) -> tuple[int, int, int]:
    return version_tuple(value)


def _node_supported(version: tuple[int, int, int]) -> bool:
    from ipad_agent.maintenance.versions import node_supported
    return node_supported(version)


def _reachable_private_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    networks = tuple(ipaddress.ip_network(item) for item in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    return address.version == 4 and any(address in network for network in networks)


def _command_check(identifier: str, command: list[str], remediation: str | None = None) -> Check:
    code, out, err = _run(command)
    return Check(identifier, "pass" if code == 0 else "fail", (out or err or "command unavailable").splitlines()[0], remediation=remediation if code else None)


def _run(command: list[str], *, env: dict[str, str] | None = None, timeout: int = 20) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", str(error)


def _devicectl_payload(arguments: list[str]) -> tuple[int, dict[str, Any], str]:
    with tempfile.NamedTemporaryFile(suffix=".json") as output:
        code, out, err = _run(["xcrun", "devicectl", *arguments, "--json-output", output.name, "--quiet", "--timeout", "10"], timeout=20)
        if code:
            return code, {}, err or out
        try:
            payload = json.loads(Path(output.name).read_text())
        except (OSError, json.JSONDecodeError) as error:
            return 65, {}, str(error)
    return 0, payload if isinstance(payload, dict) else {}, ""


def _devices_probe() -> tuple[int, list[dict[str, Any]], str]:
    code, payload, error = _devicectl_payload(["list", "devices"])
    result = payload.get("result") if isinstance(payload, dict) else None
    devices = result.get("devices") if isinstance(result, dict) else None
    if code == 0 and not isinstance(devices, list):
        return 65, [], "CoreDevice JSON omitted result.devices"
    return code, [item for item in devices if isinstance(item, dict)] if isinstance(devices, list) else [], error


def _devices() -> list[dict[str, Any]]:
    return _devices_probe()[1]


def _apps_probe(device: str) -> tuple[int, list[dict[str, Any]], str]:
    code, payload, error = _devicectl_payload(
        ["device", "info", "apps", "--device", device, "--include-all-apps"]
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    apps = result.get("apps") if isinstance(result, dict) else None
    if code == 0 and not isinstance(apps, list):
        return 65, [], "CoreDevice JSON omitted result.apps"
    return code, [item for item in apps if isinstance(item, dict)] if isinstance(apps, list) else [], error


def _exact_bundle_installed(apps: list[dict[str, Any]], bundle_id: str) -> bool:
    return any(item.get("bundleIdentifier") == bundle_id for item in apps)


def _device_ids(item: dict[str, Any]) -> set[Any]:
    hardware = item.get("hardwareProperties", {})
    return {item.get("identifier"), hardware.get("udid") if isinstance(hardware, dict) else None}


def _is_paired_ipad(item: dict[str, Any]) -> bool:
    hardware = item.get("hardwareProperties", {}); connection = item.get("connectionProperties", {})
    return isinstance(hardware, dict) and isinstance(connection, dict) and hardware.get("deviceType") == "iPad" and hardware.get("reality") == "physical" and connection.get("pairingState") == "paired"


def _lock_state(device: str) -> bool | None:
    code, payload, _ = _devicectl_payload(["device", "info", "lockState", "--device", device])
    if code:
        return None
    result = payload.get("result") if isinstance(payload, dict) else None
    state = result.get("passcodeRequired") if isinstance(result, dict) else None
    return state if isinstance(state, bool) else None


__all__ = ["Check", "internal_report", "public_report", "public_text", "run_doctor"]
