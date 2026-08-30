import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from ipad_agent.lab import (
    BenchmarkControlPlan,
    FakeExecutor,
    PhysicalAuthorization,
    PlannedStep,
    benchmark_scenario,
    compatibility_summary,
    completion_report,
    discover_physical_selectors,
    generate_integration_docs,
    plan_scenario,
    plan_selector_discovery,
    run_fake_scenario,
    validate_compatibility,
    validate_evidence,
)
from ipad_agent.lab.validation import LabValidationError
from ipad_agent.operations import OperationError, OperationResult, OperationSpec, RetryClass, SafetyClass

ROOT = Path(__file__).resolve().parents[1]
SAFARI = ROOT / "integrations" / "safari" / "integration.json"
MAPS = ROOT / "integrations" / "maps" / "integration.json"


def _environment(*, teardown_complete=True):
    return {
        "source": "CoreDevice", "capture": "device info details",
        "os_version": "18.1", "locale": "en-US",
        "wda": {
            "started": True, "owned": True, "teardown_attempted": True,
            "teardown_complete": teardown_complete, "cleanup_scope": "owned-session-only",
        },
    }


class SimulatedPhysicalExecutor(FakeExecutor):
    def __init__(self, *, teardown_complete=True):
        super().__init__()
        self.environment = _environment(teardown_complete=teardown_complete)


class SelectorExecutor(SimulatedPhysicalExecutor):
    def execute(self, step, bundle_id):
        if step.instruction["operation"] == "inspect":
            return OperationResult.succeeded(step.operation, {
                "source": {"children": [{"identifier": "target", "type": "Button", "label": "Go"}]}
            })
        return super().execute(step, bundle_id)


def _control_step(plan, phase, ordinal):
    metadata = {
        "integration_id": plan.integration_id,
        "scenario_id": "benchmark-control",
        "action_id": phase,
        "step_index": ordinal,
        "instruction_operation": "inspect",
        "declared_action_safety": "observe",
    }
    return PlannedStep(
        phase, ordinal,
        OperationSpec(
            f"{plan.integration_id}.benchmark-control.{ordinal}", phase,
            SafetyClass.OBSERVE, RetryClass.SAFE_REPEAT, metadata=metadata,
        ),
        {"operation": "inspect"},
    )


def _controls(plan):
    return BenchmarkControlPlan(
        (_control_step(plan, "baseline", 10),),
        (_control_step(plan, "reset", 11),),
        (_control_step(plan, "cleanup", 12),),
    )


