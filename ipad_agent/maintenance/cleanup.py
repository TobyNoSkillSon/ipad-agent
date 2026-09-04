"""Owned-only cleanup for project WDA artifacts and in-process servers."""
from __future__ import annotations

import json
import shutil
from typing import Any

from ipad_agent.core.config import load_config
from ipad_agent.core.paths import require_runtime_path
from ipad_agent.maintenance.versions import WDA_ARTIFACT_SCHEMA, WDA_VERIFICATION_SCHEMA
from ipad_agent.transports import wda


def run_cleanup(*, apply: bool = False, keep_fingerprint: str | None = None) -> dict[str, Any]:
    """Stop owned Appium first, then remove ownership-metadata-matching WDA state."""
    removed: list[str] = []
    candidates: list[str] = []
    rejected: list[dict[str, str]] = []
    server: dict[str, Any] = {"stopped": False, "reason": "dry_run"}
    try:
        if apply:
            server = wda.stop_owned_appium_server()
            no_server = server.get("reason") == "no_owned_server_receipt"
            if no_server:
                no_server = (
                    not wda.appium_start_marker_present()
                    and not wda.appium_endpoint_or_project_process_present(
                        load_config().appium_url
                    )
                )
                if not no_server:
                    server = {"stopped": False, "reason": "unreceipted_appium_may_be_running"}
            if server.get("stopped") is not True and not no_server:
                return {
                    "schema": "ipad-agent.cleanup/v1",
                    "state": "failed",
                    "applied": True,
                    "exit_code": 20,
                    "candidates": candidates,
                    "removed": removed,
                    "rejected": rejected,
                    "appium_server": server,
                    "error": "Owned Appium shutdown could not be proven; WDA artifacts were left in place.",
                }
            if server.get("stopped"):
                removed.append(str(wda.APPIUM_OWNER_RECEIPT))

        root = wda.DERIVED_DATA_ROOT
        if root.exists() and not root.is_symlink():
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.is_symlink() or child.name == keep_fingerprint:
                    continue
                try:
                    require_runtime_path(child)
                    payload = json.loads(wda.private_read_text(child / wda.ARTIFACT_FILE))
                    owned = (
                        payload.get("schema") == WDA_ARTIFACT_SCHEMA
                        and payload.get("owner") == wda.OWNER
                        and payload.get("fingerprint") == child.name
                    )
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    rejected.append({"path": str(child), "reason": str(error)})
                    continue
                if not owned:
                    rejected.append({"path": str(child), "reason": "ownership metadata did not match"})
                    continue
                candidates.append(str(child))
                if apply:
                    shutil.rmtree(child)
                    removed.append(str(child))
                    receipt = wda.verification_path(child.name)
                    try:
                        value = json.loads(wda.private_read_text(receipt))
                    except (OSError, json.JSONDecodeError):
                        value = None
                    if (
                        isinstance(value, dict)
                        and value.get("schema") == WDA_VERIFICATION_SCHEMA
                        and value.get("owner") == wda.OWNER
                        and value.get("fingerprint") == child.name
                    ):
                        receipt.unlink()
                        removed.append(str(receipt))
        return {
            "schema": "ipad-agent.cleanup/v1",
            "state": "complete",
            "applied": apply,
            "exit_code": 0,
            "candidates": candidates,
            "removed": removed,
            "rejected": rejected,
            "appium_server": server,
        }
    except Exception as error:
        return {
            "schema": "ipad-agent.cleanup/v1",
            "state": "failed",
            "applied": apply,
            "exit_code": 20,
            "candidates": candidates,
            "removed": removed,
            "rejected": rejected,
            "appium_server": server,
            "error": " ".join(str(error).split())[:2000],
        }


__all__ = ["run_cleanup"]
