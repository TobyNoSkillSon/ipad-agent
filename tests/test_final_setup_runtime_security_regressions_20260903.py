import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ipad_agent import doctor, setup, wda
from ipad_agent.config import Config
from ipad_agent.runtime import Daemon, Runtime, RuntimeTeardownError


class _FailingContext:
    def __init__(self):
        self.exits = 0

    def __exit__(self, *_args):
        self.exits += 1
        raise wda.XCTestControlError(
            "owned WDA cleanup could not be proven",
            code="wda_cleanup_incomplete",
            uncertain=True,
            dispatched=True,
        )


class FinalSetupRuntimeSecurityRegressions20260903Tests(unittest.TestCase):
    def _rich_doctor(self):
        device_id = "12345678-" + "1234567890ABCDEF"
        device_udid = "A" * 40
        team_id = "QWERTY" + "1234"
        private_home = "/" + "Users/private"
        return {
            "schema": "ipad-agent.doctor/v2",
            "state": "needs_agent_action",
            "ready": False,
            "exit_code": 20,
            "selected": {
                "device_identifier": device_id,
                "device_udid": device_udid,
                "team_id": team_id,
                "wda_bundle_id": "io.private.wda.runner",
                "wda_fingerprint": "b" * 24,
                "xctestrun": private_home + "/Library/WDA.xctestrun",
                "wda_artifact_receipt": private_home + "/.runtime/receipt.json",
            },
            "checks": [
                {
                    "id": "device.paired", "status": "pass", "stage": "device",
                    "message": "One selected paired physical iPad is available",
                    "evidence": {"identifier": device_id, "udid": device_udid, "model": "iPad", "os": "18.0"},
                    "human_action": None, "remediation": None,
                },
                {
                    "id": "automation.wda_build", "status": "fail", "stage": "wda",
                    "message": "No valid build-for-testing artifact exists for the current fingerprint",
                    "evidence": {"error": f"Profile Private Test Profile at {private_home}/WDA for {team_id} and io.private.wda.runner"},
                    "human_action": None,
                    "remediation": "Run: python3 -m ipad_agent setup --phase wda --apply --json",
                },
            ],
            "next": ["automation.wda_build"],
        }

    def test_public_doctor_json_keeps_logical_evidence_without_private_identifiers(self):
        rich = self._rich_doctor()
        with patch("ipad_agent.doctor._run_doctor", return_value=rich):
            report = doctor.run_doctor(Config())
        rendered = json.dumps(report, sort_keys=True)
        for secret in (
            "12345678-" + "1234567890ABCDEF", "A" * 40, "QWERTY" + "1234",
            "io.private.wda.runner", "b" * 24, "/" + "Users/private", "Private Test Profile",
        ):
            self.assertNotIn(secret, rendered)
        self.assertEqual({"device": True, "signing": True, "wda_artifact": True, "verified": False}, report["selected"])
        self.assertEqual({"model": "iPad", "os": "18.0"}, report["checks"][0]["evidence"])
        self.assertEqual("automation.wda_build", report["next"][0])
        self.assertIs(rich, doctor.internal_report(report))

    def test_public_setup_json_redacts_operations_changes_and_human_gate_error(self):
        rich = self._rich_doctor()
        result = setup._setup_report(
            True,
            "wda",
            ["/" + "Users/private/.runtime/derived-data/" + "b" * 24],
            [{
                "phase": "wda", "ok": False, "changed": False,
                "command": ["xcodebuild", "-destination", "id=" + "A" * 40],
                "artifact": {"team_id": "QWERTY" + "1234", "profile_name": "Private Test Profile"},
            }],
            rich,
            {"code": "provisioning_required", "message": "No profile Private Test Profile for " + "QWERTY" + "1234 at /" + "Users/private"},
        )
        rendered = json.dumps(result, sort_keys=True)
        for secret in ("A" * 40, "QWERTY" + "1234", "/" + "Users/private", "Private Test Profile"):
            self.assertNotIn(secret, rendered)
        self.assertEqual("action_required", result["state"])
        self.assertIn("will not update provisioning", result["error"]["message"])
        self.assertEqual({"phase": "wda", "ok": False, "changed": False}, result["operations"][0])

    def test_failed_runtime_teardown_retains_state_and_is_never_retried_or_clean(self):
        runtime = Runtime(config=Config(), registry=Mock())
        context = _FailingContext()
        session = Mock()
        runtime._session_context = context
        runtime.session = session
        runtime._last_used = 0.0

        with self.assertRaises(RuntimeTeardownError):
            runtime.teardown()
        self.assertIs(session, runtime.session)
        self.assertIs(context, runtime._session_context)
        self.assertTrue(runtime.hot)

        first = runtime.status()
        second = runtime.status()
        self.assertEqual(1, context.exits)
        self.assertEqual("failed", first["teardown"]["state"])
        self.assertTrue(first["teardown"]["recoverable"])
        self.assertTrue(first["session"])
        self.assertEqual(first["teardown"], second["teardown"])

        with self.assertRaises(RuntimeTeardownError):
            runtime.execute({"op": "x"})
        self.assertEqual(1, context.exits)

    def test_doctor_reads_npm_metadata_without_executing_appium(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            appium = root / "node" / "node_modules" / ".bin" / "appium"
            appium.parent.mkdir(parents=True)
            appium_package = appium.parents[1] / "appium" / "package.json"
            appium_package.parent.mkdir()
            appium_package.write_text(json.dumps({"name": "appium", "version": doctor.APPIUM_VERSION}))
            appium_home = root / "appium-home"
            driver_package = appium_home / "node_modules" / "appium-xcuitest-driver" / "package.json"
            driver_package.parent.mkdir(parents=True)
            driver_package.write_text(json.dumps({
                "name": "appium-xcuitest-driver",
                "version": doctor.XCUITEST_VERSION,
            }))
            checks = []
            with patch.object(doctor, "APPIUM", appium), \
                 patch.object(doctor, "APPIUM_HOME", appium_home), \
                 patch.object(doctor, "require_runtime_path", side_effect=lambda value: Path(value)), \
                 patch.object(doctor, "_run", side_effect=AssertionError("package code executed")):
                result = doctor._automation_checks(checks, True)
        self.assertEqual((True, True), result)
        self.assertEqual(["pass", "pass"], [item.status for item in checks])

    def test_daemon_shutdown_returns_failure_instead_of_swallowing_teardown(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch("ipad_agent.runtime.require_runtime_path", side_effect=lambda value: Path(value)):
            daemon = Daemon(Path(temporary) / "daemon.sock", idle_ttl=10, nonce="f" * 64)
            context = _FailingContext()
            daemon.runtime._session_context = context
            daemon.runtime.session = Mock()
            daemon.runtime._last_used = 0.0
            daemon.stop = True
            listener = Mock()
            with patch.object(daemon, "_bind", return_value=listener):
                with self.assertRaisesRegex(RuntimeError, "shutdown failed"):
                    daemon.serve()
        self.assertEqual(1, context.exits)


if __name__ == "__main__":
    unittest.main()
