"""Owned-only cleanup for project WDA artifacts and in-process servers."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from .paths import require_runtime_path
from .versions import WDA_ARTIFACT_SCHEMA, WDA_VERIFICATION_SCHEMA
from . import wda


def run_cleanup(*, apply: bool = False, keep_fingerprint: str | None = None) -> dict[str, Any]:
    removed: list[str] = []
    candidates: list[str] = []
    rejected: list[dict[str, str]] = []
    try:
        root = wda.DERIVED_DATA_ROOT
        if root.exists() and not root.is_symlink():
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.is_symlink() or child.name == keep_fingerprint:
                    continue
                try:
                    require_runtime_path(child)
                    payload = json.loads((child / wda.ARTIFACT_FILE).read_text())
                    owned = payload.get("schema") == WDA_ARTIFACT_SCHEMA and payload.get("owner") == wda.OWNER and payload.get("fingerprint") == child.name
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    rejected.append({"path": str(child), "reason": str(error)}); continue
                if not owned:
                    rejected.append({"path": str(child), "reason": "ownership metadata did not match"}); continue
                candidates.append(str(child))
                if apply:
                    shutil.rmtree(child)
                    removed.append(str(child))
                    receipt = wda.verification_path(child.name)
                    try:
                        value = json.loads(receipt.read_text())
                    except (OSError, json.JSONDecodeError):
                        value = None
                    if isinstance(value, dict) and value.get("schema") == WDA_VERIFICATION_SCHEMA and value.get("owner") == wda.OWNER and value.get("fingerprint") == child.name:
                        receipt.unlink()
                        removed.append(str(receipt))
        server = {"stopped": False, "reason": "dry_run"}
        if apply:
            server = wda.stop_owned_appium_server()
            if server.get("stopped"):
                removed.append(str(wda.APPIUM_OWNER_RECEIPT))
        return {"schema": "ipad-agent.cleanup/v1", "state": "complete", "applied": apply, "exit_code": 0, "candidates": candidates, "removed": removed, "rejected": rejected, "appium_server": server}
    except Exception as error:
        return {"schema": "ipad-agent.cleanup/v1", "state": "failed", "applied": apply, "exit_code": 20, "candidates": candidates, "removed": removed, "rejected": rejected, "error": " ".join(str(error).split())[:2000]}


__all__ = ["run_cleanup"]
