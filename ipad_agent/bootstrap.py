"""Repository-local bootstrap for redistributable automation dependencies.

This module never changes global npm state.  Callers must explicitly pass
``apply=True``; otherwise it only returns the planned command.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping

from .paths import RUNTIME_ROOT, private_mkdir
from .versions import APPIUM_VERSION, XCUITEST_VERSION, node_supported, version_tuple

NODE_PREFIX = RUNTIME_ROOT / "node"
APPIUM = NODE_PREFIX / "node_modules" / ".bin" / "appium"
APPIUM_HOME = RUNTIME_ROOT / "appium-home"


def resolve_node_toolchain(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return a compatible Node/npm pair, preferring a repository-local pair."""
    env = os.environ if environ is None else environ
    candidates: list[tuple[str, str]] = []
    local_bin = RUNTIME_ROOT / "node-runtime" / "bin"
    candidates.append((str(local_bin / "node"), str(local_bin / "npm")))
    configured = env.get("IPAD_AGENT_NODE")
    if configured:
        node = Path(configured).expanduser()
        candidates.append((str(node), str(node.with_name("npm"))))
    path_node = shutil.which("node", path=env.get("PATH"))
    path_npm = shutil.which("npm", path=env.get("PATH"))
    if path_node:
        candidates.append((path_node, path_npm or str(Path(path_node).with_name("npm"))))

    seen: set[tuple[str, str]] = set()
    observations: list[dict[str, Any]] = []
    for node, npm in candidates:
        if (node, npm) in seen:
            continue
        seen.add((node, npm))
        node_probe = _run([node, "--version"], env=dict(env))
        npm_probe = _run([npm, "--version"], env=dict(env))
        node_version = version_tuple(node_probe[1])
        npm_version = version_tuple(npm_probe[1])
        compatible = node_probe[0] == 0 and npm_probe[0] == 0 and node_supported(node_version) and npm_version >= (10, 0, 0)
        observation = {
            "node": node, "node_version": node_probe[1] or None,
            "npm": npm, "npm_version": npm_probe[1] or None,
            "compatible": compatible,
        }
        observations.append(observation)
        if compatible:
            return {**observation, "observations": [dict(item) for item in observations]}
    return {
        "node": None, "node_version": None, "npm": None, "npm_version": None,
        "compatible": False, "observations": observations,
    }


def remediation_command() -> str:
    return f"{sys.executable} -m ipad_agent setup --phase host --apply --json"


def node_remediation() -> str:
    return (
        "Make Node.js 20.19.0+, 22.12.0+, or 24.0.0+ with npm 10+ available "
        "on PATH (or set IPAD_AGENT_NODE to its node executable), then run: "
        + remediation_command()
    )


def bootstrap_automation(*, apply: bool, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Install pinned Appium and its XCUITest driver below ``.runtime``."""
    toolchain = resolve_node_toolchain(environ)
    install_command = [
        str(toolchain.get("npm") or "npm"), "install", "--prefix", str(NODE_PREFIX),
        "--no-audit", "--no-fund", "--save=false", f"appium@{APPIUM_VERSION}",
    ]
    if not toolchain["compatible"]:
        return {
            "ok": False, "changed": [], "planned": [install_command],
            "error": "compatible_node_unavailable", "remediation": node_remediation(),
            "toolchain": toolchain,
        }
    if not apply:
        return {"ok": True, "changed": [], "planned": [install_command], "toolchain": toolchain}

    private_mkdir(NODE_PREFIX)
    private_mkdir(APPIUM_HOME)
    env = dict(os.environ if environ is None else environ)
    node_bin = str(Path(str(toolchain["node"])).parent)
    env["PATH"] = node_bin + os.pathsep + env.get("PATH", "")
    env["APPIUM_HOME"] = str(APPIUM_HOME)
    changed: list[str] = []

    current = _run([str(APPIUM), "--version"], env=env)
    if current[0] or current[1].splitlines()[:1] != [APPIUM_VERSION]:
        _checked(install_command, env=env, timeout=300)
        changed.append(f"Appium {APPIUM_VERSION}")

    driver = _driver_version(env)
    if driver != XCUITEST_VERSION:
        if driver:
            _checked([str(APPIUM), "driver", "uninstall", "xcuitest"], env=env, timeout=180)
        _checked([str(APPIUM), "driver", "install", f"xcuitest@{XCUITEST_VERSION}"], env=env, timeout=600)
        changed.append(f"XCUITest driver {XCUITEST_VERSION}")
    return {"ok": True, "changed": changed, "planned": [], "toolchain": toolchain}


def _driver_version(env: dict[str, str]) -> str | None:
    probe = _run([str(APPIUM), "driver", "list", "--installed", "--json"], env=env, timeout=60)
    if probe[0]:
        return None
    try:
        item = json.loads(probe[1]).get("xcuitest", {})
    except (json.JSONDecodeError, AttributeError):
        return None
    return item.get("version") if isinstance(item, dict) else None


def _run(command: list[str], *, env: dict[str, str] | None = None, timeout: int = 20) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, "", str(error)


def _checked(command: list[str], *, env: dict[str, str], timeout: int) -> None:
    code, out, err = _run(command, env=env, timeout=timeout)
    if code:
        detail = " ".join((err or out or "command unavailable").split())[:1500]
        raise RuntimeError(f"setup command failed ({command[0]}): {detail}")


__all__ = ["APPIUM", "APPIUM_HOME", "NODE_PREFIX", "bootstrap_automation", "node_remediation", "resolve_node_toolchain"]
