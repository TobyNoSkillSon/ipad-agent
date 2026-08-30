import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from ipad_agent.lab import (
    FakeExecutor,
    PhysicalAuthorization,
    benchmark_scenario,
    compatibility_summary,
    generate_integration_docs,
    plan_scenario,
    run_physical_scenario,
    scaffold_integration,
    selector_observations,
    validate_compatibility,
    validate_evidence,
    validate_manifest,
)
from ipad_agent.lab.validation import LabValidationError

ROOT = Path(__file__).resolve().parents[1]
SAFARI = ROOT / "integrations" / "safari" / "integration.json"
MAPS = ROOT / "integrations" / "maps" / "integration.json"
CLOCK = ROOT / "integrations" / "clock" / "integration.json"


def authorization_for(plan):
    return PhysicalAuthorization.for_plan(
        plan,
        actor="test actor",
        request="execute only this exact test plan",
        authorized_at=datetime.now(timezone.utc).isoformat(),
    )


class EvidenceOnlyPhysicalExecutor(FakeExecutor):
    def __init__(self, *, teardown_complete=True):
        super().__init__()
        self.environment = {
            "source": "CoreDevice",
            "capture": "device info details",
            "os_version": "18.1",
            "locale": "en-US",
            "wda": {
                "started": True,
                "owned": True,
                "teardown_attempted": True,
                "teardown_complete": teardown_complete,
                "cleanup_scope": "owned-session-only",
            },
        }


