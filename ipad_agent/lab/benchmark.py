"""Scenario benchmarking with explicit, authorization-bound state control."""
from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any, Callable, Mapping

from ipad_agent.core.operations import OperationError, OperationResult, SafetyClass

from .evidence import evidence_document, record_evidence, utc_now
from .model import BenchmarkControlPlan, LabRun, PhysicalAuthorization, PlannedStep, ScenarioPlan
from .planning import MAX_PHYSICAL_SAFETY, assert_step_invariant, plan_scenario, verify_plan_safety
from .runner import FakeExecutor, PhysicalExecutor, StepExecutor, _run

Hook = Callable[[], Any]
_SAFETY_RANK = {SafetyClass.OBSERVE: 0, SafetyClass.NAVIGATE: 1, SafetyClass.TRANSIENT: 2}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def _validate_control_plan(control: BenchmarkControlPlan, plan: ScenarioPlan) -> None:
    scenario_ids = {step.operation.operation_id for step in plan.steps}
    for phase in (control.baseline, control.reset, control.cleanup):
        for step in phase:
            assert_step_invariant(step)
            if step.instruction.get("operation") == "open-url":
                raise ValueError("benchmark control steps cannot dispatch URLs outside manifest actions")
            if step.operation.operation_id in scenario_ids:
                raise ValueError("benchmark control steps must have distinct operation IDs")
            if step.operation.safety_class not in _SAFETY_RANK:
                raise ValueError("benchmark control steps cannot be persistent or protected")
            if _SAFETY_RANK[step.operation.safety_class] > _SAFETY_RANK[plan.safety_ceiling]:
                raise ValueError("benchmark control step exceeds the scenario safety ceiling")
            metadata = step.operation.metadata
            if metadata.get("integration_id") != plan.integration_id:
                raise ValueError("benchmark control step cannot escape the authorized integration")
            if metadata.get("instruction_operation") != step.instruction.get("operation"):
                raise ValueError("benchmark control step metadata is not bound to its instruction")


def _skipped_results(steps: tuple[PlannedStep, ...], completed: list[OperationResult]) -> None:
    for step in steps[len(completed):]:
        completed.append(OperationResult.not_sent(
            step.operation,
            OperationError("skipped", "control step was not sent because an earlier control step failed"),
        ))


def _execute_control(
    phase_name: str, steps: tuple[PlannedStep, ...], factory: Callable[[], StepExecutor],
    *, execution_index: int, bundle_id: str,
) -> dict[str, Any]:
    results: list[OperationResult] = []
    environment: dict[str, Any] = {}
    try:
        executor = factory()
        with executor:
            for step in steps:
                try:
                    result = executor.execute(step, bundle_id)
                except Exception as error:
                    result = OperationResult.failed(
                        step.operation,
                        OperationError(type(error).__name__, " ".join(str(error).split()) or type(error).__name__),
                    )
                results.append(result)
                if result.ok is not True:
                    break
        environment = dict(executor.environment)
    except Exception as error:
        if not results:
            results.append(OperationResult.failed(
                steps[0].operation,
                OperationError(type(error).__name__, " ".join(str(error).split()) or type(error).__name__),
            ))
        environment = {"control_error": " ".join(str(error).split()) or type(error).__name__}
    _skipped_results(steps, results)
    wda = environment.get("wda")
    teardown_ok = not isinstance(wda, Mapping) or wda.get("teardown_complete") is True
    ok = all(result.ok is True for result in results) and teardown_ok
    return {
        "hook": phase_name, "execution_index": execution_index, "ok": ok,
        "outcomes": [result.to_plain_result() for result in results],
        "environment": environment,
    }


def _run_callback(name: str, hook: Hook, *, execution_index: int) -> dict[str, Any]:
    try:
        hook()
    except Exception as error:
        return {
            "hook": name, "execution_index": execution_index, "ok": False,
            "error": " ".join(str(error).split()) or type(error).__name__,
        }
    return {"hook": name, "execution_index": execution_index, "ok": True}


def _benchmark_outcome(run: LabRun, *, kind: str, execution_index: int) -> dict[str, Any]:
    return {
        "kind": kind, "execution_index": execution_index, "executed": True,
        "ok": run.ok, "uncertain": run.uncertain,
        "elapsed_seconds": run.elapsed_seconds,
        "steps": [item.to_plain_result() for item in run.batch.results],
    }


def _skipped_benchmark_outcome(
    plan: ScenarioPlan, *, kind: str, execution_index: int,
) -> dict[str, Any]:
    steps = [
        OperationResult.not_sent(
            step.operation,
            OperationError("skipped", "execution was not sent because an earlier benchmark phase failed"),
        ).to_plain_result()
        for step in plan.steps
    ]
    return {
        "kind": kind, "execution_index": execution_index, "executed": False,
        "ok": False, "uncertain": False, "elapsed_seconds": 0.0, "steps": steps,
    }


