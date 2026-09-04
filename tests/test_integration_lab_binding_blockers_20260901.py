import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
    run_physical_scenario,
    validate_compatibility,
    validate_evidence,
)
from ipad_agent.coredevice import LaunchResult, UnlockDispatchResult
from ipad_agent.lab.evidence import evidence_document
from ipad_agent.lab.runner import PhysicalExecutor
from ipad_agent.lab.validation import LabValidationError
from ipad_agent.operations import OperationError, OperationResult, OperationSpec, RetryClass, SafetyClass
from tests.lab_fixture import isolate_authorization_receipts, lab_fixture_manifest

ROOT = Path(__file__).resolve().parents[1]
SAFARI = ROOT / "integrations" / "safari" / "integration.json"
LAB_FIXTURE = lab_fixture_manifest()


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


def _successful_outcomes(plan):
    executor = FakeExecutor()
    return [executor.execute(step, plan.bundle_id).to_plain_result() for step in plan.steps]


def _physical_evidence(plan, *, mode="physical", metrics=None, authorization=None):
    return evidence_document(
        mode=mode, plan=plan, outcomes=_successful_outcomes(plan),
        started_at="2026-09-01T00:01:00Z", finished_at="2026-09-01T00:02:00Z",
        metrics=metrics or {},
        host={"hostname": "private-host"},
        device={
            **_environment(),
            "device_identifier": "private-device-identifier",
        },
        authorization=authorization or PhysicalAuthorization.for_plan(
            plan, actor="private actor", request="private request",
            authorized_at="2026-09-01T00:00:00Z",
            expires_at="2026-09-01T00:10:00Z",
        ),
    )


