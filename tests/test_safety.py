import os
import tempfile
import threading
from pathlib import Path
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from ipad_agent.display import _api
from ipad_agent.server import _valid_bind_host
from ipad_agent.wda import XCTestConfig, XCTestControlError, ensure_appium_server, short_session
from ipad_agent.transports import wda


class SafetyTests(unittest.TestCase):
    def test_display_api_does_not_forward_token_on_redirect(self):
        captured = []
        class Target(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                captured.append(self.headers.get("Authorization"));self.send_response(200);self.end_headers();self.wfile.write(b"{}")
        target = HTTPServer(("127.0.0.1", 0), Target)
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(302);self.send_header("Location", f"http://127.0.0.1:{target.server_port}/capture");self.end_headers()
        redirect = HTTPServer(("127.0.0.1", 0), Redirect)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (target, redirect)]
        for thread in threads: thread.start()
        try:
            with self.assertRaises(HTTPError):
                _api({"host": "127.0.0.1", "port": redirect.server_port, "token": "SECRET"}, "GET", "/health")
        finally:
            redirect.shutdown();target.shutdown();redirect.server_close();target.server_close()
        self.assertEqual([], captured)

    def test_appium_receipt_failure_stops_the_exact_spawned_process(self):
        process = Mock(pid=4321, returncode=None)
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cache").mkdir()
            appium = root / "appium"
            appium.write_text("fixture")
            log_descriptor = os.open(root / "cache" / "appium.log", os.O_WRONLY | os.O_CREAT, 0o600)
            os.close(log_descriptor)
            start_marker = root / "appium-starting.json"
            owner_receipt = root / "appium-owner.json"

            def write_state(path, _text):
                if Path(path) == start_marker:
                    return start_marker
                raise PermissionError("receipt")

            with patch.object(wda, "RUNTIME_ROOT", root), \
                 patch.object(wda, "APPIUM", appium), \
                 patch.object(wda, "APPIUM_START_MARKER", start_marker), \
                 patch.object(wda, "APPIUM_OWNER_RECEIPT", owner_receipt), \
                 patch.object(wda, "private_mkdir"), \
                 patch.object(wda, "_owned_appium_identity", return_value=None), \
                 patch.object(wda, "_http_json", side_effect=XCTestControlError("not running")), \
                 patch.object(wda.subprocess, "Popen", return_value=process), \
                 patch.object(wda, "_process_start", return_value="start"), \
                 patch.object(wda, "private_write_text", side_effect=write_state):
                with self.assertRaisesRegex(XCTestControlError, "spawned process was stopped"):
                    wda.ensure_appium_server(timeout=0.1)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once()

    def test_appium_must_be_loopback(self):
        with self.assertRaisesRegex(XCTestControlError, "loopback"):
            ensure_appium_server("http://192.0.2.1:4723")

    def test_appium_refuses_an_unowned_loopback_responder(self):
        with patch("ipad_agent.wda._owned_appium_identity", return_value=None), \
             patch("ipad_agent.wda._http_json", return_value={"value": {}}), \
             patch("ipad_agent.wda.subprocess.Popen") as popen:
            with self.assertRaisesRegex(XCTestControlError, "unowned process"):
                ensure_appium_server()
        popen.assert_not_called()

    def test_appium_listener_must_belong_only_to_the_receipt_pid(self):
        with patch.object(wda, "_run_process", return_value=(0, "p4321", "")):
            self.assertTrue(wda._listener_owned_by_pid(4723, 4321))
        with patch.object(wda, "_run_process", return_value=(0, "p4321\np9999", "")):
            self.assertFalse(wda._listener_owned_by_pid(4723, 4321))

    def test_unreceipted_appium_probe_fails_closed_when_process_inspection_fails(self):
        responses = [(1, "", ""), (127, "", "inspection failed")]
        with patch.object(wda, "_run_process", side_effect=responses):
            with self.assertRaisesRegex(XCTestControlError, "absence could not be proven"):
                wda.appium_endpoint_or_project_process_present("http://127.0.0.1:4723")

    def test_appium_receipt_must_match_the_configured_endpoint(self):
        receipt = {
            "schema": wda.APPIUM_OWNER_SCHEMA,
            "owner": wda.OWNER,
            "pid": 4321,
            "nonce": "a" * 32,
            "process_start": "start",
            "executable": "/tmp/appium",
            "command": ["/tmp/appium", "--port", "4723"],
            "server_url": "http://127.0.0.1:4723",
        }
        command = "/tmp/appium --port 4723 IPAD_AGENT_OWNER_NONCE=" + "a" * 32
        with patch.object(wda, "_process_start", return_value="start"), \
             patch.object(wda, "_run_process", return_value=(0, command, "")):
            self.assertIsNotNone(
                wda._owned_appium_identity(receipt, server_url="http://127.0.0.1:4723")
            )
            self.assertIsNone(
                wda._owned_appium_identity(receipt, server_url="http://127.0.0.1:4724")
            )

    def test_wda_discovery_rejects_simulators_and_unpaired_devices(self):
        devices = [
            {"identifier": "sim", "hardwareProperties": {"deviceType": "iPad", "reality": "simulator", "udid": "sim"}, "deviceProperties": {"osVersionNumber": "18.0"}, "connectionProperties": {"pairingState": "paired"}},
            {"identifier": "unpaired", "hardwareProperties": {"deviceType": "iPad", "reality": "physical", "udid": "unpaired"}, "deviceProperties": {"osVersionNumber": "18.0"}, "connectionProperties": {"pairingState": "unpaired"}},
            {"identifier": "ipad", "hardwareProperties": {"deviceType": "iPad", "reality": "physical", "udid": "ipad-udid"}, "deviceProperties": {"osVersionNumber": "18.0"}, "connectionProperties": {"pairingState": "paired"}},
        ]
        with patch.object(wda, "_devicectl_json", return_value={"result": {"devices": devices}}):
            self.assertEqual("ipad", wda._discover_ipad(1.0)["identifier"])
            with self.assertRaisesRegex(XCTestControlError, "found 0"):
                wda._discover_ipad(1.0, selected="sim")

    def test_display_rejects_wildcard_and_loopback(self):
        self.assertFalse(_valid_bind_host("0.0.0.0"))
        self.assertFalse(_valid_bind_host("127.0.0.1"))
        self.assertFalse(_valid_bind_host("192.0.2.1"))
        self.assertTrue(_valid_bind_host("192.168.1.10"))

    def test_failed_session_creation_still_cleans_wda(self):
        config = XCTestConfig("udid", "1", "TEAM", "/tmp", "org.example.wda")
        with patch("ipad_agent.wda._config_with_runtime_compatibility", return_value=config), patch("ipad_agent.wda._discover_ipad", return_value={"udid": "udid"}), patch("ipad_agent.wda.ensure_appium_server"), patch("ipad_agent.wda._prove_appium_endpoint", return_value=(1234, "n" * 32, "start", False)), patch("ipad_agent.wda._http_json", side_effect=XCTestControlError("timed out")), patch("ipad_agent.wda._terminate_wda_xcodebuild") as cleanup:
            with self.assertRaises(XCTestControlError):
                with short_session(config):
                    pass
        cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