class IntegrationLabBindingBlockers20260901Tests(unittest.TestCase):
    def test_selector_discovery_rejects_executor_injection(self):
        plan = plan_selector_discovery(SAFARI)
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_plan(
            plan, actor="test", request="bounded selector inspection",
            authorized_at=now.isoformat(), expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        with self.assertRaisesRegex(TypeError, "unexpected keyword argument 'executor'"):
            discover_physical_selectors(
                SAFARI, physical=True, authorization=authorization,
                executor=SelectorExecutor(),
            )

    def test_authorization_binds_expiry_run_counts_benchmark_parameters_and_controls(self):
        plan = plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"})
        controls = _controls(plan)
        now = datetime.now(timezone.utc)
        expired = PhysicalAuthorization.for_plan(
            plan, actor="test", request="expired", authorized_at=(now - timedelta(minutes=2)).isoformat(),
            expires_at=(now - timedelta(minutes=1)).isoformat(),
        )
        with self.assertRaisesRegex(PermissionError, "expired"):
            expired.verify(plan)
        authorization = PhysicalAuthorization.for_benchmark(
            plan, actor="test", request="exact benchmark", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(), warmups=1, runs=3,
            control_plan=controls,
        )
        with self.assertRaisesRegex(PermissionError, "run_count|benchmark_parameters"):
            authorization.verify(
                plan, run_count=5, benchmark_parameters={"warmups": 2, "runs": 3},
                benchmark_control_plan=controls,
            )
        with self.assertRaisesRegex(PermissionError, "callbacks are forbidden"):
            benchmark_scenario(
                plan, physical=True, authorization=authorization, warmups=1, runs=3,
                control_plan=controls, baseline_hook=lambda: None,
            )

    def test_physical_benchmark_rejects_simulated_executor_factory(self):
        plan = plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"})
        controls = _controls(plan)
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_benchmark(
            plan, actor="test", request="exact benchmark", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(), warmups=1, runs=3,
            control_plan=controls,
        )
        with self.assertRaisesRegex(PermissionError, "do not accept executor injection"):
            benchmark_scenario(
                plan, physical=True, authorization=authorization, control_plan=controls,
                warmups=1, runs=3, executor_factory=SimulatedPhysicalExecutor,
            )

    def test_warmup_and_reset_failures_are_incomplete_and_recorded(self):
        plan = plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"})
        failed = OperationResult.failed(plan.steps[0].operation, OperationError("warmup", "failed"))
        with tempfile.TemporaryDirectory() as temporary:
            result = benchmark_scenario(
                plan, warmups=1, runs=3,
                executor_factory=lambda: FakeExecutor({plan.steps[0].operation.operation_id: failed}),
                baseline_hook=lambda: None, reset_hook=lambda: None, cleanup_hook=lambda: None,
                repository_root=temporary,
            )
            self.assertFalse(result["ok"])
            evidence = validate_evidence(result["evidence_path"])
            self.assertFalse(evidence["complete"])
            self.assertEqual(1, evidence["metrics"]["completed_warmups"])
            self.assertEqual(0, evidence["metrics"]["completed_runs"])
        with tempfile.TemporaryDirectory() as temporary:
            result = benchmark_scenario(
                MAPS, "search-place-direct", parameters={"encoded_query": "test"},
                warmups=1, runs=3, baseline_hook=lambda: None,
                reset_hook=lambda: (_ for _ in ()).throw(RuntimeError("reset failed")),
                cleanup_hook=lambda: None, repository_root=temporary,
            )
            self.assertFalse(result["ok"])
            evidence = validate_evidence(result["evidence_path"])
            self.assertFalse(evidence["complete"])
            reset = next(item for item in evidence["metrics"]["hooks"]["events"] if item["hook"] == "reset")
            self.assertFalse(reset["ok"])

    def test_outcome_order_and_all_planned_steps_are_validation_invariants(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = run_fake_scenario(
                SAFARI, "show-web-page", parameters={"url": "https://example.com"},
                repository_root=temporary,
            )
            evidence = validate_evidence(run.evidence_path)
            changed = copy.deepcopy(evidence)
            changed["outcomes"][0]["_operation"]["operation_id"] = "safari.show-web-page.99"
            with self.assertRaisesRegex(LabValidationError, "planned step order"):
                validate_evidence(changed)
            changed = copy.deepcopy(evidence)
            changed["outcomes"] = []
            changed["complete"] = False
            with self.assertRaisesRegex(LabValidationError, "every planned step"):
                validate_evidence(changed)

    def test_completion_binds_compatibility_and_generated_at_is_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = run_fake_scenario(
                SAFARI, "show-web-page", parameters={"url": "https://example.com"},
                repository_root=root,
            )
            benchmark = benchmark_scenario(
                SAFARI, "show-web-page", parameters={"url": "https://example.com"},
                warmups=1, runs=3, baseline_hook=lambda: None,
                reset_hook=lambda: None, cleanup_hook=lambda: None, repository_root=root,
            )
            selected = [run.evidence_path, benchmark["evidence_path"]]
            compatibility = compatibility_summary(selected, generated_at="2026-09-01T00:00:00Z")
            docs = root / "safari.md"
            docs.write_text(generate_integration_docs(SAFARI), encoding="utf-8")
            report = completion_report(
                SAFARI, evidence=selected, compatibility=compatibility,
                docs_path=docs, require_physical=False,
            )
            self.assertFalse(report["complete"])
            self.assertTrue(any("scenario" in item["id"] or "coverage" in item["id"] for item in report["checks"] if not item["passed"]))
            changed = copy.deepcopy(compatibility)
            changed["generated_at"] = "not-a-time secret"
            with self.assertRaisesRegex(LabValidationError, "generated_at"):
                validate_compatibility(changed)
            changed = copy.deepcopy(compatibility)
            changed["source_evidence"] = [{"sha256": "0" * 64}]
            report = completion_report(
                SAFARI, evidence=selected, compatibility=changed,
                docs_path=docs, require_physical=False,
            )
            compatibility_check = next(item for item in report["checks"] if item["id"] == "compatibility.redacted")
            self.assertFalse(compatibility_check["passed"])

    def test_generated_docs_include_unused_actions(self):
        manifest = json.loads(SAFARI.read_text(encoding="utf-8"))
        manifest["actions"]["unused-inspection"] = {
            "description": "An intentionally unused action for documentation coverage.",
            "capability": manifest["capabilities"][0],
            "steps": [{"operation": "activate"}],
            "safety": "navigate", "retry": "safe_repeat",
        }
        manifest["retry"]["idempotent_actions"].append("unused-inspection")
        docs = generate_integration_docs(manifest)
        self.assertIn("### `unused-inspection`", docs)
        self.assertIn("Used by scenarios: none (unused/orphan action).", docs)


if __name__ == "__main__":
    unittest.main()
