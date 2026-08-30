"""Typed plans, physical authorization records, and lab results."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from ipad_agent.operations import BatchResult, OperationSpec, SafetyClass


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_object(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    try:
        cloned = json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must contain only finite JSON values") from error
    if not isinstance(cloned, dict):
        raise ValueError(f"{name} must be an object")
    return cloned


@dataclass(frozen=True)
class PlannedStep:
    action_id: str
    index: int
    operation: OperationSpec
    instruction: Mapping[str, Any]
    selector: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("planned step action_id must be a non-empty string")
        object.__setattr__(self, "action_id", self.action_id.strip())
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError("planned step index must be a non-negative integer")
        if not isinstance(self.operation, OperationSpec):
            raise ValueError("planned step operation must be an OperationSpec")
        object.__setattr__(self, "instruction", _json_object(self.instruction, "planned step instruction"))
        if self.selector is not None:
            object.__setattr__(self, "selector", _json_object(self.selector, "planned step selector"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "index": self.index,
            "operation": self.operation.to_dict(),
            "instruction": dict(self.instruction),
            "selector": None if self.selector is None else dict(self.selector),
        }


@dataclass(frozen=True)
class ScenarioPlan:
    integration_id: str
    scenario_id: str
    bundle_id: str
    steps: tuple[PlannedStep, ...]
    max_attempts: int
    safety_ceiling: SafetyClass
    manifest_path: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)
    manifest_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        object.__setattr__(self, "parameters", _json_object(self.parameters, "parameters"))
        if not re.fullmatch(r"[a-f0-9]{64}", self.manifest_digest):
            raise ValueError("manifest_digest must be a SHA-256 digest")

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "integration_id": self.integration_id,
            "scenario_id": self.scenario_id,
            "bundle_id": self.bundle_id,
            "max_attempts": self.max_attempts,
            "safety_ceiling": self.safety_ceiling.value,
            "steps": [step.to_dict() for step in self.steps],
            "metadata": dict(self.metadata),
            "parameters": dict(self.parameters),
            "manifest_digest": self.manifest_digest,
        }

    @property
    def plan_digest(self) -> str:
        return canonical_digest(self._digest_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self._digest_payload()
        value["plan_digest"] = self.plan_digest
        return value


@dataclass(frozen=True)
class BenchmarkControlPlan:
    """Typed, bounded state-control steps for one benchmark."""

    baseline: tuple[PlannedStep, ...]
    reset: tuple[PlannedStep, ...]
    cleanup: tuple[PlannedStep, ...]

    def __post_init__(self) -> None:
        for name in ("baseline", "reset", "cleanup"):
            steps = tuple(getattr(self, name))
            if not steps or not all(isinstance(step, PlannedStep) for step in steps):
                raise ValueError(f"benchmark control {name} must contain PlannedStep values")
            object.__setattr__(self, name, steps)
        operation_ids = [
            step.operation.operation_id
            for phase in (self.baseline, self.reset, self.cleanup)
            for step in phase
        ]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("benchmark control operation IDs must be unique")

    def to_dict(self) -> dict[str, Any]:
        phases = {
            "baseline": [step.to_dict() for step in self.baseline],
            "reset": [step.to_dict() for step in self.reset],
            "cleanup": [step.to_dict() for step in self.cleanup],
        }
        return {**phases, "control_plan_digest": canonical_digest(phases)}


@dataclass(frozen=True)
class PhysicalAuthorization:
    """Exact authority for one already-planned physical scenario.

    The record deliberately carries the supplied parameter values. It is raw,
    private evidence and must never be projected into compatibility output.
    """

    actor: str
    request: str
    integration_id: str
    manifest_digest: str
    plan_digest: str
    scenario_id: str
    parameters: Mapping[str, Any]
    safety_ceiling: SafetyClass | str
    confirmations: tuple[str, ...]
    authorized_at: str
    expires_at: str | None = None
    run_count: int = 1
    benchmark_parameters: Mapping[str, Any] | None = None
    benchmark_control_plan: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("actor", "request", "integration_id", "scenario_id", "authorized_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"authorization.{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if not re.fullmatch(r"[a-f0-9]{64}", self.manifest_digest):
            raise ValueError("authorization.manifest_digest must be a SHA-256 digest")
        if not re.fullmatch(r"[a-f0-9]{64}", self.plan_digest):
            raise ValueError("authorization.plan_digest must be a SHA-256 digest")
        try:
            ceiling = SafetyClass(self.safety_ceiling)
        except (TypeError, ValueError) as error:
            raise ValueError("authorization.safety_ceiling is invalid") from error
        object.__setattr__(self, "safety_ceiling", ceiling)
        object.__setattr__(self, "parameters", _json_object(self.parameters, "authorization.parameters"))
        confirmations = tuple(self.confirmations)
        if (
            not all(isinstance(item, str) and item.strip() == item and item for item in confirmations)
            or len(confirmations) != len(set(confirmations))
        ):
            raise ValueError("authorization.confirmations must contain unique non-empty exact strings")
        object.__setattr__(self, "confirmations", confirmations)
        timestamp = self._parse_time(self.authorized_at, "authorized_at")
        expiry_text = self.expires_at
        if expiry_text is None:
            expiry_text = (timestamp + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
        if not isinstance(expiry_text, str) or not expiry_text.strip():
            raise ValueError("authorization.expires_at must be a non-empty ISO-8601 time")
        expiry_text = expiry_text.strip()
        expiry = self._parse_time(expiry_text, "expires_at")
        if expiry <= timestamp:
            raise ValueError("authorization.expires_at must be after authorized_at")
        object.__setattr__(self, "expires_at", expiry_text)
        if isinstance(self.run_count, bool) or not isinstance(self.run_count, int) or self.run_count < 1:
            raise ValueError("authorization.run_count must be a positive integer")
        benchmark = None if self.benchmark_parameters is None else _json_object(
            self.benchmark_parameters, "authorization.benchmark_parameters"
        )
        control = None if self.benchmark_control_plan is None else _json_object(
            self.benchmark_control_plan, "authorization.benchmark_control_plan"
        )
        if (benchmark is None) != (control is None):
            raise ValueError("benchmark authorization requires both benchmark parameters and a control plan")
        if benchmark is not None:
            if set(benchmark) != {"warmups", "runs"}:
                raise ValueError("authorization.benchmark_parameters must contain only warmups and runs")
            warmups, runs = benchmark["warmups"], benchmark["runs"]
            if (
                isinstance(warmups, bool) or not isinstance(warmups, int) or warmups < 0
                or isinstance(runs, bool) or not isinstance(runs, int) or runs < 1
                or self.run_count != warmups + runs
            ):
                raise ValueError("authorization run_count must equal benchmark warmups plus runs")
            required_control = {"baseline", "reset", "cleanup", "control_plan_digest"}
            if set(control or {}) != required_control:
                raise ValueError("authorization benchmark control plan fields are invalid")
            phases = {name: control[name] for name in ("baseline", "reset", "cleanup")}
            if any(not isinstance(phases[name], list) or not phases[name] for name in phases):
                raise ValueError("authorization benchmark control phases must contain typed plan steps")
            if control["control_plan_digest"] != canonical_digest(phases):
                raise ValueError("authorization benchmark control plan digest is invalid")
        elif self.run_count != 1:
            raise ValueError("non-benchmark physical authorization run_count must be 1")
        object.__setattr__(self, "benchmark_parameters", benchmark)
        object.__setattr__(self, "benchmark_control_plan", control)

    @staticmethod
    def _parse_time(value: str, field_name: str) -> datetime:
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise ValueError(f"authorization.{field_name} must be an ISO-8601 time") from error
        if timestamp.utcoffset() is None:
            raise ValueError(f"authorization.{field_name} must include a UTC offset")
        return timestamp.astimezone(timezone.utc)

    @classmethod
    def for_plan(
        cls, plan: ScenarioPlan, *, actor: str, request: str, authorized_at: str,
        expires_at: str | None = None, run_count: int = 1,
        confirmations: tuple[str, ...] | list[str] = (),
        benchmark_parameters: Mapping[str, Any] | None = None,
        benchmark_control_plan: BenchmarkControlPlan | Mapping[str, Any] | None = None,
    ) -> "PhysicalAuthorization":
        control = (
            benchmark_control_plan.to_dict()
            if isinstance(benchmark_control_plan, BenchmarkControlPlan)
            else benchmark_control_plan
        )
        return cls(
            actor=actor, request=request, integration_id=plan.integration_id,
            manifest_digest=plan.manifest_digest, plan_digest=plan.plan_digest,
            scenario_id=plan.scenario_id, parameters=plan.parameters,
            safety_ceiling=plan.safety_ceiling, confirmations=tuple(confirmations), authorized_at=authorized_at,
            expires_at=expires_at, run_count=run_count,
            benchmark_parameters=benchmark_parameters,
            benchmark_control_plan=control,
        )

    @classmethod
    def for_benchmark(
        cls, plan: ScenarioPlan, *, actor: str, request: str, authorized_at: str,
        expires_at: str | None, warmups: int, runs: int,
        control_plan: BenchmarkControlPlan, confirmations: tuple[str, ...] | list[str] = (),
    ) -> "PhysicalAuthorization":
        return cls.for_plan(
            plan, actor=actor, request=request, authorized_at=authorized_at,
            expires_at=expires_at, run_count=warmups + runs, confirmations=confirmations,
            benchmark_parameters={"warmups": warmups, "runs": runs},
            benchmark_control_plan=control_plan,
        )

    def verify(
        self, plan: ScenarioPlan, *, requested_ceiling: SafetyClass | str | None = None,
        run_count: int = 1, benchmark_parameters: Mapping[str, Any] | None = None,
        benchmark_control_plan: BenchmarkControlPlan | Mapping[str, Any] | None = None,
        at: datetime | None = None,
    ) -> None:
        ceiling = plan.safety_ceiling if requested_ceiling is None else SafetyClass(requested_ceiling)
        now = datetime.now(timezone.utc) if at is None else at
        if now.utcoffset() is None:
            raise ValueError("authorization verification time must include a UTC offset")
        verified_at = now.astimezone(timezone.utc)
        if verified_at < self._parse_time(self.authorized_at, "authorized_at"):
            raise PermissionError("physical authorization is not active yet")
        if verified_at >= self._parse_time(self.expires_at or "", "expires_at"):
            raise PermissionError("physical authorization has expired")
        control = (
            benchmark_control_plan.to_dict()
            if isinstance(benchmark_control_plan, BenchmarkControlPlan)
            else None if benchmark_control_plan is None else _json_object(
                benchmark_control_plan, "benchmark_control_plan"
            )
        )
        benchmark = None if benchmark_parameters is None else _json_object(
            benchmark_parameters, "benchmark_parameters"
        )
        expected = {
            "integration_id": plan.integration_id,
            "manifest_digest": plan.manifest_digest,
            "plan_digest": plan.plan_digest,
            "scenario_id": plan.scenario_id,
            "parameters": dict(plan.parameters),
            "safety_ceiling": ceiling.value,
            "confirmations": tuple(plan.metadata.get("requires_confirmation", ())),
            "run_count": run_count,
            "benchmark_parameters": benchmark,
            "benchmark_control_plan": control,
        }
        actual = {
            "integration_id": self.integration_id,
            "manifest_digest": self.manifest_digest,
            "plan_digest": self.plan_digest,
            "scenario_id": self.scenario_id,
            "parameters": dict(self.parameters),
            "safety_ceiling": self.safety_ceiling.value,
            "confirmations": self.confirmations,
            "run_count": self.run_count,
            "benchmark_parameters": self.benchmark_parameters,
            "benchmark_control_plan": self.benchmark_control_plan,
        }
        if actual != expected:
            mismatches = [key for key in expected if actual[key] != expected[key]]
            raise PermissionError("physical authorization does not bind the requested plan: " + ", ".join(mismatches))

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "request": self.request,
            "integration_id": self.integration_id,
            "manifest_digest": self.manifest_digest,
            "plan_digest": self.plan_digest,
            "scenario_id": self.scenario_id,
            "parameters": dict(self.parameters),
            "safety_ceiling": self.safety_ceiling.value,
            "confirmations": list(self.confirmations),
            "authorized_at": self.authorized_at,
            "expires_at": self.expires_at,
            "run_count": self.run_count,
            "benchmark_parameters": self.benchmark_parameters,
            "benchmark_control_plan": self.benchmark_control_plan,
        }


@dataclass(frozen=True)
class LabRun:
    mode: str
    plan: ScenarioPlan
    batch: BatchResult
    attempts: tuple[tuple[dict[str, Any], ...], ...]
    started_at: str
    finished_at: str
    elapsed_seconds: float
    evidence_path: Path | None = None
    environment: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        wda = self.environment.get("wda")
        teardown_ok = not isinstance(wda, Mapping) or wda.get("teardown_complete") is True
        return self.batch.ok and teardown_ok

    @property
    def uncertain(self) -> bool:
        return self.batch.uncertain

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "ok": self.ok,
            "uncertain": self.uncertain,
            "plan": self.plan.to_dict(),
            "batch": self.batch.to_dict(),
            "attempts": [[dict(attempt) for attempt in group] for group in self.attempts],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": self.elapsed_seconds,
            "evidence_path": None if self.evidence_path is None else str(self.evidence_path),
            "environment": dict(self.environment),
        }


__all__ = [
    "BenchmarkControlPlan", "LabRun", "PhysicalAuthorization", "PlannedStep",
    "ScenarioPlan", "canonical_digest",
]
