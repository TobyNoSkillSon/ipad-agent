"""Private raw evidence and strictly allow-listed committed compatibility summaries."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from ipad_agent.core.paths import descriptor_has_extended_acl, has_extended_acl

from .model import PhysicalAuthorization, ScenarioPlan, canonical_digest
from .planning import verify_plan_safety
from .validation import read_json_strict, validate_compatibility, validate_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PRIVATE_PARTS = (
    "device identifiers", "hostnames", "user or team values", "tokens", "paths",
    "URLs", "UI source", "raw responses", "authorization actors and requests",
)
_COMPATIBILITY_METRICS = frozenset({
    "warmups", "runs", "minimum_seconds", "median_seconds", "p95_seconds",
    "maximum_seconds", "successful_runs", "uncertain_runs", "elapsed_seconds",
    "candidate_count", "repeatable_candidate_count",
})
_OS_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?$")
_LOCALE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")


def utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def private_evidence_root(repository_root: str | Path = REPOSITORY_ROOT) -> Path:
    return Path(repository_root).resolve() / ".runtime" / "lab"


def _secure_private_directories(private_root: Path, parent: Path) -> None:
    private_root = Path(os.path.abspath(private_root))
    parent = Path(os.path.abspath(parent))
    if private_root.name != "lab" or private_root.parent.name != ".runtime":
        raise ValueError("private evidence root must be repository .runtime/lab")
    repository_root = private_root.parent.parent
    try:
        relative = parent.relative_to(repository_root)
        parent.relative_to(private_root)
    except ValueError as error:
        raise ValueError("evidence path escaped .runtime/lab") from error
    current = repository_root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise ValueError("evidence path contains an unsafe component")
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            os.mkdir(current, 0o700)
            info = current.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & ~0o700
            or has_extended_acl(current)
        ):
            raise PermissionError("private evidence directory is not owner-only")


def _private_write(path: Path, payload: Mapping[str, Any], *, private_root: Path) -> None:
    private_root = Path(os.path.abspath(private_root))
    path = Path(os.path.abspath(path))
    try:
        path.relative_to(private_root)
    except ValueError as error:
        raise ValueError("evidence path escaped .runtime/lab") from error
    _secure_private_directories(private_root, path.parent)
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        stat.S_ISLNK(existing.st_mode)
        or not stat.S_ISREG(existing.st_mode)
        or existing.st_uid != os.getuid()
        or stat.S_IMODE(existing.st_mode) & ~0o600
        or has_extended_acl(path)
    ):
        raise PermissionError("private evidence file is not owner-only")

    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        if descriptor_has_extended_acl(descriptor):
            raise PermissionError("private evidence temporary file inherited an ACL")
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def evidence_document(
    *, mode: str, plan: ScenarioPlan, outcomes: list[dict[str, Any]], started_at: str,
    finished_at: str, metrics: Mapping[str, Any], host: Mapping[str, Any] | None = None,
    device: Mapping[str, Any] | None = None, complete: bool = True,
    authorization: PhysicalAuthorization | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    host_value = dict(host or {
        "system": platform.system(), "release": platform.release(),
        "machine": platform.machine(), "hostname": platform.node(),
    })
    device_value = dict(device or {})
    safety_gate = verify_plan_safety(plan)
    authorization_value = (
        authorization.to_dict() if isinstance(authorization, PhysicalAuthorization)
        else None if authorization is None else dict(authorization)
    )
    environment = {"host": host_value, "device": device_value}
    outcomes_ok = bool(outcomes) and all(
        outcome.get("ok") is True and outcome.get("uncertain") is not True
        for outcome in outcomes
    )
    wda = device_value.get("wda")
    teardown_ok = not isinstance(wda, Mapping) or wda.get("teardown_complete") is True
    return {
        "$schema": "schemas/evidence-v1.json",
        "schema": "ipad-agent.lab-evidence/v1",
        "version": 1,
        "evidence_id": uuid4().hex,
        "integration_id": plan.integration_id,
        "scenario_id": plan.scenario_id,
        "mode": mode,
        "started_at": started_at,
        "finished_at": finished_at,
        "host": host_value,
        "device": device_value,
        "plan": plan.to_dict(),
        "binding": {
            "integration_id": plan.integration_id,
            "scenario_id": plan.scenario_id,
            "manifest_digest": plan.manifest_digest,
            "plan_digest": plan.plan_digest,
            "parameters": dict(plan.parameters),
            "parameters_digest": canonical_digest(plan.parameters),
            "environment_digest": canonical_digest(environment),
        },
        "authorization": authorization_value,
        "safety_gate": safety_gate,
        "outcomes": outcomes,
        "metrics": dict(metrics),
        "redaction": {"state": "raw-private", "commit": False},
        "complete": bool(complete and outcomes_ok and teardown_ok and safety_gate["passed"]),
    }


def record_evidence(document: Mapping[str, Any], *, repository_root: str | Path = REPOSITORY_ROOT) -> Path:
    value = validate_evidence(document)
    root = private_evidence_root(repository_root)
    stamp = re.sub(r"[^0-9]", "", value["started_at"])[:14] or "undated"
    target = root / value["integration_id"] / f"{stamp}-{value['evidence_id'][:12]}" / "evidence.json"
    resolved = target.resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError("evidence path escaped .runtime/lab")
    _private_write(target, value, private_root=root)
    return target


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compatibility_metrics(metrics: Mapping[str, Any]) -> dict[str, int | float]:
    """Project numeric metrics by field name; never copy arbitrary keys or values."""
    result: dict[str, int | float] = {}
    for key in sorted(_COMPATIBILITY_METRICS):
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value < 0 or value != value or value in {float("inf"), float("-inf")}:
            continue
        result[key] = value
    return result


def _safe_os(value: Any) -> str | None:
    return value if isinstance(value, str) and _OS_VERSION.fullmatch(value) else None


def _safe_locale(value: Any) -> str | None:
    return value.replace("_", "-") if isinstance(value, str) and _LOCALE.fullmatch(value) else None


def compatibility_summary(
    evidence: Iterable[str | Path | Mapping[str, Any]], *, generated_at: str | None = None,
) -> dict[str, Any]:
    """Aggregate only enumerated compatibility fields; no recursive raw copying."""
    integrations: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, str]] = []
    seen_digests: set[str] = set()
    for item in evidence:
        if isinstance(item, Mapping):
            value = validate_evidence(item)
            digest = canonical_digest(value)
        else:
            path = Path(item).expanduser().resolve()
            value = validate_evidence(read_json_strict(path))
            digest = _digest(path)
        if digest in seen_digests:
            continue
        seen_digests.add(digest)
        physical_execution = value["mode"] == "physical"
        physical_benchmark = (
            value["mode"] == "benchmark"
            and value["metrics"].get("physical") is True
        )
        physically_sourced = (
            (physical_execution or physical_benchmark)
            and value["scenario_id"] != "selector-discovery"
            and value["device"].get("source") == "CoreDevice"
            and value["device"].get("capture") == "device info details"
        )
        if not (
            physically_sourced and value["complete"] is True
            and isinstance(value.get("authorization"), Mapping)
        ):
            # Simulation, selector discovery, failed/uncertain execution, and
            # unevidenced environment records are private diagnostics, never
            # publishable compatibility.
            continue
        sources.append({"sha256": digest})
        integration = integrations.setdefault(value["integration_id"], {
            "id": value["integration_id"], "physical_tested": True,
            "platform": "iPadOS", "os_versions": [], "locales": [],
            "scenarios": [], "limitations": [],
        })
        if physically_sourced:
            os_version = _safe_os(value["device"].get("os_version"))
            locale = _safe_locale(value["device"].get("locale"))
            if os_version and os_version not in integration["os_versions"]:
                integration["os_versions"].append(os_version)
            if locale and locale not in integration["locales"]:
                integration["locales"].append(locale)
        outcomes = value["outcomes"]
        status = "pass" if (
            value["complete"] and outcomes
            and all(outcome.get("ok") is True and outcome.get("uncertain") is not True for outcome in outcomes)
        ) else "fail"
        integration["scenarios"].append({
            "id": value["scenario_id"], "mode": value["mode"], "status": status,
            "evidence_sha256": digest,
            "metrics": _compatibility_metrics(value["metrics"]),
        })
    for integration in integrations.values():
        integration["os_versions"].sort()
        integration["locales"].sort()
        integration["scenarios"].sort(
            key=lambda item: (item["id"], item["mode"], item["evidence_sha256"])
        )
    summary = {
        "$schema": "schemas/compatibility-v1.json",
        "schema": "ipad-agent.compatibility/v1",
        "version": 1,
        "generated_at": generated_at or utc_now(),
        "source_evidence": sorted(sources, key=lambda item: item["sha256"]),
        "integrations": sorted(integrations.values(), key=lambda item: item["id"]),
        "redaction": {
            "raw_evidence_committed": False,
            "excluded": list(_PRIVATE_PARTS),
            "policy": "strict field allow-list plus SHA-256 evidence references only",
        },
    }
    return validate_compatibility(summary)


def write_compatibility_summary(
    evidence: Iterable[str | Path | Mapping[str, Any]], *,
    output: str | Path = REPOSITORY_ROOT / "compatibility-v1.json",
    generated_at: str | None = None,
) -> Path:
    target = Path(output)
    payload = compatibility_summary(evidence, generated_at=generated_at)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


__all__ = [
    "compatibility_summary", "evidence_document", "private_evidence_root",
    "record_evidence", "utc_now", "write_compatibility_summary",
]
