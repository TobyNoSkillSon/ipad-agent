import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from ipad_agent.config import Config, config_from_snapshot
from ipad_agent.coredevice import IPadControlError, LaunchResult, _bundle_for_target
from ipad_agent.display import _publish
from ipad_agent.operations import OperationPhase, OperationResult, OperationSpec, SafetyClass
from ipad_agent.registry import AddonNotEnabledError, load_registry
from ipad_agent.runtime import Runtime, _client_send, dispatch_client


ROOT = Path(__file__).resolve().parents[1]


class RegistryRuntimeWiringContracts(unittest.TestCase):
    def test_package_import_is_inert(self):
        code = r'''
import os, pathlib, sys
before = dict(os.environ)
runtime = pathlib.Path.cwd() / ".runtime"
existed = runtime.exists()
import ipad_agent
assert "ipad_agent.config" not in sys.modules
assert "ipad_agent.registry" not in sys.modules
assert "ipad_agent.api" not in sys.modules
assert not hasattr(ipad_agent, "ip")
assert not hasattr(ipad_agent, "ipad")
assert not hasattr(ipad_agent, "sh")
assert not hasattr(ipad_agent, "show")
assert dict(os.environ) == before
assert runtime.exists() == existed
'''
        completed = subprocess.run(
            [sys.executable, "-B", "-c", code], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_safari_default_and_brave_addon_resolution(self):
        config = Config()
        registry = load_registry()
        self.assertEqual("com.apple.mobilesafari", _bundle_for_target("safari", config, registry))
        with self.assertRaises(AddonNotEnabledError):
            _bundle_for_target("brave", config, registry)
        brave = load_registry(enabled_addons=["brave"])
        self.assertEqual(
            "com.brave.ios.browser",
            _bundle_for_target("Brave Browser", Config(enabled_addons=["brave"]), brave),
        )

    def test_runtime_uses_registry_selectors(self):
        runtime = Runtime(config=Config(), registry=load_registry())
        runtime.active_app = "com.apple.Preferences"
        recipe = runtime.selector("wifi")
        self.assertEqual("com.apple.settings.wifi", recipe["value"])
        self.assertEqual("settings", recipe["_integration"])
        with self.assertRaises(AddonNotEnabledError):
            runtime.selector("brave.address")

    def test_locked_or_lost_foreground_never_delivers_url(self):
        meta = {"host": "192.168.1.2", "port": 8766, "token": "token"}
        config = Config()
        registry = load_registry()
        api_results = iter([{"revision": "r1"}])

        def fake_api(_meta, method, path, body=None, timeout=3.0):
            if method == "POST" and path == "/api/show":
                return next(api_results)
            return {"ok": True}

        locked = LaunchResult("com.apple.mobilesafari", "device", 0.01, None, True)
        with patch("ipad_agent.display._ensure_server", return_value=(meta, 0.0, False)), \
             patch("ipad_agent.display._status", return_value={"visible": False}), \
             patch("ipad_agent.display._api", side_effect=fake_api), \
             patch("ipad_agent.display._launch", return_value=locked) as launch:
            result = _publish(
                {"kind": "text", "text": "hello"}, device=None, ready_timeout=2.0,
                config=config, registry=registry,
            )
        self.assertTrue(result["locked"])
        self.assertEqual(1, launch.call_count)
        self.assertIsNone(launch.call_args.args[1])

        api_results = iter([{"revision": "r1"}])
        lost = IPadControlError("opaque transport failure", response_lost=True)
        with patch("ipad_agent.display._ensure_server", return_value=(meta, 0.0, False)), \
             patch("ipad_agent.display._status", return_value={"visible": False}), \
             patch("ipad_agent.display._api", side_effect=fake_api), \
             patch("ipad_agent.display._launch", side_effect=lost) as launch:
            with self.assertRaises(IPadControlError):
                _publish(
                    {"kind": "text", "text": "hello"}, device=None, ready_timeout=2.0,
                    config=config, registry=registry,
                )
        self.assertEqual(1, launch.call_count)
        self.assertIsNone(launch.call_args.args[1])

    def test_sender_marks_response_loss_structurally_and_does_not_restart(self):
        operation = OperationSpec("tap", "tap", SafetyClass.TRANSIENT)

        class ClosedSocket:
            def settimeout(self, _timeout): pass
            def connect(self, _path): pass
            def sendall(self, _payload): pass
            def recv(self, _size): return b""
            def close(self): pass

        with patch("ipad_agent.runtime.socket.socket", return_value=ClosedSocket()):
            outcome = _client_send({"op": "t", "selector": "x"}, operation, timeout=1.0)
        self.assertEqual(OperationPhase.RESPONSE_LOST, outcome.phase)
        self.assertTrue(outcome.uncertain)

        lost = OperationResult.response_lost(operation)
        with patch("ipad_agent.runtime._client_send", return_value=lost) as send, \
             patch("ipad_agent.runtime._client_start_daemon") as start:
            result = dispatch_client(
                {"op": "t", "selector": "x"}, config=Config(), registry=load_registry()
            )
        self.assertTrue(result["uncertain"])
        send.assert_called_once()
        start.assert_not_called()

    def test_daemon_request_carries_validated_config_snapshot(self):
        config = Config(device="device-1", browser="safari", display_port=9000)
        registry = load_registry()
        captured = {}

        def no_daemon(request, operation, *, timeout):
            captured.update(request)
            return OperationResult.not_sent(operation)

        with patch("ipad_agent.runtime._client_send", side_effect=no_daemon):
            result = dispatch_client({"op": "q"}, config=config, registry=registry)
        restored = config_from_snapshot(captured["_config"])
        self.assertEqual("device-1", restored.device)
        self.assertEqual("safari", restored.browser)
        self.assertEqual(9000, restored.display_port)
        self.assertTrue(result["ok"])

    def test_sensitive_wire_operation_without_authority_is_not_sent(self):
        request = {
            "op": "t", "selector": "x",
            "_operation": {
                "operation_id": "protected", "name": "protected tap",
                "safety_class": "protected", "retry_class": "never_automated",
                "authority": None, "metadata": {},
            },
        }
        with patch("ipad_agent.runtime._client_send") as send:
            result = dispatch_client(request, config=Config(), registry=load_registry())
        self.assertFalse(result["ok"])
        self.assertIn("explicit authority", result["error"])
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
