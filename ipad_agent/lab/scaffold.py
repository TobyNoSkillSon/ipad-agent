"""Deterministic integration scaffolding; preview unless apply=True."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .validation import validate_manifest

_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_BUNDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9][A-Za-z0-9-]*)+$")


def scaffold_integration(
    integration_id: str,
    *,
    name: str,
    bundle_ids: Iterable[str],
    kind: str = "addon",
    repository_root: str | Path | None = None,
    output: str | Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Build a minimal valid manifest and optionally write exactly one new file."""
    if not isinstance(integration_id, str) or not _ID.fullmatch(integration_id):
        raise ValueError("integration_id must be a canonical kebab-case ID")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be non-empty")
    if kind not in {"core", "addon"}:
        raise ValueError("kind must be core or addon")
    bundles = list(bundle_ids)
    if not bundles or any(not isinstance(item, str) or not _BUNDLE.fullmatch(item) for item in bundles):
        raise ValueError("bundle_ids must contain valid reverse-DNS bundle IDs")
    if len({item.casefold() for item in bundles}) != len(bundles):
        raise ValueError("bundle_ids must be unique")

    manifest = {
        "$schema": "../../schemas/integration-v1.json",
        "schema": "ipad-agent.integration/v1",
        "version": 1,
        "id": integration_id,
        "name": name.strip(),
        "kind": kind,
        "bundle_ids": bundles,
        "aliases": [integration_id],
        "capabilities": ["unverified-launch-draft"],
        "selectors": {},
        "actions": {
            "unverified-activate-draft": {
                "description": "UNVERIFIED authoring placeholder; activation support has not been claimed.",
                "capability": "unverified-launch-draft",
                "steps": [{"operation": "activate"}],
                "safety": "navigate",
                "retry": "safe_repeat",
            }
        },
        "scenarios": {
            "unverified-launch-draft": {
                "description": "UNVERIFIED authoring placeholder; replace it with evidenced behavior.",
                "capabilities": ["unverified-launch-draft"],
                "actions": ["unverified-activate-draft"],
                "safety": "navigate",
                "retry": "safe_repeat",
            }
        },
        "safety": {
            "classification": "bounded-ui-navigation",
            "mutates_user_data": False,
            "requires_confirmation": [],
            "prohibited": ["payments", "account or security changes", "destructive operations", "protected confirmations"],
            "uncertain_outcome": "Inspect visible state before any retry after a lost response.",
        },
        "retry": {"default": "inspect_then_decide", "max_attempts": 1, "idempotent_actions": ["unverified-activate-draft"]},
        "requirements": {
            "host": ["UNVERIFIED: declare integration-specific host requirements"],
            "device": ["UNVERIFIED: declare integration-specific device requirements"],
            "permissions": ["UNVERIFIED: declare integration-specific permission requirements"],
        },
        "compatibility": {
            "verification": "unverified", "platform": "iPadOS",
            "minimum_os": "UNVERIFIED", "maximum_os": None,
            "locales": ["UNVERIFIED"], "app_versions": [],
        },
        "privacy": {
            "data_access": ["UNVERIFIED: determine from bounded inspection"],
            "data_sent": ["UNVERIFIED: determine from product behavior and documentation"],
            "retention": "UNVERIFIED: do not claim retention behavior before evidence exists.",
            "notes": "UNVERIFIED: replace every marker with integration-specific evidence before completion.",
        },
    }
    validate_manifest(manifest)
    root = Path(repository_root).resolve() if repository_root is not None else Path(__file__).resolve().parents[2]
    target = Path(output).expanduser() if output is not None else root / ("integrations" if kind == "core" else "addons") / integration_id / "integration.json"
    target = target if target.is_absolute() else root / target
    payload = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    changed = False
    if apply:
        if target.exists():
            raise FileExistsError(f"refusing to overwrite {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
        changed = True
    return {
        "ok": True,
        "applied": apply,
        "changed": changed,
        "target": str(target),
        "manifest": manifest,
        "index_entry": {
            "id": integration_id,
            "kind": kind,
            "manifest": f"{integration_id}/integration.json" if kind == "core" else f"../addons/{integration_id}/integration.json",
            "category": "application",
            "aliases": [integration_id],
            "bundle_ids": bundles,
        },
        "claims": "none verified; every UNVERIFIED marker is an authoring placeholder",
        "next": "Replace every UNVERIFIED draft marker with reviewed facts, validate, then add the index entry deliberately; scaffold never edits integrations/index.json.",
    }


__all__ = ["scaffold_integration"]
