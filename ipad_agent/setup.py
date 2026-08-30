"""Explicit-apply state transitions for host dependencies and signed WDA."""
from __future__ import annotations

import os
from pathlib import Path
import json
import re
from typing import Any

from .bootstrap import APPIUM, bootstrap_automation
from .config import DEFAULT_CONFIG_PATH, load_config
from .doctor import internal_report, public_report, public_text, run_doctor
from .paths import private_write_text
from .versions import APPIUM_VERSION, SETUP_SCHEMA, XCUITEST_VERSION
from . import airdrop, wda

PHASES = ("all", "host", "wda", "verify")


def run_setup(*, apply: bool = False, phase: str = "all") -> dict[str, Any]:
    """Plan or apply one rerunnable transition; return JSON state on failure."""
    changed: list[str] = []
    operations: list[dict[str, Any]] = []
    error: dict[str, str] | None = None
    if phase not in PHASES:
        return _setup_report(apply, phase, changed, operations, internal_report(run_doctor()), {"code": "invalid_phase", "message": f"phase must be one of: {', '.join(PHASES)}"})
    try:
        if apply and phase in {"all", "host"} and not DEFAULT_CONFIG_PATH.exists():
            private_write_text(DEFAULT_CONFIG_PATH, _default_config())
            changed.append(str(DEFAULT_CONFIG_PATH))

        doctor = internal_report(run_doctor())
        if phase in {"all", "host"}:
            bootstrap = bootstrap_automation(apply=apply)
            operations.append({"phase": "host", **bootstrap})
            changed.extend(bootstrap.get("changed", []))
            if not bootstrap.get("ok"):
                error = {"code": str(bootstrap.get("error") or "host_bootstrap_failed"), "message": str(bootstrap.get("remediation") or "Host bootstrap failed")}
            doctor = internal_report(run_doctor())
            if error is None:
                helper = _maintain_airdrop_helper(doctor, apply=apply)
                operations.append(helper)
                if helper.get("changed"):
                    changed.append(str(airdrop.HELPER_BINARY))
                if apply and helper.get("changed"):
                    doctor = internal_report(run_doctor())

        if error is None and phase in {"all", "wda"}:
            blockers = _blocking(doctor, _WDA_PREREQUISITES)
            if blockers:
                operations.append({"phase": "wda", "ok": False, "changed": False, "blocked_by": blockers})
            else:
                selection = _selection_from_report(doctor)
                build = wda.build_for_testing(selection, apply=apply)
                operation = {"phase": "wda", **build}
                operations.append(operation)
                if build.get("changed"):
                    changed.append(str(wda.artifact_directory(selection)))
                if apply and build.get("ok") and isinstance(build.get("artifact"), dict):
                    runtime_fields = _persist_runtime_wda_config(selection, build["artifact"])
                    operation["runtime_config"] = runtime_fields
                    if runtime_fields.get("changed"):
                        changed.append(str(DEFAULT_CONFIG_PATH))
                doctor = internal_report(run_doctor())

        if error is None and phase == "verify":
            blockers = _blocking(doctor, _VERIFY_PREREQUISITES)
            if blockers:
                operations.append({"phase": "verify", "ok": False, "changed": False, "blocked_by": blockers})
            else:
                selection = _selection_from_report(doctor)
                result = wda.verify_bounded_session(selection, apply=apply, timeout=180.0, appium_url=load_config().appium_url)
                operations.append({"phase": "verify", **result})
                if result.get("changed"):
                    changed.append(str(wda.verification_path(selection.fingerprint)))
                doctor = internal_report(run_doctor())
    except Exception as caught:
        message = " ".join(str(caught).split())[:2000] or type(caught).__name__
        error = _classify_transition_error(caught, message)
        doctor = internal_report(run_doctor())
    return _setup_report(apply, phase, changed, operations, doctor, error)


