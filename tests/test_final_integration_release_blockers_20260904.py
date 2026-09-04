import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from ipad_agent.coredevice import UnlockDispatchResult
from ipad_agent.lab import (
    PhysicalAuthorization, completion_report, plan_scenario, run_fake_scenario,
)
from ipad_agent.lab.runner import PhysicalExecutor, _run
from ipad_agent.registry import load_registry
from tests.lab_fixture import isolate_authorization_receipts, lab_fixture_manifest

ROOT = Path(__file__).resolve().parents[1]
SAFARI = ROOT / "integrations" / "safari" / "integration.json"
MAPS = ROOT / "integrations" / "apple_maps" / "integration.json"
LAB_FIXTURE = lab_fixture_manifest()
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
    def setUp(self) -> None:
        isolate_authorization_receipts(self)

    def test_locked_coredevice_result_is_terminal_before_url_or_wda(self):
        plan = plan_scenario(SAFARI, "open-url-direct", parameters={"url": "https://example.com"})
        executor = PhysicalExecutor(physical=True, authorization=authorization(plan), plan=plan)
        locked = UnlockDispatchResult("locked", None)
        environment = {
            "source": "CoreDevice", "capture": "device info details",
            "coredevice_identifier": "device", "device_class": "iPad",
            "os_version": "18.1", "locale": "en-US",
        }
        with patch("ipad_agent.lab.runner.open_ipad_when_unlocked", return_value=locked) as launch, patch(
            "ipad_agent.lab.runner.capture_coredevice_environment", return_value=environment
        ), patch.object(executor, "_wda", side_effect=AssertionError("WDA must not start")):
            run = _run(
                plan, executor, mode="physical", record=False, repository_root=ROOT,
                authorization=executor.authorization,
            )
        self.assertFalse(run.ok)
        self.assertEqual(1, launch.call_count)
        self.assertEqual("device_locked", run.batch.results[0].error.code)
        self.assertEqual(1, len(run.batch.results))

    def test_authorization_is_reverified_after_constructor_and_before_dispatch(self):
        plan = plan_scenario(SAFARI, "activate-direct")
        grant = authorization(plan, expires=timedelta(milliseconds=80))
        executor = PhysicalExecutor(physical=True, authorization=grant, plan=plan)
        time.sleep(0.12)
        with patch("ipad_agent.lab.runner.open_ipad_when_unlocked") as launch:
            with self.assertRaisesRegex(PermissionError, "expired"):
                executor.execute(plan.steps[0], plan.bundle_id)
        launch.assert_not_called()

    def test_confirmation_requirements_are_exact_authorization_data(self):
        manifest = json.loads(SAFARI.read_text(encoding="utf-8"))
        required = "confirm one explicit transient route"
        manifest["safety"]["requires_confirmation"] = [required]
        plan = plan_scenario(manifest, "activate-direct")
        with self.assertRaisesRegex(PermissionError, "confirmations"):
            PhysicalExecutor(physical=True, authorization=authorization(plan), plan=plan)
        exact = authorization(plan, confirmations=(required,))
        executor = PhysicalExecutor(physical=True, authorization=exact, plan=plan)
        self.assertEqual([required], executor.authorization.to_dict()["confirmations"])

    def test_every_open_url_route_has_strict_data_first_policy(self):
        legacy_cases = (
            (SAFARI, "open-url-direct", "url", "https://example.com"),
            (ROOT / "integrations" / "brave" / "integration.json", "open-url-direct", "url", "https://example.com"),
        )
        for manifest, scenario, key, value in legacy_cases:
            with self.subTest(manifest=manifest.parent.name):
                plan = plan_scenario(manifest, scenario, parameters={key: value})
                url_steps = [step for step in plan.steps if step.instruction["operation"] == "open-url"]
                self.assertTrue(url_steps)
                self.assertTrue(all(
                    step.instruction["allowed_schemes"] == ["http", "https"]
                    for step in url_steps
                ))

        fixture_plan = plan_scenario(
            LAB_FIXTURE, "search-direct", parameters={"query": "test"},
        )
        fixture_step = fixture_plan.steps[0]
        self.assertEqual("open-url", fixture_step.instruction["operation"])
        self.assertTrue(
            fixture_step.instruction["validated_route"]["url"].startswith(
                "https://links.example.org/search?"
            )
        )
        self.assertEqual(
            fixture_step.instruction["validated_route"]["policy_sha256"],
            fixture_plan.metadata["url_policy_binding"]["sha256"],
        )

        maps_registry = load_registry()
        maps_route = maps_registry.resolve_url_route("maps", "search", ("test",), {})
        maps_integration = maps_registry.resolve("maps")
        self.assertTrue(maps_route.url.startswith("https://maps.apple.com/search?"))
        self.assertEqual(maps_integration.policy_sha256, maps_route.policy_sha256)
        self.assertEqual("com.apple.Maps", maps_route.bundle_id)

        for bad in ("file:///tmp/a", "https://user:secret@example.com", "https:///x", "https://bad host", "https://x/%zz"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                plan_scenario(SAFARI, "open-url-direct", parameters={"url": bad})

    def test_completion_rejects_foreign_and_stale_manifest_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = run_fake_scenario(
                SAFARI, "activate-direct", repository_root=temporary,
            )
            foreign = completion_report(MAPS, evidence=[run.evidence_path], require_physical=False)
            valid = next(item for item in foreign["checks"] if item["id"] == "evidence.valid")
            self.assertFalse(valid["passed"])
            manifest = json.loads(SAFARI.read_text(encoding="utf-8"))
            manifest["privacy"]["notes"] += " Current manifest revision."
            stale = completion_report(manifest, evidence=[run.evidence_path], require_physical=False)
            valid = next(item for item in stale["checks"] if item["id"] == "evidence.valid")
            self.assertFalse(valid["passed"])

    def test_release_rejects_malformed_route_status_and_unscoped_promotions(self):
        relative = "integrations/preview/route-compatibility.json"
        actual = release_check._strict_json
        base = actual(ROOT / relative)
        candidates = {
            path.relative_to(ROOT).as_posix()
            for path in release_check.release_paths(ROOT)
        }
        mutations = []
        wrong_status = copy.deepcopy(base)
        next(row for row in wrong_status["commands"] if row["command"] == "show")["production"] = "proven"
        mutations.append((wrong_status, "production status is invalid"))
        no_visible_proof = copy.deepcopy(base)
        show = next(row for row in no_visible_proof["commands"] if row["command"] == "show")
        show["evidence"] = [item for item in show["evidence"] if item.get("kind") == "transport-contract"]
        mutations.append((no_visible_proof, "lacks visible evidence"))
        nested_private = copy.deepcopy(base)
        show = next(row for row in nested_private["commands"] if row["command"] == "show")
        show["evidence"][0]["private"] = {"url": "private", "path": "private"}
        mutations.append((nested_private, "evidence kind or fields are not allowlisted"))
        top_extra = copy.deepcopy(base)
        top_extra["private_payload"] = {"path": "private"}
        mutations.append((top_extra, "document fields are invalid"))
        row_extra = copy.deepcopy(base)
        row_extra["commands"][0]["private_payload"] = {"path": "private"}
        mutations.append((row_extra, "row 0 fields are invalid"))
        wrong_schema = copy.deepcopy(base)
        wrong_schema["schema"] = "ipad-agent.brave-route-compatibility/v1"
        mutations.append((wrong_schema, "document fields are invalid"))
        bad_exclusions = copy.deepcopy(base)
        bad_exclusions["excluded_routes"] = {"private_payload": True}
        mutations.append((bad_exclusions, "exclusions are invalid"))
        arbitrary_verdict = copy.deepcopy(base)
        visual = next(
            item for item in next(row for row in arbitrary_verdict["commands"] if row["command"] == "show")["evidence"]
            if item.get("kind") == "user-visual-pass"
        )
        visual["result"] = "arbitrary-private-verdict"
        mutations.append((arbitrary_verdict, "evidence result is invalid"))
        for value, expected in mutations:
            with self.subTest(expected=expected):
                def altered(path: Path, *, replacement=value):
                    if path == ROOT / relative:
                        return replacement
                    return actual(path)
                with patch.object(release_check, "_strict_json", side_effect=altered):
                    issues = release_check.validate_route_compatibility_sidecars(ROOT, candidates)
                self.assertTrue(any(expected in issue for issue in issues))

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
