import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from ipad_agent import cleanup, wda
from ipad_agent.bootstrap import bootstrap_automation
from ipad_agent.config import Config
from ipad_agent.doctor import run_doctor
from ipad_agent.setup import run_setup
from ipad_agent.versions import DOCTOR_SCHEMA, SETUP_SCHEMA, WDA_ARTIFACT_SCHEMA


class HostSetupWDAStateMachineV2Tests(unittest.TestCase):
    def test_bootstrap_without_compatible_node_is_a_stable_exact_remediation(self):
        with patch("ipad_agent.bootstrap.resolve_node_toolchain", return_value={"compatible": False, "node": None, "npm": None}):
            result = bootstrap_automation(apply=True)
        self.assertFalse(result["ok"])
        self.assertEqual("compatible_node_unavailable", result["error"])
        self.assertIn("python", result["remediation"])
        self.assertIn("setup --phase host --apply --json", result["remediation"])

    def test_doctor_internal_failure_is_json_state_not_exception(self):
        with patch("ipad_agent.doctor.load_config", side_effect=ValueError("bad local config")):
            result = run_doctor()
        self.assertEqual(DOCTOR_SCHEMA, result["schema"])
        self.assertEqual("needs_agent_action", result["state"])
        self.assertEqual("doctor.internal", result["checks"][0]["id"])

    def test_setup_dry_run_never_calls_mutating_bootstrap(self):
        fake_doctor = {"schema": DOCTOR_SCHEMA, "state": "needs_agent_action", "ready": False, "exit_code": 20, "selected": {}, "checks": [], "next": []}
        with patch("ipad_agent.setup.run_doctor", return_value=fake_doctor), patch("ipad_agent.setup.bootstrap_automation", return_value={"ok": True, "changed": [], "planned": []}) as bootstrap:
            result = run_setup(apply=False, phase="host")
        bootstrap.assert_called_once_with(apply=False)
        self.assertEqual(SETUP_SCHEMA, result["schema"])
        self.assertFalse(result["applied"])
        self.assertEqual([], result["changed"])

    def test_build_for_testing_dry_run_is_fingerprinted_and_pure(self):
        selection = wda.WDASelection("device", "udid", "18.0", "EXAMPLE123", "io.example.wda", "/driver/WDA.xcodeproj", "digest", "Xcode 16", "abc123")
        with tempfile.TemporaryDirectory() as temporary, patch.object(wda, "DERIVED_DATA_ROOT", Path(temporary) / "derived"):
            result = wda.build_for_testing(selection, apply=False)
            self.assertFalse((Path(temporary) / "derived").exists())
        self.assertEqual("abc123", result["fingerprint"])
        self.assertIn("build-for-testing", result["command"])
        self.assertIn("DEVELOPMENT_TEAM=EXAMPLE123", result["command"])
        self.assertIn("-destination", result["command"])

    def test_cleanup_refuses_unowned_and_removes_only_owned_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "derived-data"; root.mkdir()
            owned = root / "owned"; owned.mkdir()
            (owned / wda.ARTIFACT_FILE).write_text(json.dumps({"schema": WDA_ARTIFACT_SCHEMA, "owner": wda.OWNER, "fingerprint": "owned"}))
            foreign = root / "foreign"; foreign.mkdir()
            (foreign / wda.ARTIFACT_FILE).write_text("{}")
            state = Path(temporary) / "state"; state.mkdir()
            with patch.object(wda, "DERIVED_DATA_ROOT", root), patch("ipad_agent.cleanup.require_runtime_path", side_effect=lambda value: Path(value)), patch.object(wda, "verification_path", side_effect=lambda fingerprint: state / f"{fingerprint}.json"):
                result = cleanup.run_cleanup(apply=True)
            self.assertFalse(owned.exists())
            self.assertTrue(foreign.exists())
            self.assertEqual("complete", result["state"])
            self.assertTrue(result["rejected"])

    def test_artifact_validation_rejects_incomplete_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            derived_root = Path(temporary) / "derived-data"; artifact = derived_root / "fingerprint"
            products = artifact / "Build" / "Products"; products.mkdir(parents=True)
            xctestrun = products / "WDA.xctestrun"; xctestrun.write_bytes(plistlib.dumps({"WDA": {"TestBundlePath": "runner"}}))
            app = products / "WebDriverAgentRunner-Runner.app"; app.mkdir()
            metadata = {
                "schema": WDA_ARTIFACT_SCHEMA, "owner": wda.OWNER, "fingerprint": "fingerprint",
                "xctestrun": str(xctestrun), "runner_app": str(app), "team_id": "EXAMPLE123",
                "bundle_id": "io.example.wda",
            }
            (artifact / wda.ARTIFACT_FILE).write_text(json.dumps(metadata))
            signature = {"team_id": "EXAMPLE123", "bundle_id": "io.example.wda.xctrunner", "authority": "Apple Development", "free_team": True}
            with patch.object(wda, "DERIVED_DATA_ROOT", derived_root), patch("ipad_agent.wda.require_runtime_path", side_effect=lambda value: Path(value)), patch("ipad_agent.wda._signature_metadata", return_value=signature):
                with self.assertRaisesRegex(wda.XCTestControlError, "provenance omits required metadata"):
                    wda.validate_artifact(artifact)


if __name__ == "__main__":
    unittest.main()
