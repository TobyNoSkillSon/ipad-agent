import hashlib
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

from ipad_agent import doctor, setup, wda
from ipad_agent.versions import DOCTOR_SCHEMA


class AutomationSetupBlockers20260828Tests(unittest.TestCase):
    def test_certificate_display_suffix_is_not_used_as_development_team(self):
        identities = doctor._apple_development_identities(
            '  1) ' + 'A' * 40 + ' "Apple Development: user@example.test (WRONG12345)"'
        )
        self.assertEqual([{"sha1": "A" * 40}], identities)

    def test_xcode_preference_teams_are_real_and_deduplicated(self):
        value = {"IDEProvisioningTeamByIdentifier": {
            "account": [
                {"teamID": "ABCDE12345"},
                {"teamID": "ABCDE12345"},
            ]
        }}
        with patch("ipad_agent.doctor._run", return_value=(0, plistlib.dumps(value).decode(), "")):
            self.assertEqual({"ABCDE12345": ["xcode_preferences"]}, doctor._xcode_provisioning_teams())

    def test_provisioning_update_and_registration_flags_are_never_used(self):
        selection = wda.WDASelection(
            "device", "udid", "18.0", "ABCDE12345", "io.example.wda",
            "/driver/WDA.xcodeproj", "digest", "Xcode 16", "fingerprint",
        )
        dry = wda.build_for_testing(selection, apply=False)
        self.assertNotIn("-allowProvisioningUpdates", dry["command"])
        self.assertNotIn("-allowProvisioningDeviceRegistration", dry["command"])
        commands = []
        def run(command, *, timeout):
            commands.append(command)
            return 65, "", "No profiles for the runner were found"
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(wda, "DERIVED_DATA_ROOT", Path(temporary)), \
             patch("ipad_agent.wda.validate_artifact", side_effect=wda.XCTestControlError("missing")), \
             patch("ipad_agent.wda.private_mkdir"), \
             patch("ipad_agent.wda._run_process", side_effect=run):
            with self.assertRaises(wda.XCTestControlError) as caught:
                wda.build_for_testing(selection, apply=True)
        self.assertEqual("provisioning_required", caught.exception.code)
        self.assertNotIn("-allowProvisioningUpdates", commands[0])
        self.assertNotIn("-allowProvisioningDeviceRegistration", commands[0])
        self.assertEqual(1, len(commands))

    def test_unlock_gate_suppresses_impossible_agent_build_action(self):
        report = {
            "schema": DOCTOR_SCHEMA, "state": "needs_agent_action", "ready": False,
            "exit_code": 20, "selected": {}, "next": [],
            "checks": [
                {"id": "device.unlocked", "status": "action_required", "human_action": "Unlock it", "remediation": None},
                {"id": "automation.wda_source", "status": "fail", "human_action": None, "remediation": "Run: impossible-now"},
            ],
        }
        result = setup._setup_report(False, "wda", [], [{"phase": "wda", "blocked_by": ["device.unlocked", "automation.wda_source"]}], report, None)
        self.assertEqual("action_required", result["state"])
        self.assertEqual(["human_security_action"], [item["kind"] for item in result["actions"]])

    def test_human_signing_failure_is_structural_action_required(self):
        report = {"schema": DOCTOR_SCHEMA, "state": "ready", "ready": True, "exit_code": 0, "selected": {}, "checks": [], "next": []}
        error = setup._classify_transition_error(RuntimeError("No provisioning profile for runner"), "No provisioning profile for runner")
        result = setup._setup_report(True, "wda", [], [], report, error)
        self.assertEqual("provisioning_required", result["error"]["code"])
        self.assertEqual("action_required", result["state"])
        self.assertEqual(10, result["exit_code"])

    def test_invalid_phase_report_matches_setup_schema_phase_contract(self):
        result = setup.run_setup(apply=False, phase="not-a-phase")
        schema = json.loads((Path(__file__).parents[1] / "schemas" / "setup-v2.json").read_text())
        self.assertEqual("invalid_phase", result["error"]["code"])
        self.assertEqual("string", schema["properties"]["phase"]["type"])
        self.assertIsInstance(result["phase"], str)

    def test_owned_artifact_fields_are_persisted_for_normal_runtime(self):
        selection = wda.WDASelection("device", "udid", "18.0", "ABCDE12345", "io.example.wda", "/driver/WDA.xcodeproj", "digest", "Xcode 16", "fingerprint")
        artifact = {
            "xctestrun": "/owned/Build/Products/WDA.xctestrun",
            "runtime": {
                "team_id": "ABCDE12345", "wda_bundle_id": "io.example.wda",
                "xctestrun": "/owned/Build/Products/WDA.xctestrun", "wda_fingerprint": "fingerprint",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            path.write_text(setup._default_config())
            with patch.object(setup, "DEFAULT_CONFIG_PATH", path), patch("ipad_agent.setup.private_write_text", side_effect=lambda target, value: Path(target).write_text(value)):
                result = setup._persist_runtime_wda_config(selection, artifact)
            rendered = path.read_text()
        self.assertTrue(result["changed"])
        self.assertIn('team_id = "ABCDE12345"', rendered)
        self.assertIn('wda_bundle_id = "io.example.wda"', rendered)
        self.assertIn('xctestrun = "/owned/Build/Products/WDA.xctestrun"', rendered)
        self.assertEqual("fingerprint", result["wda_fingerprint"])

    def test_cross_process_cleanup_requires_pid_start_nonce_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "appium-owner.json"
            receipt = {
                "schema": "ipad-agent.appium-owner/v1", "owner": "ipad-agent", "pid": 4321,
                "started_at": "2026-01-01T00:00:00Z", "process_start": "start tuple",
                "nonce": "a" * 32, "executable": "/owned/appium", "server_url": "http://127.0.0.1:4723",
                "command": ["/owned/appium"],
            }
            receipt_path.write_text(json.dumps(receipt))
            run_values = [(0, "/owned/appium IPAD_AGENT_OWNER_NONCE=" + "a" * 32, "")]
            kill_values = [None, ProcessLookupError()]
            with patch.object(wda, "APPIUM_OWNER_RECEIPT", receipt_path), patch.object(wda, "private_read_text", side_effect=lambda value: Path(value).read_text()), patch.object(wda, "_SERVER", None), patch("ipad_agent.wda._process_start", return_value="start tuple"), patch("ipad_agent.wda._run_process", side_effect=run_values), patch("ipad_agent.wda._terminate_wda_xcodebuild"), patch("ipad_agent.wda.os.kill", side_effect=kill_values):
                result = wda.stop_owned_appium_server(timeout=0.1)
            self.assertTrue(result["stopped"])
            self.assertFalse(receipt_path.exists())

    def test_mutating_transport_failure_has_dispatched_uncertain_metadata(self):
        opener = Mock()
        opener.open.side_effect = TimeoutError("lost")
        with patch("ipad_agent.wda.urllib.request.build_opener", return_value=opener) as build:
            with self.assertRaises(wda.XCTestControlError) as caught:
                wda._http_json("POST", "http://127.0.0.1/session", {}, 1)
        handlers = build.call_args.args
        proxy = next(item for item in handlers if isinstance(item, wda.urllib.request.ProxyHandler))
        self.assertEqual({}, proxy.proxies)
        self.assertTrue(any(isinstance(item, wda._RejectRedirects) for item in handlers))
        self.assertEqual({"dispatched": True, "uncertain": True}, caught.exception.transport)
        self.assertEqual("wda_transport_error", caught.exception.code)

    def test_source_digest_covers_source_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "WebDriverAgent.xcodeproj"
            project.mkdir()
            (project / "project.pbxproj").write_text("project")
            source = root / "WebDriverAgentRunner.m"
            source.write_text("one")
            first = wda._source_digest(project)
            source.write_text("two")
            second = wda._source_digest(project)
        self.assertNotEqual(first, second)

    def test_verification_receipt_requires_current_unexpired_tuple(self):
        selection = wda.WDASelection("device", "udid", "18.0", "ABCDE12345", "io.example.wda", "/driver/WDA.xcodeproj", "digest", "Xcode 16", "fingerprint")
        with tempfile.TemporaryDirectory() as temporary:
            xctestrun = Path(temporary) / "wda.xctestrun"
            xctestrun.write_bytes(b"plist")
            artifact = {"xctestrun": str(xctestrun)}
            receipt = {
                "schema": "ipad-agent.wda-verification/v2", "owner": "ipad-agent",
                "fingerprint": "fingerprint", "device_udid": "udid", "team_id": "ABCDE12345",
                "bundle_id": "io.example.wda", "verified_at": "2000-01-01T00:00:00Z",
                "expires_at": "2000-01-08T00:00:00Z",
                "verification_tuple": wda._verification_tuple(selection, artifact),
            }
            path = Path(temporary) / "receipt.json"
            path.write_text(json.dumps(receipt))
            with patch("ipad_agent.wda.verification_path", return_value=path), patch("ipad_agent.wda.validate_artifact", return_value=artifact):
                self.assertFalse(wda.verified(selection))


if __name__ == "__main__":
    unittest.main()