def benchmark_scenario(
    manifest_or_plan: ScenarioPlan | str | Path | Mapping[str, Any], scenario_id: str | None = None,
    *, warmups: int = 1, runs: int = 5, physical: bool = False,
    authorization: PhysicalAuthorization | None = None,
    parameters: Mapping[str, Any] | None = None,
    safety_ceiling: SafetyClass = MAX_PHYSICAL_SAFETY,
    executor_factory: Callable[[], StepExecutor] | None = None,
    baseline_hook: Hook | None = None, reset_hook: Hook | None = None,
    cleanup_hook: Hook | None = None,
    control_plan: BenchmarkControlPlan | None = None,
    record: bool = True, repository_root: str | Path = Path(__file__).resolve().parents[2],
) -> dict[str, Any]:
    if isinstance(warmups, bool) or not isinstance(warmups, int) or not 0 <= warmups <= 20:
        raise ValueError("warmups must be an integer between 0 and 20")
    maximum_runs = 20 if physical else 100
    if isinstance(runs, bool) or not isinstance(runs, int) or not 1 <= runs <= maximum_runs:
        raise ValueError(f"runs must be an integer between 1 and {maximum_runs}")
    if physical and executor_factory is not None:
        raise PermissionError("physical benchmarks do not accept executor injection")
    if physical is not True and executor_factory is PhysicalExecutor:
        raise PermissionError("a physical executor requires physical=True")
    requested = SafetyClass(safety_ceiling)
    if physical and requested not in _SAFETY_RANK:
        raise ValueError(f"physical safety ceiling cannot exceed {MAX_PHYSICAL_SAFETY.value}")
    plan = manifest_or_plan if isinstance(manifest_or_plan, ScenarioPlan) else plan_scenario(
        manifest_or_plan, scenario_id or "", parameters=parameters, safety_ceiling=requested,
    )
    verify_plan_safety(plan, requested_ceiling=requested)

    repeated = warmups + runs > 1
    stateful = plan.metadata.get("mutates_user_data") is True
    callbacks = {"baseline": baseline_hook, "reset": reset_hook, "cleanup": cleanup_hook}
    if any(hook is not None and not callable(hook) for hook in callbacks.values()):
        raise TypeError("benchmark hooks must be callable")
    if physical:
        if any(hook is not None for hook in callbacks.values()):
            raise PermissionError("physical benchmark callbacks are forbidden; use typed control_plan steps")
        if not isinstance(control_plan, BenchmarkControlPlan):
            raise ValueError("repeated physical benchmarks require typed baseline/reset/cleanup control_plan steps")
        _validate_control_plan(control_plan, plan)
        if not isinstance(authorization, PhysicalAuthorization):
            raise PermissionError("physical benchmark requires a PhysicalAuthorization record")
        benchmark_parameters = {"warmups": warmups, "runs": runs}
        authorization.verify(
            plan, requested_ceiling=requested, run_count=warmups + runs,
            benchmark_parameters=benchmark_parameters, benchmark_control_plan=control_plan,
        )
    else:
        benchmark_parameters = None
        if control_plan is not None:
            raise ValueError("typed control_plan steps are reserved for physical benchmarks")
        requires_state_control = repeated and stateful
        missing = [name for name, hook in callbacks.items() if requires_state_control and hook is None]
        if missing:
            raise ValueError(
                "repeated stateful benchmarks require baseline/reset/cleanup hooks; missing "
                + ", ".join(missing)
            )

    factory: Callable[[], StepExecutor]
    if physical:
        def physical_factory(claim: str) -> Callable[[], StepExecutor]:
            return lambda: PhysicalExecutor(
                physical=True, authorization=authorization, plan=plan,
                run_count=warmups + runs, benchmark_parameters=benchmark_parameters,
                benchmark_control_plan=control_plan, _execution_claim=claim,
            )
    else:
        factory = executor_factory or FakeExecutor
    started = utc_now()
    warmup_results: list[LabRun] = []
    measured: list[LabRun] = []
    hook_events: list[dict[str, Any]] = []
    execution_index = 0
    execution_failed = False

    if physical:
        assert control_plan is not None
        baseline_event = _execute_control(
            "baseline", control_plan.baseline, physical_factory("baseline:0"),
            execution_index=0, bundle_id=plan.bundle_id,
        )
    elif baseline_hook is not None:
        baseline_event = _run_callback("baseline", baseline_hook, execution_index=0)
    else:
        baseline_event = None
    if baseline_event is not None:
        hook_events.append(baseline_event)
        execution_failed = baseline_event["ok"] is not True

    schedule = [("warmup", index) for index in range(warmups)] + [("measured", index) for index in range(runs)]
    for kind, _ in schedule:
        if execution_failed:
            break
        if execution_index:
            if physical:
                assert control_plan is not None
                reset_event = _execute_control(
                    "reset", control_plan.reset, physical_factory(f"reset:{execution_index}"),
                    execution_index=execution_index, bundle_id=plan.bundle_id,
                )
            elif reset_hook is not None:
                reset_event = _run_callback("reset", reset_hook, execution_index=execution_index)
            else:
                reset_event = None
            if reset_event is not None:
                hook_events.append(reset_event)
                if reset_event["ok"] is not True:
                    execution_failed = True
                    break
        try:
            run = _run(
                plan,
                physical_factory(f"run:{execution_index}")() if physical else factory(),
                mode="physical" if physical else "fake", record=False,
                repository_root=repository_root, authorization=authorization if physical else None,
                authorization_run_count=warmups + runs if physical else 1,
                benchmark_parameters=benchmark_parameters,
                benchmark_control_plan=control_plan,
            )
        except Exception as error:
            hook_events.append({
                "hook": "execution", "execution_index": execution_index, "kind": kind,
                "ok": False, "error": " ".join(str(error).split()) or type(error).__name__,
            })
            execution_failed = True
            break
        if kind == "warmup":
            warmup_results.append(run)
        else:
            measured.append(run)
        execution_index += 1
        if not run.ok:
            execution_failed = True

    if physical:
        assert control_plan is not None
        cleanup_event = _execute_control(
            "cleanup", control_plan.cleanup, physical_factory("cleanup:0"),
            execution_index=execution_index, bundle_id=plan.bundle_id,
        )
    elif cleanup_hook is not None:
        cleanup_event = _run_callback("cleanup", cleanup_hook, execution_index=execution_index)
    else:
        cleanup_event = None
    if cleanup_event is not None:
        hook_events.append(cleanup_event)
    cleanup_ok = cleanup_event is None or cleanup_event["ok"] is True
    finished = utc_now()

    durations = [item.elapsed_seconds for item in measured]
    all_scheduled = len(warmup_results) == warmups and len(measured) == runs
    all_runs = [*warmup_results, *measured]
    all_runs_ok = all_scheduled and all(item.ok for item in all_runs)
    metrics: dict[str, Any] = {
        "physical": physical, "warmups": warmups, "runs": runs,
        "completed_warmups": len(warmup_results), "completed_runs": len(measured),
        "successful_warmups": sum(item.ok for item in warmup_results),
        "successful_runs": sum(item.ok for item in measured),
        "uncertain_runs": sum(item.uncertain for item in measured),
        "stateful": stateful,
        "hooks": {
            "baseline": baseline_event is not None, "reset": any(item["hook"] == "reset" for item in hook_events),
            "cleanup": cleanup_event is not None, "cleanup_ok": cleanup_ok,
            "events": hook_events,
        },
    }
    if control_plan is not None:
        metrics["control_plan"] = control_plan.to_dict()
    if durations:
        metrics.update({
            "minimum_seconds": min(durations), "median_seconds": statistics.median(durations),
            "p95_seconds": _percentile(durations, 0.95), "maximum_seconds": max(durations),
        })

    benchmark_ok = all_runs_ok and cleanup_ok and not execution_failed
    evidence_path = None
    if record:
        actual_outcomes = {
            **{
                index: _benchmark_outcome(item, kind="warmup", execution_index=index)
                for index, item in enumerate(warmup_results)
            },
            **{
                warmups + index: _benchmark_outcome(
                    item, kind="measured", execution_index=warmups + index
                )
                for index, item in enumerate(measured)
            },
        }
        outcomes = [
            actual_outcomes.get(index) or _skipped_benchmark_outcome(
                plan, kind="warmup" if index < warmups else "measured", execution_index=index,
            )
            for index in range(warmups + runs)
        ]
        control_environments = [
            dict(item["environment"])
            for item in hook_events if isinstance(item.get("environment"), Mapping)
        ]
        environment = dict(all_runs[-1].environment) if all_runs else (
            dict(control_environments[-1]) if control_environments else {}
        )
        environment["benchmark_runs"] = [dict(item.environment) for item in all_runs]
        environment["benchmark_controls"] = control_environments
        document = evidence_document(
            mode="benchmark", plan=plan, outcomes=outcomes, started_at=started,
            finished_at=finished, metrics=metrics, device=environment,
            complete=benchmark_ok,
            authorization=authorization if physical else None,
        )
        evidence_path = record_evidence(document, repository_root=repository_root)
    return {
        "ok": benchmark_ok, "physical": physical, "metrics": metrics,
        "runs": measured, "warmup_runs": warmup_results, "evidence_path": evidence_path,
    }


benchmark = benchmark_scenario

__all__ = ["benchmark", "benchmark_scenario"]
