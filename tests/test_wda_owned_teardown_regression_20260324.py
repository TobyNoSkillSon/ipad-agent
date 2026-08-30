import contextlib
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from ipad_agent import wda


class WDAOwnedTeardownRegression20260324Tests(unittest.TestCase):
    def test_descendant_capture_uses_ancestry_and_owned_xctestrun_constraint(self):
        owned_xctestrun = wda.DERIVED_DATA_ROOT / "fingerprint" / "Build" / "Products" / "WebDriverAgentRunner.xctestrun"
        commands = {
            200: f"/usr/bin/xcodebuild test-without-building -xctestrun {owned_xctestrun} -destination id=device",
            201: "/usr/bin/xcodebuild test-without-building -xctestrun /tmp/foreign.xctestrun",
        }

        def run_process(command, *, timeout):
            if command[:2] == ["pgrep", "-P"]:
                parent = int(command[-1])
                return (0, "200 201", "") if parent == 100 else (1, "", "")
            if command[:3] == ["ps", "-o", "command="]:
                return 0, commands[int(command[-1])], ""
            raise AssertionError(command)

        with patch("ipad_agent.wda._run_process", side_effect=run_process), \
             patch("ipad_agent.wda._process_start", side_effect=lambda pid: f"start-{pid}"):
            captured = wda._capture_owned_wda_descendants(100)

        self.assertEqual([200], [process.pid for process in captured])
        self.assertEqual(100, captured[0].parent_pid)
        self.assertTrue(wda._is_owned_wda_xcodebuild_command(commands[200]))
        self.assertFalse(wda._is_owned_wda_xcodebuild_command(commands[201]))

    def test_bounded_descendant_cleanup_escalates_only_the_captured_exact_process(self):
        command = (
            f"/usr/bin/xcodebuild test-without-building -xctestrun "
            f"{wda.DERIVED_DATA_ROOT / 'fingerprint' / 'WDA.xctestrun'}"
        )
        process = wda._OwnedWDAProcess(80377, 79890, "owned-start", command)
        alive = {80377: True}
        signals = []

        def process_start(pid):
            return "owned-start" if alive.get(pid, False) else None

        def kill(pid, sent_signal):
            signals.append((pid, sent_signal))
            if sent_signal == signal.SIGKILL:
                alive[pid] = False

        with patch("ipad_agent.wda._process_start", side_effect=process_start), \
             patch("ipad_agent.wda.os.kill", side_effect=kill), \
             patch("ipad_agent.wda._capture_owned_wda_descendants", return_value=[]):
            result = wda._terminate_wda_xcodebuild(
                server_pid=79890, captured=[process], timeout=0.06
            )

        self.assertTrue(result["complete"])
        self.assertEqual([(80377, signal.SIGTERM), (80377, signal.SIGKILL)], signals)
        self.assertEqual([80377], result["killed_pids"])
        self.assertEqual([], result["remaining_pids"])

    def test_stop_leaves_receipt_and_appium_running_when_descendant_cleanup_is_incomplete(self):
        receipt = {
            "schema": "ipad-agent.appium-owner/v1", "owner": "ipad-agent",
            "pid": 79890, "nonce": "a" * 32, "process_start": "appium-start",
            "executable": "/owned/appium", "command": ["/owned/appium"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "appium-owner.json"
            receipt_path.write_text(json.dumps(receipt))
            with patch.object(wda, "APPIUM_OWNER_RECEIPT", receipt_path), \
                 patch("ipad_agent.wda._owned_appium_identity", return_value=(79890, "a" * 32, "appium-start", False)), \
                 patch("ipad_agent.wda._terminate_wda_xcodebuild", return_value={
                     "complete": False, "reason": "descendant_termination_timeout",
                     "remaining_pids": [80377],
                 }), patch("ipad_agent.wda.os.kill") as kill:
                result = wda.stop_owned_appium_server(timeout=0.01)

            self.assertFalse(result["stopped"])
            self.assertEqual("descendant_cleanup_incomplete", result["reason"])
            self.assertTrue(receipt_path.exists())
            kill.assert_not_called()

    def test_stop_cleans_descendants_before_appium_and_removes_receipt_only_after_exit(self):
        receipt = {
            "schema": "ipad-agent.appium-owner/v1", "owner": "ipad-agent",
            "pid": 79890, "nonce": "b" * 32, "process_start": "appium-start",
            "executable": "/owned/appium", "command": ["/owned/appium"],
        }
        events = []

        def cleanup(**kwargs):
            events.append("descendants")
            return {"complete": True, "remaining_pids": []}

        def kill(pid, sent_signal):
            events.append(("appium", sent_signal))
            if sent_signal == 0:
                raise ProcessLookupError

        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "appium-owner.json"
            receipt_path.write_text(json.dumps(receipt))
            with patch.object(wda, "APPIUM_OWNER_RECEIPT", receipt_path), \
                 patch.object(wda, "_SERVER", None), \
                 patch("ipad_agent.wda._owned_appium_identity", return_value=(79890, "b" * 32, "appium-start", False)), \
                 patch("ipad_agent.wda._terminate_wda_xcodebuild", side_effect=cleanup), \
                 patch("ipad_agent.wda.os.kill", side_effect=kill):
                result = wda.stop_owned_appium_server(timeout=0.05)

            self.assertTrue(result["stopped"])
            self.assertFalse(receipt_path.exists())
        self.assertEqual("descendants", events[0])
        self.assertEqual(("appium", signal.SIGTERM), events[1])

    def test_short_session_orders_capture_delete_cleanup_and_records_proof(self):
        config = wda.XCTestConfig("udid", "18.0", "ABCDE12345", "/owned", "io.example.wda")
        events = []

        def http_json(method, url, payload, timeout):
            if method == "POST" and url.endswith("/session"):
                return {"value": {"sessionId": "session-1"}}
            if method == "POST" and url.endswith("/appium/settings"):
                return {"value": None}
            if method == "DELETE":
                events.append("delete")
                return {"value": None}
            raise AssertionError((method, url))

        def capture(pid):
            events.append("capture")
            return []

        def cleanup(**kwargs):
            events.append("cleanup")
            return {"complete": True, "captured_pids": [], "remaining_pids": []}

        with patch("ipad_agent.wda.ensure_appium_server"), \
             patch("ipad_agent.wda._http_json", side_effect=http_json), \
             patch("ipad_agent.wda._owned_appium_identity", return_value=(79890, "c" * 32, "start", False)), \
             patch("ipad_agent.wda._capture_owned_wda_descendants", side_effect=capture), \
             patch("ipad_agent.wda._terminate_wda_xcodebuild", side_effect=cleanup):
            with wda.short_session(config) as session:
                pass

        self.assertEqual(["capture", "delete", "cleanup"], events)
        self.assertEqual({
            "session_deleted": True,
            "appium_ownership_proven": True,
            "xcodebuild_descendants_captured": [],
            "xcodebuild_remaining": [],
        }, session.teardown_result)

    def test_failed_teardown_invalidates_prior_verification_and_writes_no_success(self):
        selection = wda.WDASelection(
            "device", "udid", "18.0", "ABCDE12345", "io.example.wda",
            "/driver/WDA.xcodeproj", "digest", "Xcode 16", "fingerprint",
        )
        session = wda.AppiumSession("http://127.0.0.1:4723", "session-1")

        @contextlib.contextmanager
        def incomplete_session(*args, **kwargs):
            yield session
            session.teardown_result = {
                "session_deleted": True,
                "appium_ownership_proven": True,
                "xcodebuild_descendants_captured": [80377],
                "xcodebuild_remaining": [80377],
            }

        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "fingerprint.json"
            receipt_path.write_text("old-success")
            artifact = {"xctestrun": str(Path(temporary) / "WDA.xctestrun")}
            with patch("ipad_agent.wda.artifact_directory", return_value=Path(temporary)), \
                 patch("ipad_agent.wda.validate_artifact", return_value=artifact), \
                 patch("ipad_agent.wda.verification_path", return_value=receipt_path), \
                 patch("ipad_agent.wda.short_session", side_effect=incomplete_session), \
                 patch("ipad_agent.wda.private_write_text") as write_receipt:
                with self.assertRaisesRegex(wda.XCTestControlError, "teardown was not proven"):
                    wda.verify_bounded_session(selection, apply=True)

            self.assertFalse(receipt_path.exists())
            write_receipt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
