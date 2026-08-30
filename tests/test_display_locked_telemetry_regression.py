import unittest
from unittest.mock import patch

from ipad_agent.config import Config
from ipad_agent.coredevice import LaunchResult
from ipad_agent.display import _direct, _publish
from ipad_agent.registry import load_registry


class DisplayLockedTelemetryRegression(unittest.TestCase):
    def setUp(self):
        patcher = patch("ipad_agent.display._FORCE_FOREGROUND", False)
        self.force_foreground = patcher.start()
        self.addCleanup(patcher.stop)
        self.config = Config()
        self.registry = load_registry()
        self.meta = {"host": "192.168.1.2", "port": 8766, "token": "token"}

    def test_initial_locked_launch_stops_before_url_fallback_and_is_not_foregrounded(self):
        api_calls = []

        def fake_api(_meta, method, path, body=None, timeout=3.0):
            api_calls.append((method, path, body))
            if method == "POST" and path == "/api/show":
                return {"revision": "r1"}
            return {"ok": True}

        locked = LaunchResult("com.apple.mobilesafari", "device", 0.01, None, True)
        with patch("ipad_agent.display._ensure_server", return_value=(self.meta, 0.0, False)), \
             patch("ipad_agent.display._status", return_value={"visible": False}), \
             patch("ipad_agent.display._api", side_effect=fake_api), \
             patch("ipad_agent.display._launch", return_value=locked) as launch:
            result = _publish(
                {"kind": "text", "text": "hello"}, device=None, ready_timeout=2.0,
                config=self.config, registry=self.registry,
            )

        self.assertEqual(1, launch.call_count)
        self.assertIsNone(launch.call_args.args[1])
        self.assertEqual([("POST", "/api/show", {"payload": {"kind": "text", "text": "hello"}})], api_calls)
        self.assertTrue(result["locked"])
        self.assertEqual("device-locked", result["verified"])
        self.assertFalse(result["foregrounded"])
        self.assertTrue(result["launch_accepted"])
        self.assertFalse(result.get("url_delivered", False))

    def test_locked_url_fallback_branch_never_claims_foreground(self):
        api_calls = []

        def fake_api(_meta, method, path, body=None, timeout=3.0):
            api_calls.append((method, path, body))
            if method == "POST" and path == "/api/show":
                return {"revision": f"r{sum(item[1] == '/api/show' for item in api_calls)}"}
            return {"ok": True}

        accepted = LaunchResult("com.apple.mobilesafari", "device", 0.01, None, False)
        locked = LaunchResult("com.apple.mobilesafari", "device", 0.01, "http://example.invalid", True)
        with patch("ipad_agent.display._ensure_server", return_value=(self.meta, 0.0, False)), \
             patch("ipad_agent.display._status", return_value={"visible": False}), \
             patch("ipad_agent.display._wait_ready", side_effect=[None, None]), \
             patch("ipad_agent.display._api", side_effect=fake_api), \
             patch("ipad_agent.display._launch", side_effect=[accepted, locked]) as launch:
            result = _publish(
                {"kind": "text", "text": "hello"}, device=None, ready_timeout=2.0,
                config=self.config, registry=self.registry,
            )

        self.assertEqual(2, launch.call_count)
        self.assertIsNone(launch.call_args_list[0].args[1])
        self.assertTrue(launch.call_args_list[1].args[1].startswith("http://192.168.1.2:8766/now#"))
        self.assertTrue(result["locked"])
        self.assertFalse(result["foregrounded"])
        self.assertTrue(result["launch_accepted"])
        self.assertTrue(result["url_delivered"])

    def test_direct_locked_launch_exposes_dispatch_without_foreground_claim(self):
        locked = LaunchResult("com.apple.mobilesafari", "device", 0.01, "https://example.invalid", True)
        with patch("ipad_agent.display._launch", return_value=locked), \
             patch("ipad_agent.display._read_meta", return_value=None):
            result = _direct(
                "safari", "https://example.invalid", device=None,
                config=self.config, registry=self.registry,
            )

        self.assertTrue(result["locked"])
        self.assertEqual("device-locked", result["verified"])
        self.assertFalse(result["foregrounded"])
        self.assertTrue(result["launch_accepted"])


if __name__ == "__main__":
    unittest.main()
