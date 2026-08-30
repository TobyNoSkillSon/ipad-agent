"""Fake execution and explicitly authorized, evidence-bound physical execution."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from ipad_agent.coredevice import open_ipad
from ipad_agent.operations import BatchResult, OperationError, OperationPhase, OperationResult, SafetyClass
from ipad_agent.wda import XCTestConfig, short_session

from .evidence import evidence_document, record_evidence, utc_now
from .model import (
    BenchmarkControlPlan, LabRun, PhysicalAuthorization, PlannedStep, ScenarioPlan,
    canonical_digest,
)
from .planning import (
    MAX_PHYSICAL_SAFETY, _validated_url, assert_step_invariant, plan_scenario,
    verify_plan_safety,
)


class StepExecutor(Protocol):
    environment: Mapping[str, Any]
    def __enter__(self) -> "StepExecutor": ...
    def __exit__(self, *exc: object) -> None: ...
    def execute(self, step: PlannedStep, bundle_id: str) -> OperationResult: ...


class FakeExecutor:
    """Deterministic executor; overrides map operation IDs to results or callbacks."""
    environment: Mapping[str, Any] = {"fake": True, "source": "fake"}

    def __init__(self, overrides: Mapping[str, OperationResult | Callable[[PlannedStep], OperationResult]] | None = None) -> None:
        self.overrides = dict(overrides or {})

    def __enter__(self) -> "FakeExecutor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, step: PlannedStep, bundle_id: str) -> OperationResult:
        assert_step_invariant(step)
        override = self.overrides.get(step.operation.operation_id)
        if callable(override):
            return override(step)
        if isinstance(override, OperationResult):
            if override.operation.operation_id != step.operation.operation_id:
                raise ValueError("fake override operation_id does not match planned step")
            return override
        return OperationResult.succeeded(step.operation, {"fake": True, "operation": step.instruction["operation"]})


def _walk_mappings(value: Any):
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _walk_mappings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_mappings(item)


def _first_text(payload: Mapping[str, Any], names: tuple[str, ...]) -> str | None:
    wanted = {name.casefold() for name in names}
    for mapping in _walk_mappings(payload):
        for key, value in mapping.items():
            if key.casefold() in wanted and isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _coredevice_environment_from_payload(payload: Mapping[str, Any], *, device_id: str) -> dict[str, Any]:
    """Extract a bounded environment record from CoreDevice details only."""
    os_version = _first_text(payload, ("osVersionNumber", "osVersion", "operatingSystemVersion", "productVersion"))
    locale = _first_text(payload, ("locale", "currentLocale", "deviceLocale", "languageLocale"))
    model = _first_text(payload, ("marketingName", "modelName", "productType", "deviceType"))
    name = _first_text(payload, ("deviceType",)) or "iPad"
    result: dict[str, Any] = {
        "source": "CoreDevice", "capture": "device info details",
        "coredevice_identifier": device_id, "device_class": name,
        "os_version": os_version if os_version is not None else "unknown",
        "locale": locale.replace("_", "-") if locale is not None else "unknown",
    }
    if model is not None:
        result["model"] = model
    return result


def capture_coredevice_environment(device_id: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """Capture OS, device class/model, and locale without starting WDA."""
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("device_id must be non-empty")
    with tempfile.NamedTemporaryFile(suffix=".json") as output:
        try:
            completed = subprocess.run(
                [
                    "xcrun", "devicectl", "device", "info", "details", "--device", device_id.strip(),
                    "--json-output", output.name, "--quiet", "--timeout", f"{timeout:g}",
                ],
                capture_output=True, text=True, timeout=timeout + 1.0,
            )
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout).strip() or f"exit {completed.returncode}")
            payload = json.loads(Path(output.name).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("CoreDevice details were not an object")
            return _coredevice_environment_from_payload(payload, device_id=device_id.strip())
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, ValueError, RuntimeError) as error:
            return {
                "source": "CoreDevice", "capture": "device info details",
                "coredevice_identifier": device_id.strip(), "device_class": "unknown",
                "os_version": "unknown", "locale": "unknown",
                "capture_error": " ".join(str(error).split()) or type(error).__name__,
            }


class PhysicalExecutor:
    """CoreDevice-first executor with one owned lazy WDA burst and evidenced teardown."""

    def __init__(
        self, *, physical: bool = False, authorization: PhysicalAuthorization | None = None,
        plan: ScenarioPlan | None = None,
        config: XCTestConfig | None = None, timeout: float = 30.0,
        run_count: int = 1, benchmark_parameters: Mapping[str, Any] | None = None,
        benchmark_control_plan: BenchmarkControlPlan | None = None,
    ) -> None:
        if physical is not True:
            raise PermissionError("PhysicalExecutor requires physical=True")
        if not isinstance(authorization, PhysicalAuthorization):
            raise PermissionError("PhysicalExecutor requires a PhysicalAuthorization record")
        if not isinstance(plan, ScenarioPlan):
            raise PermissionError("PhysicalExecutor requires the exact authorized ScenarioPlan")
        authorization.verify(
            plan, run_count=run_count, benchmark_parameters=benchmark_parameters,
            benchmark_control_plan=benchmark_control_plan,
        )
        if timeout <= 0 or timeout > 180:
            raise ValueError("physical timeout must be between 0 and 180 seconds")
        self.authorization = authorization
        self.plan = plan
        self._authorization_run_count = run_count
        self._benchmark_parameters = benchmark_parameters
        self._benchmark_control_plan = benchmark_control_plan
        authorized_steps = list(plan.steps)
        if benchmark_control_plan is not None:
            authorized_steps.extend(
                step
                for phase in (
                    benchmark_control_plan.baseline,
                    benchmark_control_plan.reset,
                    benchmark_control_plan.cleanup,
                )
                for step in phase
            )
        self._authorized_steps = {
            step.operation.operation_id: canonical_digest(step.to_dict()) for step in authorized_steps
        }
        self.config = config
        self.timeout = timeout
        self._session_context: Any = None
        self._session: Any = None
        self.environment: dict[str, Any] = {
            "source": "CoreDevice", "wda": {
                "started": False, "owned": False, "teardown_attempted": False,
                "teardown_complete": False, "cleanup_scope": "owned-session-only",
            },
        }

    def __enter__(self) -> "PhysicalExecutor":
        return self

    def __exit__(self, *exc: object) -> None:
        wda = self.environment.setdefault("wda", {})
        if self._session_context is None:
            if wda.get("started") is not True:
                wda.update({"started": False, "owned": False, "teardown_attempted": False, "teardown_complete": True})
            return None
        wda["teardown_attempted"] = True
        try:
            self._session_context.__exit__(*exc)
        except Exception as error:
            # Preserve teardown failure as private evidence instead of losing the
            # entire run while unwinding the context manager.
            wda["teardown_complete"] = False
            wda["teardown_error"] = " ".join(str(error).split()) or type(error).__name__
        else:
            wda["teardown_complete"] = True
        finally:
            self._session_context = None
            self._session = None
        return None

    def _merge_coredevice_environment(self, device_id: str) -> None:
        wda = dict(self.environment.get("wda", {}))
        captured = capture_coredevice_environment(device_id, timeout=min(self.timeout, 10.0))
        self.environment.update(captured)
        self.environment["wda"] = wda

    def _wda(self):
        if self._session is None:
            config = self.config or XCTestConfig.discover(timeout=self.timeout)
            self.config = config
            self._merge_coredevice_environment(config.udid)
            # OS version and locale remain unknown if CoreDevice did not report
            # them; WDA/XCTest configuration is never a compatibility source.
            wda = self.environment.setdefault("wda", {})
            wda.update({"started": True, "owned": True, "teardown_attempted": False, "teardown_complete": False})
            session_context = short_session(config, timeout=min(180.0, max(30.0, self.timeout * 3)))
            try:
                session = session_context.__enter__()
            except Exception as error:
                # short_session owns its failed-start cleanup.  Record that the
                # attempt occurred, but do not claim teardown completion when
                # session creation never reached a verifiable yield point.
                wda.update({
                    "teardown_attempted": True, "teardown_complete": False,
                    "teardown_error": " ".join(str(error).split()) or type(error).__name__,
                })
                raise
            self._session_context = session_context
            self._session = session
        return self._session

    def execute(self, step: PlannedStep, bundle_id: str) -> OperationResult:
        assert_step_invariant(step)
        expected_step = self._authorized_steps.get(step.operation.operation_id)
        if expected_step is None or canonical_digest(step.to_dict()) != expected_step:
            raise PermissionError("step is outside the exact PhysicalAuthorization plan")
        ranks = {SafetyClass.OBSERVE: 0, SafetyClass.NAVIGATE: 1, SafetyClass.TRANSIENT: 2}
        if step.operation.safety_class not in ranks or ranks[step.operation.safety_class] > ranks[self.authorization.safety_ceiling]:
            raise PermissionError("step exceeds the PhysicalAuthorization safety ceiling")
        instruction = step.instruction
        operation = instruction["operation"]
        if operation == "open-url":
            _validated_url(
                instruction.get("value"), instruction.get("allowed_schemes"),
                action_id=step.action_id,
            )
        # Expiry and every exact authorization field are checked at the last
        # policy boundary before this physical/control step can dispatch.
        self.authorization.verify(
            self.plan, run_count=self._authorization_run_count,
            benchmark_parameters=self._benchmark_parameters,
            benchmark_control_plan=self._benchmark_control_plan,
        )
        dispatched = False
        started = time.perf_counter()
        try:
            if operation in {"activate", "open-url"}:
                dispatched = True
                launch = open_ipad(bundle_id, url=instruction.get("value"), timeout=self.timeout)
                self._merge_coredevice_environment(launch.device_id)
                response = {
                    "bundle_id": launch.bundle_id, "elapsed_seconds": launch.elapsed_seconds,
                    "locked": launch.locked,
                }
                if launch.locked is True:
                    return OperationResult.failed(
                        step.operation,
                        OperationError(
                            "device_locked", "CoreDevice reported the iPad locked",
                            {"locked": True, "bundle_id": launch.bundle_id, "dispatched": True},
                        ),
                    )
            else:
                session = self._wda()
                if operation == "inspect" and step.selector is None:
                    response = {"source": session.source_json(timeout=self.timeout)}
                elif operation == "swipe":
                    dispatched = True
                    session.execute("mobile: swipe", {"direction": instruction["direction"]}, timeout=self.timeout)
                    response = {}
                elif operation == "type":
                    active = session._request("GET", "/element/active", None, self.timeout)
                    key = "element-6066-11e4-a52e-4f735466cecf"
                    element = active.get(key) if isinstance(active, dict) else None
                    if not element:
                        raise RuntimeError("no active element")
                    dispatched = True
                    session.type(element, instruction["value"], timeout=self.timeout)
                    response = {}
                else:
                    if step.selector is None:
                        raise RuntimeError(f"{operation} requires a selector")
                    selector_timeout = float(instruction.get("seconds", 5.0))
                    deadline = time.monotonic() + selector_timeout
                    elements: list[str] = []
                    while True:
                        elements = session.find_all(
                            step.selector["using"], step.selector["value"],
                            timeout=max(0.5, min(2.0, selector_timeout)),
                        )
                        if len(elements) == 1 or len(elements) > 1 or time.monotonic() >= deadline:
                            break
                        time.sleep(0.1)
                    if len(elements) != 1:
                        raise RuntimeError(
                            f"selector cardinality must be exactly one for {instruction.get('selector')}; found {len(elements)}"
                        )
                    element = elements[0]
                    if operation == "inspect":
                        response = {
                            "selector": instruction.get("selector"),
                            "cardinality": 1,
                            "context": {
                                name: session.attribute(element, name, timeout=self.timeout)
                                for name in ("type", "name", "label", "value", "visible")
                            },
                        }
                    elif operation == "tap":
                        dispatched = True
                        session.click(element, timeout=self.timeout)
                        response = {}
                    elif operation == "clear-type":
                        dispatched = True
                        session.clear(element, timeout=self.timeout)
                        session.type(element, instruction["value"], timeout=self.timeout)
                        response = {}
                    elif operation == "wait":
                        response = {"selector": instruction.get("selector"), "cardinality": 1}
                    else:
                        raise RuntimeError(f"unsupported physical operation: {operation}")
            response["lab_elapsed_seconds"] = time.perf_counter() - started
            return OperationResult.succeeded(step.operation, response)
        except Exception as error:
            detail = OperationError(type(error).__name__, " ".join(str(error).split()) or type(error).__name__)
            lost = bool(getattr(error, "response_lost", False))
            if dispatched and step.operation.safety_class is SafetyClass.TRANSIENT:
                lost = True
            return OperationResult.response_lost(step.operation, detail) if lost else OperationResult.failed(step.operation, detail)


def _run(
    plan: ScenarioPlan, executor: StepExecutor, *, mode: str, record: bool,
    repository_root: str | Path, authorization: PhysicalAuthorization | None = None,
    authorization_run_count: int = 1,
    benchmark_parameters: Mapping[str, Any] | None = None,
    benchmark_control_plan: BenchmarkControlPlan | None = None,
) -> LabRun:
    safety_gate = verify_plan_safety(plan)
    if mode == "physical":
        if authorization is None:
            raise PermissionError("physical execution requires a PhysicalAuthorization record")
        if type(executor) is not PhysicalExecutor:
            raise PermissionError("physical evidence requires the sealed PhysicalExecutor path")
        authorization.verify(
            plan, run_count=authorization_run_count,
            benchmark_parameters=benchmark_parameters,
            benchmark_control_plan=benchmark_control_plan,
        )
    started_at = utc_now()
    started = time.perf_counter()
    final: list[OperationResult] = []
    attempts: list[tuple[dict[str, Any], ...]] = []
    with executor:
        for step in plan.steps:
            assert_step_invariant(step)
            history: list[dict[str, Any]] = []
            result: OperationResult | None = None
            for _ in range(plan.max_attempts):
                result = executor.execute(step, plan.bundle_id)
                history.append(result.to_dict())
                if result.ok is True:
                    break
                if (
                    not result.automated_retry_allowed
                    or result.phase is OperationPhase.RESPONSE_LOST
                    or (result.error is not None and result.error.code == "device_locked")
                ):
                    break
            assert result is not None
            final.append(result)
            attempts.append(tuple(history))
            if result.ok is not True:
                break
        if len(final) < len(plan.steps):
            for skipped in plan.steps[len(final):]:
                final.append(OperationResult.not_sent(
                    skipped.operation,
                    OperationError("skipped", "step was not sent because an earlier planned step failed"),
                ))
                attempts.append(tuple())
    finished_at = utc_now()
    elapsed = time.perf_counter() - started
    batch = BatchResult.aggregate(
        f"{plan.integration_id}.{plan.scenario_id}", final,
        metadata={"mode": mode, "safety_gate": safety_gate},
    )
    environment = dict(executor.environment)
    run = LabRun(mode, plan, batch, tuple(attempts), started_at, finished_at, elapsed, None, environment)
    if record:
        outcomes = [item.to_plain_result() for item in batch.results]
        document = evidence_document(
            mode=mode, plan=plan, outcomes=outcomes, started_at=started_at, finished_at=finished_at,
            metrics={"elapsed_seconds": elapsed, "attempt_counts": [len(item) for item in attempts]},
            device=environment, complete=batch.complete, authorization=authorization,
        )
        path = record_evidence(document, repository_root=repository_root)
        run = LabRun(mode, plan, batch, tuple(attempts), started_at, finished_at, elapsed, path, environment)
    return run


def run_fake_scenario(
    manifest_or_plan: ScenarioPlan | str | Path | Mapping[str, Any], scenario_id: str | None = None,
    *, parameters: Mapping[str, Any] | None = None, executor: FakeExecutor | None = None,
    record: bool = True, repository_root: str | Path = Path(__file__).resolve().parents[2],
) -> LabRun:
    plan = manifest_or_plan if isinstance(manifest_or_plan, ScenarioPlan) else plan_scenario(
        manifest_or_plan, scenario_id or "", parameters=parameters,
    )
    return _run(plan, executor or FakeExecutor(), mode="fake", record=record, repository_root=repository_root)


def run_physical_scenario(
    manifest_or_plan: ScenarioPlan | str | Path | Mapping[str, Any], scenario_id: str | None = None,
    *, physical: bool = False, authorization: PhysicalAuthorization | None = None,
    parameters: Mapping[str, Any] | None = None,
    safety_ceiling: SafetyClass = MAX_PHYSICAL_SAFETY,
    record: bool = True, repository_root: str | Path = Path(__file__).resolve().parents[2],
    timeout: float = 30.0,
) -> LabRun:
    if physical is not True:
        raise PermissionError("physical scenario execution requires physical=True")
    if not isinstance(authorization, PhysicalAuthorization):
        raise PermissionError("physical scenario execution requires a PhysicalAuthorization record")
    requested = SafetyClass(safety_ceiling)
    if requested not in {SafetyClass.OBSERVE, SafetyClass.NAVIGATE, SafetyClass.TRANSIENT}:
        raise ValueError(f"physical safety ceiling cannot exceed {MAX_PHYSICAL_SAFETY.value}")
    plan = manifest_or_plan if isinstance(manifest_or_plan, ScenarioPlan) else plan_scenario(
        manifest_or_plan, scenario_id or "", parameters=parameters, safety_ceiling=requested,
    )
    verify_plan_safety(plan, requested_ceiling=requested)
    authorization.verify(plan, requested_ceiling=requested)
    runner = PhysicalExecutor(
        physical=True, authorization=authorization, plan=plan, timeout=timeout
    )
    return _run(
        plan, runner, mode="physical", record=record, repository_root=repository_root,
        authorization=authorization,
    )


run_scenario_fake = run_fake_scenario
run_scenario_physical = run_physical_scenario

__all__ = [
    "FakeExecutor", "PhysicalExecutor", "StepExecutor", "capture_coredevice_environment",
    "run_fake_scenario", "run_physical_scenario", "run_scenario_fake", "run_scenario_physical",
]
