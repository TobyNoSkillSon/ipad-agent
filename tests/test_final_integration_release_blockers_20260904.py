import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from ipad_agent.coredevice import LaunchResult
from ipad_agent.lab import (
    PhysicalAuthorization, completion_report, plan_scenario, run_fake_scenario,
)
from ipad_agent.lab.runner import PhysicalExecutor, _run

ROOT = Path(__file__).resolve().parents[1]
SAFARI = ROOT / "integrations" / "safari" / "integration.json"
MAPS = ROOT / "integrations" / "maps" / "integration.json"
SPEC = importlib.util.spec_from_file_location("release_check_final", ROOT / "scripts" / "release_check.py")
assert SPEC and SPEC.loader
release_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_check)


def authorization(plan, *, expires=timedelta(minutes=5), confirmations=()):
    now = datetime.now(timezone.utc)
    return PhysicalAuthorization.for_plan(
        plan, actor="test", request="exact bounded plan", authorized_at=now.isoformat(),
        expires_at=(now + expires).isoformat(), confirmations=confirmations,
    )


class FinalIntegrationReleaseBlockers20260904Tests(unittest.TestCase):
    def test_locked_coredevice_result_is_terminal_before_url_or_wda(self):
        plan = plan_scenario(SAFARI, "show-web-page", parameters={"url": "https://example.com"})
        executor = PhysicalExecutor(physical=True, authorization=authorization(plan), plan=plan)
        locked = LaunchResult(plan.bundle_id, "device", 0.01, None, True)
        environment = {
            "source": "CoreDevice", "capture": "device info details",
            "coredevice_identifier": "device", "device_class": "iPad",
            "os_version": "18.1", "locale": "en-US",
        }
        with patch("ipad_agent.lab.runner.open_ipad", return_value=locked) as launch, patch(
            "ipad_agent.lab.runner.capture_coredevice_environment", return_value=environment
        ), patch.object(executor, "_wda", side_effect=AssertionError("WDA must not start")):
            run = _run(
                plan, executor, mode="physical", record=False, repository_root=ROOT,
                authorization=executor.authorization,
            )
        self.assertFalse(run.ok)
        self.assertEqual(1, launch.call_count)
        self.assertEqual("device_locked", run.batch.results[0].error.code)
        self.assertEqual("not_sent", run.batch.results[1].phase.value)

    def test_authorization_is_reverified_after_constructor_and_before_dispatch(self):
        plan = plan_scenario(SAFARI, "foreground-only")
        grant = authorization(plan, expires=timedelta(milliseconds=80))
        executor = PhysicalExecutor(physical=True, authorization=grant, plan=plan)
        time.sleep(0.12)
        with patch("ipad_agent.lab.runner.open_ipad") as launch:
            with self.assertRaisesRegex(PermissionError, "expired"):
                executor.execute(plan.steps[0], plan.bundle_id)
        launch.assert_not_called()

    def test_confirmation_requirements_are_exact_authorization_data(self):
        manifest = json.loads(SAFARI.read_text(encoding="utf-8"))
        required = "confirm one explicit transient route"
        manifest["safety"]["requires_confirmation"] = [required]
        plan = plan_scenario(manifest, "foreground-only")
        with self.assertRaisesRegex(PermissionError, "confirmations"):
            PhysicalExecutor(physical=True, authorization=authorization(plan), plan=plan)
        exact = authorization(plan, confirmations=(required,))
        executor = PhysicalExecutor(physical=True, authorization=exact, plan=plan)
        self.assertEqual([required], executor.authorization.to_dict()["confirmations"])

    def test_every_open_url_route_has_strict_data_first_policy(self):
        cases = (
            (SAFARI, "show-web-page", "url", "https://example.com", ["http", "https"]),
            (MAPS, "search-place-direct", "encoded_query", "test", ["maps"]),
            (ROOT / "addons" / "brave" / "integration.json", "open-task-url", "url", "https://example.com", ["http", "https"]),
        )
        for manifest, scenario, key, value, schemes in cases:
            with self.subTest(manifest=manifest.parent.name):
                plan = plan_scenario(manifest, scenario, parameters={key: value})
                url_steps = [step for step in plan.steps if step.instruction["operation"] == "open-url"]
                self.assertTrue(url_steps)
                self.assertTrue(all(step.instruction["allowed_schemes"] == schemes for step in url_steps))
        for bad in ("file:///tmp/a", "https://user:secret@example.com", "https:///x", "https://bad host", "https://x/%zz"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                plan_scenario(SAFARI, "show-web-page", parameters={"url": bad})

    def test_completion_rejects_foreign_and_stale_manifest_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = run_fake_scenario(
                SAFARI, "foreground-only", repository_root=temporary,
            )
            foreign = completion_report(MAPS, evidence=[run.evidence_path], require_physical=False)
            valid = next(item for item in foreign["checks"] if item["id"] == "evidence.valid")
            self.assertFalse(valid["passed"])
            manifest = json.loads(SAFARI.read_text(encoding="utf-8"))
            manifest["privacy"]["notes"] += " Current manifest revision."
            stale = completion_report(manifest, evidence=[run.evidence_path], require_physical=False)
            valid = next(item for item in stale["checks"] if item["id"] == "evidence.valid")
            self.assertFalse(valid["passed"])

    def test_release_semantics_reject_fabricated_public_physical_or_cleanup_claims(self):
        compatibility = json.loads((ROOT / "compatibility-v1.json").read_text(encoding="utf-8"))
        report = json.loads((ROOT / "lab-report-v1.json").read_text(encoding="utf-8"))
        report["checks"] = [{"id": "scenarios.physical", "passed": True, "detail": "fabricated"}]
        report["complete"] = True
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "compatibility-v1.json").write_text(json.dumps(compatibility), encoding="utf-8")
            (root / "lab-report-v1.json").write_text(json.dumps(report), encoding="utf-8")
            candidates = {
                "compatibility-v1.json", "lab-report-v1.json",
                "schemas/compatibility-v1.json", "schemas/lab-report-v1.json",
            }
            issues = release_check.validate_public_lab_claims(root, candidates)
        self.assertTrue(issues)
        self.assertRegex(issues[0], "complete|physical|evidence")


if __name__ == "__main__":
    unittest.main()
