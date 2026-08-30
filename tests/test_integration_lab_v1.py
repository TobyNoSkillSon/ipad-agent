import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest

from ipad_agent.lab import (
    FakeExecutor,
    PhysicalExecutor,
    benchmark_scenario,
    compatibility_summary,
    discover_direct_routes,
    discover_selectors,
    generate_integration_docs,
    integration_docs,
    plan_scenario,
    run_fake_scenario,
    run_physical_scenario,
    scaffold_integration,
    validate_evidence,
    validate_manifest,
)
from ipad_agent.lab.validation import LabValidationError
from ipad_agent.operations import OperationPhase, RetryClass, SafetyClass

ROOT = Path(__file__).resolve().parents[1]
SAFARI = ROOT / "integrations" / "safari" / "integration.json"
MAPS = ROOT / "integrations" / "maps" / "integration.json"


class IntegrationLabV1Tests(unittest.TestCase):
    def test_static_cli_exposes_only_scaffold_validate_and_docs(self):
        completed = subprocess.run(
            [sys.executable, "-m", "ipad_agent.lab", "--help"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertIn("{scaffold,validate,docs}", completed.stdout)
        self.assertNotIn("physical", completed.stdout.split("positional arguments:")[-1])

    def test_scaffold_is_dry_run_by_default_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = scaffold_integration(
                "sample-app", name="Sample App", bundle_ids=["com.example.sample"],
                repository_root=temporary,
            )
            target = Path(result["target"])
            self.assertFalse(result["applied"])
            self.assertFalse(target.exists())
            applied = scaffold_integration(
                "sample-app", name="Sample App", bundle_ids=["com.example.sample"],
                repository_root=temporary, apply=True,
            )
            self.assertTrue(applied["changed"])
            self.assertEqual("sample-app", validate_manifest(target)["id"])
            with self.assertRaises(FileExistsError):
                scaffold_integration(
                    "sample-app", name="Sample App", bundle_ids=["com.example.sample"],
                    repository_root=temporary, apply=True,
                )

    def test_strict_validation_rejects_duplicate_keys_and_capability_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "integration.json"
            text = SAFARI.read_text(encoding="utf-8").replace('"version": 1,', '"version": 1,\n  "version": 1,')
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(LabValidationError, "duplicate JSON key"):
                validate_manifest(path)
            value = json.loads(SAFARI.read_text(encoding="utf-8"))
            value["scenarios"]["show-web-page"]["capabilities"] = ["launch"]
            with self.assertRaisesRegex(LabValidationError, "capability set"):
                validate_manifest(value)

    def test_plan_resolves_parameters_and_uses_operation_retry_contracts(self):
        plan = plan_scenario(MAPS, "find-place-ui-fallback", parameters={"query": "Warsaw"})
        self.assertEqual(["activate", "clear-type", "tap"], [step.instruction["operation"] for step in plan.steps])
        self.assertEqual("Warsaw", plan.steps[1].instruction["value"])
        self.assertEqual(SafetyClass.NAVIGATE, plan.steps[0].operation.safety_class)
        self.assertEqual(RetryClass.SAFE_REPEAT, plan.steps[0].operation.retry_class)
        self.assertEqual(SafetyClass.TRANSIENT, plan.steps[1].operation.safety_class)
        self.assertEqual(RetryClass.INSPECT_THEN_DECIDE, plan.steps[1].operation.retry_class)
        with self.assertRaisesRegex(ValueError, "missing scenario parameter"):
            plan_scenario(MAPS, "find-place-ui-fallback")
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            plan_scenario(MAPS, "find-place-ui-fallback", parameters={"query": "x"}, safety_ceiling=SafetyClass.PERSISTENT)

    def test_fake_run_records_private_schema_evidence_and_physical_is_gated(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = run_fake_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"}, repository_root=temporary)
            self.assertTrue(run.ok)
            self.assertIsNotNone(run.evidence_path)
            self.assertIn(str(Path(temporary) / ".runtime" / "lab"), str(run.evidence_path))
            evidence = validate_evidence(run.evidence_path)
            self.assertEqual("fake", evidence["mode"])
            self.assertFalse(evidence["redaction"]["commit"])
            self.assertEqual(0o600, run.evidence_path.stat().st_mode & 0o777)
            with self.assertRaisesRegex(PermissionError, "physical=True"):
                run_physical_scenario(plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"}))
            with self.assertRaisesRegex(PermissionError, "physical=True"):
                PhysicalExecutor()

    def test_static_discovery_prefers_routes_and_builds_selector_candidates(self):
        routes = discover_direct_routes(SAFARI)
        self.assertEqual(["activate", "open-url"], [item["operation"] for item in routes])
        candidates = discover_selectors({"children": [{"identifier": "search-field", "label": "Search"}]})
        self.assertIn({"using": "accessibility id", "value": "search-field"}, candidates)
        self.assertIn({"using": "-ios predicate string", "value": "label == 'Search'"}, candidates)

    def test_benchmark_has_warmups_metrics_and_private_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = benchmark_scenario(
                SAFARI, "show-web-page", parameters={"url": "https://example.com"},
                warmups=1, runs=3, baseline_hook=lambda: None,
                reset_hook=lambda: None, cleanup_hook=lambda: None, repository_root=temporary,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(1, result["metrics"]["warmups"])
            self.assertEqual(3, result["metrics"]["runs"])
            self.assertEqual(3, result["metrics"]["successful_runs"])
            evidence = validate_evidence(result["evidence_path"])
            self.assertEqual("benchmark", evidence["mode"])

    def test_compatibility_summary_is_allow_listed_and_docs_check_detects_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = run_fake_scenario(SAFARI, "show-web-page", parameters={"url": "https://secret.example/path"}, repository_root=temporary)
            summary = compatibility_summary([run.evidence_path], generated_at="2026-03-10T00:00:00Z")
            encoded = json.dumps(summary)
            self.assertNotIn("secret.example", encoded)
            self.assertNotIn(platform.node(), encoded)
            self.assertFalse(summary["redaction"]["raw_evidence_committed"])
            output = Path(temporary) / "safari.md"
            preview = integration_docs(SAFARI, output=output)
            self.assertFalse(output.exists())
            self.assertIn("Safari integration", preview["preview"])
            integration_docs(SAFARI, output=output, apply=True)
            self.assertTrue(integration_docs(SAFARI, output=output, check=True)["ok"])
            output.write_text("drift", encoding="utf-8")
            self.assertFalse(integration_docs(SAFARI, output=output, check=True)["ok"])


if __name__ == "__main__":
    unittest.main()