class IntegrationLabBindingBlockers20260901Tests(unittest.TestCase):
    def setUp(self) -> None:
        isolate_authorization_receipts(self)

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

    def test_authorization_identifier_and_exact_fifteen_minute_boundary(self):
        plan = plan_scenario(SAFARI, "activate-direct")
        authorized = datetime(2026, 9, 1, tzinfo=timezone.utc)
        boundary = authorized + timedelta(minutes=15)
        first = PhysicalAuthorization.for_plan(
            plan, actor="test", request="boundary", authorized_at=authorized.isoformat(),
            expires_at=boundary.isoformat(),
        )
        second = PhysicalAuthorization.for_plan(
            plan, actor="test", request="boundary", authorized_at=authorized.isoformat(),
            expires_at=boundary.isoformat(),
        )
        self.assertRegex(first.authorization_id, r"^[a-f0-9]{64}$")
        self.assertNotEqual(first.authorization_id, second.authorization_id)
        self.assertEqual(first.authorization_id, first.to_dict()["authorization_id"])
        first.verify(plan, at=boundary - timedelta(microseconds=1))
        with self.assertRaisesRegex(PermissionError, "expired"):
            first.verify(plan, at=boundary)
        with self.assertRaisesRegex(ValueError, "no more than 15 minutes"):
            PhysicalAuthorization.for_plan(
                plan, actor="test", request="too long", authorized_at=authorized.isoformat(),
                expires_at=(boundary + timedelta(microseconds=1)).isoformat(),
            )
        changed = first.to_dict()
        changed["authorization_id"] = "predictable"
        with self.assertRaisesRegex(ValueError, "256-bit"):
            PhysicalAuthorization(**changed)

    def test_physical_authorization_receipt_blocks_object_copy_and_process_reuse(self):
        plan = plan_scenario(SAFARI, "activate-direct")
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_plan(
            plan, actor="test", request="one invocation", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        locked = UnlockDispatchResult("locked", None)
        with tempfile.TemporaryDirectory() as temporary, patch(
            "ipad_agent.lab.runner.AUTHORIZATION_RECEIPT_ROOT", Path(temporary)
        ), patch(
            "ipad_agent.lab.runner.open_ipad_when_unlocked", return_value=locked,
        ) as launch:
            first = run_physical_scenario(
                plan, physical=True, authorization=authorization, record=False,
                repository_root=temporary,
            )
            self.assertFalse(first.ok)
            with self.assertRaisesRegex(PermissionError, "already been consumed"):
                run_physical_scenario(
                    plan, physical=True, authorization=authorization, record=False,
                    repository_root=Path(temporary) / "different-evidence-root",
                )
            copied = PhysicalAuthorization(**authorization.to_dict())
            with self.assertRaisesRegex(PermissionError, "already been consumed"):
                run_physical_scenario(
                    plan, physical=True, authorization=copied, record=False,
                    repository_root=temporary,
                )
            self.assertEqual(1, launch.call_count)
            receipt = Path(temporary) / ".runtime" / "state" / "physical-authorizations" / f"{authorization.authorization_id}.json"
            self.assertTrue(receipt.is_file())
            self.assertEqual(0o600, receipt.stat().st_mode & 0o777)
            child = subprocess.run(
                [sys.executable, "-c", (
                    "from ipad_agent.lab._authorization_state import consume_authorization_receipt; "
                    f"consume_authorization_receipt({temporary!r}, {authorization.authorization_id!r}, {{'copy': True}})"
                )], cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(0, child.returncode)
            self.assertIn("already been consumed", child.stderr)

    def test_fake_run_creates_no_authorization_state(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "ipad_agent.lab.runner.AUTHORIZATION_RECEIPT_ROOT", Path(temporary)
        ):
            run = run_fake_scenario(SAFARI, "activate-direct", record=False, repository_root=temporary)
            self.assertTrue(run.ok)
            self.assertFalse((Path(temporary) / ".runtime").exists())

    def test_one_executor_cannot_replay_an_authorized_step(self):
        plan = plan_scenario(SAFARI, "activate-direct")
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_plan(
            plan, actor="test", request="one executor", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        locked = UnlockDispatchResult("locked", None)
        with tempfile.TemporaryDirectory() as temporary, patch(
            "ipad_agent.lab.runner.AUTHORIZATION_RECEIPT_ROOT", Path(temporary)
        ), patch(
            "ipad_agent.lab.runner.open_ipad_when_unlocked", return_value=locked,
        ) as launch:
            executor = PhysicalExecutor(
                physical=True, authorization=authorization, plan=plan,
            )
            first = executor.execute(plan.steps[0], plan.bundle_id)
            self.assertEqual("device_locked", first.error.code)
            with self.assertRaisesRegex(PermissionError, "exhausted"):
                executor.execute(plan.steps[0], plan.bundle_id)
            self.assertEqual(1, launch.call_count)

    def test_deepcopied_executor_cannot_replay_a_remaining_step(self):
        base = plan_scenario(SAFARI, "activate-direct")
        first = base.steps[0]
        second_operation = replace(
            first.operation,
            operation_id="safari.activate-direct.1",
            name="activate:second",
        )
        second = replace(
            first, action_id="activate-second", index=1, operation=second_operation,
        )
        plan = replace(base, steps=(first, second))
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_plan(
            plan, actor="test", request="two-step copy resistance",
            authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        locked = UnlockDispatchResult("locked", None)
        with tempfile.TemporaryDirectory() as temporary, patch(
            "ipad_agent.lab.runner.AUTHORIZATION_RECEIPT_ROOT", Path(temporary)
        ), patch(
            "ipad_agent.lab.runner.open_ipad_when_unlocked", return_value=locked,
        ) as launch:
            executor = PhysicalExecutor(
                physical=True, authorization=authorization, plan=plan,
            )
            executor.execute(first, plan.bundle_id)
            copied = copy.deepcopy(executor)
            executor.execute(second, plan.bundle_id)
            with self.assertRaisesRegex(PermissionError, "already been consumed"):
                copied.execute(second, plan.bundle_id)
        self.assertEqual(2, launch.call_count)

    def test_concurrent_copies_get_exactly_one_physical_dispatch(self):
        plan = plan_scenario(SAFARI, "activate-direct")
        now = datetime.now(timezone.utc)
        original = PhysicalAuthorization.for_plan(
            plan, actor="test", request="thread race", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        authorizations = (original, PhysicalAuthorization(**original.to_dict()))
        locked = UnlockDispatchResult("locked", None)

        def invoke(grant):
            try:
                run_physical_scenario(
                    plan, physical=True, authorization=grant, record=False,
                    repository_root=temporary,
                )
            except PermissionError as error:
                return str(error)
            return "dispatched"

        with tempfile.TemporaryDirectory() as temporary, patch(
            "ipad_agent.lab.runner.AUTHORIZATION_RECEIPT_ROOT", Path(temporary)
        ), patch(
            "ipad_agent.lab.runner.open_ipad_when_unlocked", return_value=locked,
        ) as launch, ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(invoke, authorizations))
        self.assertEqual(1, outcomes.count("dispatched"))
        self.assertEqual(1, sum("already been consumed" in item for item in outcomes))
        self.assertEqual(1, launch.call_count)

    def test_benchmark_consumes_once_but_allows_its_internal_attempts(self):
        plan = plan_scenario(SAFARI, "open-url-direct", parameters={"url": "https://example.com"})
        controls = _controls(plan)
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_benchmark(
            plan, actor="test", request="one benchmark", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(), warmups=1, runs=3,
            control_plan=controls,
        )
        launch_result = LaunchResult(plan.bundle_id, "device", 0.01, None, False)
        dispatched = UnlockDispatchResult("dispatched", launch_result)

        class Session:
            def source_json(self, *, timeout):
                return {"children": []}

        environment = {
            "source": "CoreDevice", "capture": "device info details",
            "coredevice_identifier": "device", "device_class": "iPad",
            "os_version": "18.1", "locale": "en-US",
        }
        with tempfile.TemporaryDirectory() as temporary, patch(
            "ipad_agent.lab.runner.AUTHORIZATION_RECEIPT_ROOT", Path(temporary)
        ), patch.object(PhysicalExecutor, "_wda", return_value=Session()), patch(
            "ipad_agent.lab.runner.open_ipad_when_unlocked", return_value=dispatched,
        ) as launch, patch(
            "ipad_agent.lab.runner.capture_coredevice_environment", return_value=environment,
        ):
            result = benchmark_scenario(
                plan, physical=True, authorization=authorization, warmups=1, runs=3,
                control_plan=controls, record=False, repository_root=temporary,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(4, launch.call_count)
            receipt_directory = Path(temporary) / ".runtime" / "state" / "physical-authorizations"
            self.assertGreaterEqual(
                len(list(receipt_directory.glob("*.json"))), 1 + launch.call_count,
            )
            repeated = benchmark_scenario(
                plan, physical=True, authorization=authorization, warmups=1, runs=3,
                control_plan=controls, record=False, repository_root=temporary,
            )
            self.assertFalse(repeated["ok"])
            self.assertEqual(4, launch.call_count)

    def test_authorization_binds_expiry_run_counts_benchmark_parameters_and_controls(self):
        plan = plan_scenario(SAFARI, "open-url-direct", parameters={"url": "https://example.com"})
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
        plan = plan_scenario(SAFARI, "open-url-direct", parameters={"url": "https://example.com"})
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
        plan = plan_scenario(SAFARI, "open-url-direct", parameters={"url": "https://example.com"})
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
                LAB_FIXTURE, "search-direct", parameters={"query": "test"},
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
                SAFARI, "open-url-direct", parameters={"url": "https://example.com"},
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
                SAFARI, "open-url-direct", parameters={"url": "https://example.com"},
                repository_root=root,
            )
            benchmark = benchmark_scenario(
                SAFARI, "open-url-direct", parameters={"url": "https://example.com"},
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

    def test_selector_discovery_never_projects_as_physical_compatibility(self):
        plan = plan_selector_discovery(SAFARI)
        authorization = PhysicalAuthorization.for_plan(
            plan, actor="private actor", request="private selector inspection",
            authorized_at="2026-09-01T00:00:00Z",
            expires_at="2026-09-01T00:10:00Z",
        )
        discovery = _physical_evidence(
            plan, mode="discovery",
            metrics={"candidate_count": 1, "repeatable_candidate_count": 1},
            authorization=authorization,
        )
        mislabeled_physical = _physical_evidence(
            plan, mode="physical", authorization=authorization,
        )

        summary = compatibility_summary(
            [discovery, mislabeled_physical], generated_at="2026-09-01T00:03:00Z",
        )

        self.assertEqual([], summary["source_evidence"])
        self.assertEqual([], summary["integrations"])
        self.assertNotIn("private", json.dumps(summary))

    def test_physical_runs_and_physical_benchmarks_remain_redacted_and_deterministic(self):
        plan = plan_scenario(
            SAFARI, "open-url-direct", parameters={"url": "https://private.example/path"},
        )
        physical = _physical_evidence(plan, metrics={"elapsed_seconds": 1.25})
        controls = _controls(plan)
        benchmark_authorization = PhysicalAuthorization.for_benchmark(
            plan, actor="private actor", request="private benchmark request",
            authorized_at="2026-09-01T00:00:00Z",
            expires_at="2026-09-01T00:10:00Z", warmups=1, runs=3,
            control_plan=controls,
        )
        step_outcomes = _successful_outcomes(plan)
        benchmark_outcomes = [
            {
                "kind": "warmup" if index == 0 else "measured",
                "execution_index": index, "executed": True, "ok": True,
                "uncertain": False, "elapsed_seconds": 1.0 + index / 10,
                "steps": step_outcomes,
            }
            for index in range(4)
        ]
        benchmark = evidence_document(
            mode="benchmark", plan=plan, outcomes=benchmark_outcomes,
            started_at="2026-09-01T00:01:00Z", finished_at="2026-09-01T00:02:00Z",
            metrics={
                "physical": True, "warmups": 1, "runs": 3,
                "completed_warmups": 1, "completed_runs": 3,
                "successful_warmups": 1, "successful_runs": 3,
                "uncertain_runs": 0,
                "hooks": {"cleanup_ok": True, "events": []},
                "control_plan": controls.to_dict(),
                "minimum_seconds": 1.1, "median_seconds": 1.2,
                "p95_seconds": 1.3, "maximum_seconds": 1.3,
            },
            host={"hostname": "private-host"},
            device={**_environment(), "device_identifier": "private-device-identifier"},
            authorization=benchmark_authorization,
        )
        generated_at = "2026-09-01T00:03:00Z"

        first = compatibility_summary([benchmark, physical], generated_at=generated_at)
        second = compatibility_summary([physical, benchmark], generated_at=generated_at)

        self.assertEqual(first, second)
        self.assertEqual(["benchmark", "physical"], [
            scenario["mode"] for scenario in first["integrations"][0]["scenarios"]
        ])
        self.assertTrue(first["integrations"][0]["physical_tested"])
        encoded = json.dumps(first)
        self.assertNotIn("private.example", encoded)
        self.assertNotIn("private-host", encoded)
        self.assertNotIn("private actor", encoded)
        self.assertNotIn("private-device-identifier", encoded)

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