class IntegrationLabRecoveredBlockerTests(unittest.TestCase):
    def test_manifest_cannot_hide_executable_safety_or_retry(self):
        manifest = json.loads(SAFARI.read_text(encoding="utf-8"))
        manifest["actions"]["open-url"]["safety"] = "observe"
        with self.assertRaisesRegex(LabValidationError, "safety must"):
            validate_manifest(manifest)
        manifest = json.loads(SAFARI.read_text(encoding="utf-8"))
        manifest["actions"]["open-url"]["retry"] = "safe_repeat"
        with self.assertRaisesRegex(LabValidationError, "retry|idempotent"):
            validate_manifest(manifest)

    def test_mixed_action_steps_inherit_the_action_retry_contract(self):
        plan = plan_scenario(CLOCK, "transient-stopwatch")
        start_steps = [step for step in plan.steps if step.action_id == "start-stopwatch"]
        self.assertEqual(["inspect_then_decide", "inspect_then_decide"], [step.operation.retry_class.value for step in start_steps])

    def test_authorization_and_executor_bind_the_exact_plan(self):
        plan = plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"})
        authorization = authorization_for(plan)
        changed = plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.org"})
        with self.assertRaisesRegex(PermissionError, "parameters|plan_digest"):
            authorization.verify(changed)
        from ipad_agent.lab.runner import PhysicalExecutor
        with self.assertRaisesRegex(PermissionError, "exact authorized ScenarioPlan"):
            PhysicalExecutor(physical=True, authorization=authorization)

    def test_evidence_is_bound_to_identity_plan_parameters_environment_and_safety(self):
        with tempfile.TemporaryDirectory() as temporary:
            from ipad_agent.lab import run_fake_scenario
            run = run_fake_scenario(
                SAFARI, "show-web-page", parameters={"url": "https://example.com"},
                repository_root=temporary,
            )
            evidence = validate_evidence(run.evidence_path)
            mutations = []
            changed = copy.deepcopy(evidence); changed["integration_id"] = "other"; mutations.append(changed)
            changed = copy.deepcopy(evidence); changed["plan"]["parameters"]["url"] = "https://other"; mutations.append(changed)
            changed = copy.deepcopy(evidence); changed["host"]["hostname"] = "other"; mutations.append(changed)
            changed = copy.deepcopy(evidence); changed["safety_gate"]["plan_digest"] = "0" * 64; mutations.append(changed)
            for changed in mutations:
                with self.subTest(field=len(mutations)):
                    with self.assertRaises(LabValidationError):
                        validate_evidence(changed)

    def test_failed_outcome_cannot_be_marked_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            from ipad_agent.lab import run_fake_scenario
            run = run_fake_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"}, repository_root=temporary)
            evidence = validate_evidence(run.evidence_path)
            evidence["outcomes"][0]["ok"] = False
            evidence["complete"] = True
            with self.assertRaisesRegex(LabValidationError, "successful, certain outcomes"):
                validate_evidence(evidence)

    def test_physical_executor_injection_cannot_create_evidence(self):
        plan = plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"})
        with self.assertRaisesRegex(TypeError, "unexpected keyword argument 'executor'"):
            run_physical_scenario(
                plan, physical=True, authorization=authorization_for(plan),
                executor=EvidenceOnlyPhysicalExecutor(),
            )

    def test_simulation_cannot_publish_compatibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            from ipad_agent.lab import run_fake_scenario
            run = run_fake_scenario(
                SAFARI, "show-web-page", parameters={"url": "https://example.com"},
                executor=EvidenceOnlyPhysicalExecutor(), repository_root=temporary,
            )
            summary = compatibility_summary([run.evidence_path], generated_at="2026-08-29T00:00:00Z")
            self.assertEqual([], summary["source_evidence"])
            self.assertEqual([], summary["integrations"])
            changed = copy.deepcopy(summary)
            changed["redaction"]["excluded"].append("secret value")
            with self.assertRaisesRegex(LabValidationError, "allow-list contract"):
                validate_compatibility(changed)

    def test_selector_repeatability_requires_same_unique_context(self):
        first = {"children": [{"identifier": "target", "type": "Button", "label": "Go"}]}
        same = copy.deepcopy(first)
        moved = {"children": [{"wrapper": {"identifier": "target", "type": "Button", "label": "Go"}}]}
        duplicate = {"children": [first["children"][0], copy.deepcopy(first["children"][0])]}
        stable = next(item for item in selector_observations(first, same) if item["value"] == "target")
        changed = next(item for item in selector_observations(first, moved) if item["value"] == "target")
        repeated = next(item for item in selector_observations(first, duplicate) if item["value"] == "target")
        self.assertTrue(stable["unique"] and stable["repeatable"])
        self.assertFalse(changed["repeatable"])
        self.assertFalse(repeated["unique"])

    def test_repeated_physical_benchmark_requires_state_hooks_before_execution(self):
        plan = plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"})
        with self.assertRaisesRegex(PermissionError, "do not accept executor injection"):
            benchmark_scenario(
                plan, physical=True, authorization=authorization_for(plan),
                executor_factory=EvidenceOnlyPhysicalExecutor, warmups=1, runs=3,
            )

    def test_stateful_benchmark_resets_between_every_run_and_records_cleanup_failure(self):
        events = []
        with tempfile.TemporaryDirectory() as temporary:
            result = benchmark_scenario(
                MAPS, "search-place-direct", parameters={"encoded_query": "test"},
                warmups=1, runs=3, baseline_hook=lambda: events.append("baseline"),
                reset_hook=lambda: events.append("reset"),
                cleanup_hook=lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
                repository_root=temporary,
            )
            self.assertFalse(result["ok"])
            self.assertEqual(["baseline", "reset", "reset", "reset"], events)
            evidence = validate_evidence(result["evidence_path"])
            self.assertFalse(evidence["complete"])
            self.assertFalse(evidence["metrics"]["hooks"]["cleanup_ok"])

    def test_scaffold_and_generated_docs_do_not_hide_claims_or_behavior(self):
        draft = scaffold_integration("sample-app", name="Sample App", bundle_ids=["com.example.sample"])
        encoded = json.dumps(draft["manifest"])
        self.assertIn("UNVERIFIED", encoded)
        self.assertEqual("none verified; every UNVERIFIED marker is an authoring placeholder", draft["claims"])
        docs = generate_integration_docs(SAFARI)
        for exact in (
            "Aliases: `safari`, `apple safari`.",
            "Bundle IDs: `com.apple.mobilesafari`.",
            "value `{url}`",
            "Maximum attempts per step: `1`.",
            "Verification: `unverified`.",
            "Verified app versions: none.",
        ):
            self.assertIn(exact, docs)


if __name__ == "__main__":
    unittest.main()