_WDA_PREREQUISITES = {
    "host.macos", "host.python", "host.xcode", "host.xcode_license",
    "host.xcode_first_launch", "host.devicectl", "automation.appium",
    "automation.xcuitest_driver", "device.paired", "device.developer_mode",
    "device.unlocked", "signing.identity", "signing.selection", "automation.wda_source",
}
def _maintain_airdrop_helper(report: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    """Plan or build only the fixed project-owned helper; never invent policy."""
    helper_status = _check_status(report, "airdrop.helper")
    if helper_status == "pass":
        return {
            "phase": "host", "component": "airdrop_helper",
            "ok": True, "changed": False, "ready": True,
        }
    if _check_status(report, "host.swift") != "pass":
        return {
            "phase": "host", "component": "airdrop_helper",
            "ok": False, "changed": False, "blocked_by": ["host.swift"],
        }
    if not apply:
        return {
            "phase": "host", "component": "airdrop_helper",
            "ok": True, "changed": False,
            "planned": "build_project_owned_airdrop_helper",
        }
    airdrop.build_helper()
    return {
        "phase": "host", "component": "airdrop_helper",
        "ok": True, "changed": True, "ready": True,
    }


_VERIFY_PREREQUISITES = {
    "host.macos", "host.xcode", "host.xcode_license", "host.xcode_first_launch",
    "host.devicectl", "automation.appium", "automation.xcuitest_driver",
    "device.paired", "device.developer_mode", "device.unlocked", "signing.identity",
    "signing.selection", "automation.wda_build", "automation.wda_provenance",
    "automation.runtime_config",
}


def _blocking(report: dict[str, Any], required: set[str]) -> list[str]:
    values = {item.get("id"): item.get("status") for item in report.get("checks", [])}
    return sorted(identifier for identifier in required if values.get(identifier) != "pass")


def _selection_from_report(report: dict[str, Any]) -> wda.WDASelection:
    selected = report.get("selected", {})
    required = ("device_identifier", "device_udid", "team_id", "wda_bundle_id")
    if any(not selected.get(key) for key in required):
        raise wda.XCTestControlError("Doctor did not produce a complete device/team/bundle selection")
    device = {
        "identifier": selected["device_identifier"], "udid": selected["device_udid"],
        "version": _device_version(report),
    }
    xcode = next((item.get("evidence", {}).get("version") for item in report.get("checks", []) if item.get("id") == "host.xcode" and isinstance(item.get("evidence"), dict)), None)
    return wda.make_selection(device=device, team=selected["team_id"], bundle_id=selected["wda_bundle_id"], xcode=xcode)


def _device_version(report: dict[str, Any]) -> str:
    for item in report.get("checks", []):
        if item.get("id") == "device.paired" and isinstance(item.get("evidence"), dict):
            value = item["evidence"].get("os")
            if value:
                return str(value)
    raise wda.XCTestControlError("Selected iPad OS version is unavailable")


_HUMAN_GATE_ACTIONS: dict[str, tuple[str, str]] = {
    "device_unlock_required": ("device.unlocked", "Unlock the iPad yourself with Face ID, Touch ID, or its passcode, leave it awake, then rerun the same setup phase."),
    "apple_account_required": ("signing.identity", "In Xcode > Settings > Accounts, sign in to or refresh the intended Apple account and complete Apple ID and 2FA prompts yourself; then rerun the same setup phase."),
    "keychain_required": ("signing.identity", "Unlock the login keychain in Keychain Access and approve any signing/keychain prompt yourself; then rerun the same setup phase."),
    "signing_required": ("signing.identity", "In Xcode, select the intended development team and create or refresh its Apple Development signing certificate. Approve signing prompts yourself, then rerun the same setup phase."),
    "provisioning_required": ("signing.selection", "In Xcode, refresh automatic signing/provisioning for the intended team and connected iPad. Complete account or device-registration prompts yourself, then rerun the same setup phase."),
    "developer_trust_required": ("device.developer_trust", "On iPad, open Settings > General > VPN & Device Management, select the Developer App, tap Trust, confirm it yourself, keep the iPad unlocked, then rerun the verify phase."),
}


def _classify_transition_error(error: Exception, message: str) -> dict[str, str]:
    explicit = getattr(error, "code", None)
    if isinstance(explicit, str) and explicit in _HUMAN_GATE_ACTIONS:
        return {"code": explicit, "message": message}
    lower = message.casefold()
    patterns = (
        ("device_unlock_required", ("device is locked", "device locked", "unlock the device", "passcode")),
        ("keychain_required", ("keychain", "user interaction is not allowed", "errsecauthfailed", "errsecinternalcomponent", "private key")),
        ("apple_account_required", ("apple id", "developer account", "account authentication", "two-factor", "2fa", "not logged in", "no accounts", "add a new account")),
        ("provisioning_required", ("provisioning profile", "no profiles for", "register device", "device registration", "profile doesn't include", "failed to register bundle identifier", "communication with apple failed")),
        ("signing_required", ("code signing", "codesign", "signing certificate", "development team", "requires a development team", "no certificate for team")),
    )
    for code, tokens in patterns:
        if any(token in lower for token in tokens):
            return {"code": code, "message": message}
    return {"code": "setup_transition_failed", "message": message}


def _persist_runtime_wda_config(selection: wda.WDASelection, artifact: dict[str, Any]) -> dict[str, Any]:
    xctestrun = artifact.get("xctestrun")
    runtime = artifact.get("runtime")
    expected = {
        "team_id": selection.team_id, "wda_bundle_id": selection.bundle_id,
        "xctestrun": xctestrun, "wda_fingerprint": selection.fingerprint,
    }
    if runtime != expected or not isinstance(xctestrun, str):
        raise wda.XCTestControlError("Built WDA artifact omitted truthful runtime provenance")
    original = DEFAULT_CONFIG_PATH.read_text() if DEFAULT_CONFIG_PATH.exists() else _default_config()
    match = re.search(r"(?ms)^\[automation\]\s*\n(?P<body>.*?)(?=^\[|\Z)", original)
    if not match:
        raise wda.XCTestControlError("Local config has no [automation] section")
    body = match.group("body")
    values = {
        "team_id": selection.team_id,
        "wda_bundle_id": selection.bundle_id,
        "xctestrun": xctestrun,
    }
    for key, value in values.items():
        rendered = f"{key} = {json.dumps(value)}"
        pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
        if pattern.search(body):
            body = pattern.sub(rendered, body, count=1)
        else:
            body += rendered + "\n"
    updated = original[:match.start("body")] + body + original[match.end("body"):]
    changed = updated != original or not DEFAULT_CONFIG_PATH.exists()
    if changed:
        private_write_text(DEFAULT_CONFIG_PATH, updated)
    return {**expected, "changed": changed}


def _setup_report(apply: bool, phase: str, changed: list[str], operations: list[dict[str, Any]], doctor: dict[str, Any], error: dict[str, str] | None) -> dict[str, Any]:
    blocked_by = next((
        item.get("blocked_by") for item in reversed(operations)
        if item.get("component") != "airdrop_helper"
        and isinstance(item.get("blocked_by"), list)
    ), None)
    report_next = doctor.get("next")
    only = set(blocked_by) if blocked_by else (set(report_next) if isinstance(report_next, list) else None)
    human_precedence = (
        "host.xcode_license", "host.xcode_first_launch", "device.paired",
        "device.developer_mode", "device.unlocked", "signing.identity",
    )
    current_human_gate = next((identifier for identifier in human_precedence if only and identifier in only and _check_status(doctor, identifier) == "action_required"), None)
    actions = _actions(doctor, only={current_human_gate} if current_human_gate else only)
    if phase in {"all", "host"}:
        transfer_actions = _actions(
            doctor, only={"host.swift", "airdrop.policy", "airdrop.helper"},
        )
        known = {(item.get("kind"), item.get("check")) for item in actions}
        actions.extend(
            item for item in transfer_actions
            if (item.get("kind"), item.get("check")) not in known
        )
    human_error = error is not None and error.get("code") in _HUMAN_GATE_ACTIONS
    if human_error:
        check, instructions = _HUMAN_GATE_ACTIONS[error["code"]]
        actions = [{"kind": "human_security_action", "check": check, "instructions": instructions}]
    if not apply and phase in PHASES and not any(item.get("kind") == "human_security_action" for item in actions):
        actions.insert(0, {"kind": "agent_action", "command": f"python3 -m ipad_agent setup --phase {phase} --apply --json", "reason": "Apply the planned repository-local transition; dry-run never mutates state."})
    ready = bool(doctor.get("ready")) and error is None
    blocking_agent_action = any(
        item.get("kind") == "agent_action"
        and item.get("check")
        and item.get("check") not in {"host.swift", "airdrop.policy", "airdrop.helper"}
        for item in actions
    )
    if human_error:
        state, exit_code = "action_required", 10
    elif error:
        state, exit_code = "failed", 20
    elif ready:
        state, exit_code = "ready", 0
    elif any(item.get("kind") == "human_security_action" for item in actions) and not blocking_agent_action:
        state, exit_code = "action_required", 10
    else:
        state, exit_code = "needs_agent_action", int(doctor.get("exit_code", 20))
    result: dict[str, Any] = {
        "schema": SETUP_SCHEMA, "state": state, "applied": apply, "phase": phase,
        "changed": _public_changes(changed, operations), "ready": ready, "exit_code": exit_code,
        "actions": [_public_action(item) for item in actions],
        "operations": [_public_operation(item) for item in operations],
        "doctor": public_report(doctor),
    }
    if error is not None:
        result["error"] = _public_error(error)
    return result


def _public_changes(changed: list[str], operations: list[dict[str, Any]]) -> list[str]:
    """Describe mutations logically; never publish local artifact paths."""
    logical: list[str] = []
    if changed:
        for operation in operations:
            phase = operation.get("phase")
            component = operation.get("component")
            value = operation.get("changed")
            did_change = bool(value) if not isinstance(value, list) else bool(value)
            if did_change and component == "airdrop_helper":
                logical.append("airdrop_helper")
            elif did_change and phase in {"host", "wda", "verify"}:
                logical.append({"host": "host_automation", "wda": "wda_artifact", "verify": "verification_receipt"}[phase])
        if any(str(value) == str(DEFAULT_CONFIG_PATH) for value in changed):
            logical.append("local_config")
        if not logical:
            logical.append("repository_local_state")
    return list(dict.fromkeys(logical))


def _public_action(action: dict[str, Any]) -> dict[str, Any]:
    result = {key: action[key] for key in ("kind", "check", "reason") if key in action}
    if action.get("instructions"):
        result["instructions"] = public_text(action["instructions"])
    if action.get("command"):
        command = public_text(action["command"])
        if "-m ipad_agent" in command:
            command = "python3 " + command[command.index("-m ipad_agent"):]
        result["command"] = command
    return result


def _public_operation(operation: dict[str, Any]) -> dict[str, Any]:
    phase = str(operation.get("phase") or "unknown")
    result: dict[str, Any] = {"phase": phase}
    if operation.get("component") == "airdrop_helper":
        result["component"] = "airdrop_helper"
    if "ok" in operation:
        result["ok"] = bool(operation.get("ok"))
    if "changed" in operation:
        value = operation.get("changed")
        result["changed"] = bool(value) if not isinstance(value, list) else bool(value)
    if isinstance(operation.get("blocked_by"), list):
        result["blocked_by"] = [str(value) for value in operation["blocked_by"]]
    if phase == "host":
        toolchain = operation.get("toolchain")
        if isinstance(toolchain, dict):
            result["toolchain"] = {
                key: public_text(value)
                for key in ("node_version", "npm_version")
                if isinstance((value := toolchain.get(key)), str) and value
            }
        if operation.get("component") == "airdrop_helper":
            if operation.get("ready"):
                result["ready"] = True
            if operation.get("planned"):
                result["planned"] = "build_project_owned_airdrop_helper"
        elif operation.get("planned"):
            result["planned"] = "install_pinned_host_automation"
        if operation.get("error"):
            result["error"] = public_text(operation["error"])
    elif phase == "wda":
        if operation.get("ok") is True and operation.get("artifact") is not None:
            result["artifact"] = "validated"
        elif operation.get("ok") is True and not operation.get("changed"):
            result["planned"] = "build_for_testing"
        if operation.get("runtime_config") is not None:
            result["runtime_config"] = "updated" if operation.get("runtime_config", {}).get("changed") else "current"
    elif phase == "verify":
        if operation.get("receipt") is not None:
            result["verification"] = "recorded"
        elif operation.get("planned"):
            result["planned"] = "bounded_appium_wda_session"
        if isinstance(operation.get("timeout_seconds"), (int, float)):
            result["timeout_seconds"] = operation["timeout_seconds"]
    return result


def _public_error(error: dict[str, str]) -> dict[str, str]:
    code = str(error.get("code") or "setup_transition_failed")
    stable = {
        "invalid_phase": "The requested setup phase is unsupported.",
        "device_unlock_required": "The iPad must be unlocked by a person before setup can continue.",
        "apple_account_required": "Apple account authentication must be completed by a person in Xcode.",
        "keychain_required": "A person must unlock or approve the signing keychain in macOS.",
        "signing_required": "A person must complete Apple Development signing in Xcode.",
        "provisioning_required": "A person must create or refresh WDA provisioning in Xcode; ipad-agent will not update provisioning or register devices automatically.",
        "developer_trust_required": "A person must trust the WDA developer app on the iPad.",
    }
    if code == "setup_transition_failed":
        detail = public_text(error.get("message") or "The bounded setup transition failed")
        message = f"The setup transition failed: {detail}"
    else:
        message = stable.get(
            code,
            "The setup transition failed; follow the logical remediation and rerun the same phase.",
        )
    return {"code": code, "message": message}


def _check_status(report: dict[str, Any], identifier: str) -> str | None:
    return next((str(item.get("status")) for item in report.get("checks", []) if item.get("id") == identifier), None)


def _actions(report: dict[str, Any], *, only: set[str] | None = None) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for check in report.get("checks", []):
        identifier = str(check.get("id"))
        if only is not None and identifier not in only:
            continue
        human = check.get("human_action")
        remediation = check.get("remediation")
        if check.get("status") == "action_required" and human:
            key = ("human", identifier)
            if key not in seen:
                actions.append({"kind": "human_security_action", "check": identifier, "instructions": human}); seen.add(key)
        elif check.get("status") in {"fail", "unknown"} and remediation:
            key = ("agent", identifier)
            if key not in seen:
                action: dict[str, Any] = {"kind": "agent_action", "check": identifier, "instructions": remediation}
                if remediation.startswith("Run: "):
                    action["command"] = remediation.removeprefix("Run: ")
                actions.append(action); seen.add(key)
    return actions


def _default_config() -> str:
    return "\n".join([
        "# Local machine state. Never commit this file.",
        "[device]", 'id = ""', "",
        "[apps]", 'browser = "safari"', "",
        "[addons]", "enabled = []", "",
        "[display]", 'host = ""', "port = 8766", "",
        "[automation]", f'appium = "{APPIUM}"', 'appium_url = "http://127.0.0.1:4723"',
        'team_id = ""', 'wda_bundle_id = ""', 'xctestrun = ""', "",
    ])


__all__ = ["APPIUM_VERSION", "PHASES", "XCUITEST_VERSION", "run_setup"]
