import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from unittest.mock import patch

from ipad_agent.display import _api
from ipad_agent.server import _valid_bind_host
from ipad_agent.wda import XCTestConfig, XCTestControlError, ensure_appium_server, short_session


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

    def test_appium_must_be_loopback(self):
        with self.assertRaisesRegex(XCTestControlError, "loopback"):
            ensure_appium_server("http://192.0.2.1:4723")

    def test_display_rejects_wildcard_and_loopback(self):
        self.assertFalse(_valid_bind_host("0.0.0.0"))
        self.assertFalse(_valid_bind_host("127.0.0.1"))
        self.assertFalse(_valid_bind_host("192.0.2.1"))
        self.assertTrue(_valid_bind_host("192.168.1.10"))

    def test_failed_session_creation_still_cleans_wda(self):
        config = XCTestConfig("udid", "1", "TEAM", "/tmp", "org.example.wda")
        with patch("ipad_agent.wda.ensure_appium_server"), patch("ipad_agent.wda._http_json", side_effect=XCTestControlError("timed out")), patch("ipad_agent.wda._terminate_wda_xcodebuild") as cleanup:
            with self.assertRaises(XCTestControlError):
                with short_session(config):
                    pass
        cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
