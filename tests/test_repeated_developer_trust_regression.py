import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from ipad_agent import doctor, setup, wda
from ipad_agent.config import Config


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class RepeatedDeveloperTrustRegressionTests(unittest.TestCase):
    def test_doctor_does_not_infer_personal_team_trust_from_receipt_state(self):
        missing_or_expired = doctor._developer_trust_check(
            session_verified=False,
        )
        self.assertEqual("skipped", missing_or_expired.status)
        self.assertIsNone(missing_or_expired.human_action)

        proven = doctor._developer_trust_check(
            session_verified=True,
        )
        self.assertEqual("pass", proven.status)

    def test_verify_attempts_one_bounded_session_despite_unproven_trust(self):
        checks = [
            {"id": identifier, "status": "pass"}
            for identifier in setup._VERIFY_PREREQUISITES
        ]
        checks.extend([
            {
                "id": "device.developer_trust", "status": "action_required",
                "human_action": "stale inferred trust action",
            },
            {
                "id": "automation.session_verified", "status": "fail",
                "remediation": "run verify",
            },
        ])
        report = {
            "schema": "ipad-agent.doctor/v2", "state": "action_required",
            "ready": False, "exit_code": 10, "selected": {},
            "checks": checks, "next": ["device.developer_trust", "automation.session_verified"],
        }
        selection = wda.WDASelection(
            "device", "udid", "18.0", "ABCDE12345", "io.example.wda",
            "/driver/WDA.xcodeproj", "digest", "Xcode 16", "fingerprint",
        )
        verify_result = {"ok": True, "changed": True, "receipt": {"verified": True}}
        with patch("ipad_agent.setup.run_doctor", side_effect=[report, report]), \
             patch("ipad_agent.setup._selection_from_report", return_value=selection), \
             patch("ipad_agent.setup.load_config", return_value=Config()), \
             patch("ipad_agent.setup.wda.verify_bounded_session", return_value=verify_result) as verify:
            result = setup.run_setup(apply=True, phase="verify")

        verify.assert_called_once_with(
            selection, apply=True, timeout=180.0,
            appium_url=Config().appium_url,
        )
        self.assertEqual([{"phase": "verify", "ok": True, "changed": True, "verification": "recorded"}], result["operations"])

    def test_only_structural_wda_session_failure_requests_developer_trust(self):
        trusted_failure = {
            "value": {
                "error": "session not created",
                "message": (
                    "Unable to launch WebDriverAgentRunner.xctrunner because its "
                    "profile has not been explicitly trusted by the user"
                ),
            }
        }
        opener = Mock()
        opener.open.return_value = _Response(trusted_failure)
        with patch("ipad_agent.wda.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(wda.XCTestControlError) as caught:
                wda._http_json("POST", "http://127.0.0.1:4723/session", {}, 1)
        self.assertEqual("developer_trust_required", caught.exception.code)

        http_error = urllib.error.HTTPError(
            "http://127.0.0.1:4723/wd/hub/session", 500, "error", {},
            io.BytesIO(json.dumps(trusted_failure).encode()),
        )
        opener.open.side_effect = http_error
        with patch("ipad_agent.wda.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(wda.XCTestControlError) as caught:
                wda._http_json("POST", "http://127.0.0.1:4723/wd/hub/session", {}, 1)
        self.assertEqual("developer_trust_required", caught.exception.code)

        opener.open.side_effect = None
        other_failure = {
            "value": {
                "error": "session not created",
                "message": "Unable to launch WebDriverAgentRunner.xctrunner: invalid entitlements",
            }
        }
        opener.open.return_value = _Response(other_failure)
        with patch("ipad_agent.wda.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(wda.XCTestControlError) as caught:
                wda._http_json("POST", "http://127.0.0.1:4723/session", {}, 1)
        self.assertEqual("wda_remote_error", caught.exception.code)

        classified = setup._classify_transition_error(
            caught.exception, str(caught.exception),
        )
        self.assertEqual("setup_transition_failed", classified["code"])
        public = setup._public_error(classified)
        self.assertIn("invalid entitlements", public["message"])
        self.assertNotIn("trust the WDA developer app", public["message"])

    def test_generic_developer_app_words_do_not_create_a_trust_gate(self):
        classified = setup._classify_transition_error(
            RuntimeError("Developer app installation failed for an unrelated reason"),
            "Developer app installation failed for an unrelated reason",
        )
        self.assertEqual("setup_transition_failed", classified["code"])


if __name__ == "__main__":
    unittest.main()
