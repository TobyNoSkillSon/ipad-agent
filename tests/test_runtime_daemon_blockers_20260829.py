import base64
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

from ipad_agent.api import _result_for_request
from ipad_agent.config import Config, config_from_snapshot, config_snapshot
from ipad_agent.operations import OperationResult
from ipad_agent.paths import (
    AF_UNIX_PATH_BUDGET,
    private_runtime_socket_path,
    private_write_text,
    runtime_path,
)
from ipad_agent.registry import load_registry
from ipad_agent.runtime import (
    Daemon,
    RUNTIME_PROTOCOL,
    SOCKET_OWNER,
    SOCKET_OWNER_SCHEMA,
    _client_send,
    _client_socket_path,
    _operation_for_request,
    _owned_socket_metadata,
    _socket_metadata_path,
    dispatch_client,
    registry_from_snapshot,
    registry_snapshot,
)
from ipad_agent.wda import XCTestControlError


class RuntimeDaemonRecoveredBlockers20260829Tests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            runtime_path("tests").rmdir()
        except OSError:
            pass

    def _authenticated_exchange(self, daemon, request):
        client, server = socket.socketpair()
        try:
            client.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode())
            daemon._handle(server)
            raw = client.recv(1024 * 1024)
        finally:
            client.close()
        return json.loads(raw.split(b"\n", 1)[0]) if raw else None

    def _wire(self, daemon, request):
        value = dict(request)
        value.update({
            "_protocol": RUNTIME_PROTOCOL,
            "_nonce": daemon.nonce,
            "_config": config_snapshot(Config()),
            "_registry": registry_snapshot(load_registry()),
        })
        return value

    def test_wda_response_loss_is_structurally_uncertain_through_daemon(self):
        daemon = Daemon(runtime_path("tests", "uncertain.sock"), idle_ttl=10, nonce="a" * 64)
        lost = XCTestControlError(
            "opaque connection loss", code="wda_transport_error",
            uncertain=True, dispatched=True,
        )
        with patch.object(daemon.runtime, "tap_selector", side_effect=lost):
            payload = self._authenticated_exchange(
                daemon, self._wire(daemon, {"op": "t", "selector": "button"})
            )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["uncertain"])
        self.assertEqual("response_lost", payload["_operation"]["phase"])
        self.assertTrue(payload["_operation"]["dispatched"])
        self.assertEqual("wda_transport_error", payload["error_info"]["code"])

    def test_batch_retains_child_uncertainty_in_daemon_and_api_projection(self):
        daemon = Daemon(runtime_path("tests", "batch.sock"), idle_ttl=10, nonce="b" * 64)
        lost = XCTestControlError(
            "timeout after tap", code="wda_transport_error",
            uncertain=True, dispatched=True,
        )
        request = {"op": "b", "batch": [["t", "button"], ["q"]]}
        with patch.object(daemon.runtime, "tap_selector", side_effect=lost):
            payload = self._authenticated_exchange(daemon, self._wire(daemon, request))

        child = payload["result"][0]
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["uncertain"])
        self.assertTrue(child["uncertain"])
        self.assertEqual("response_lost", child["_operation"]["phase"])
        public = _result_for_request(payload, request)
        self.assertTrue(public["uncertain"])
        self.assertIn("do not retry", public.summary)

    def test_explicit_config_and_registry_contract_are_carried_to_daemon(self):
        config = Config(
            browser="brave",
            enabled_addons=["brave"],
            bundle_aliases={"custom app": "org.example.Custom"},
        )
        registry = load_registry(enabled_addons=["brave"])
        captured = {}

        def no_daemon(request, operation, *, timeout):
            captured.update(request)
            return OperationResult.not_sent(operation)

        with patch("ipad_agent.runtime._client_send", side_effect=no_daemon):
            result = dispatch_client({"op": "q"}, config=config, registry=registry)

        restored_config = config_from_snapshot(captured["_config"])
        restored_registry = registry_from_snapshot(captured["_registry"])
        self.assertTrue(result["ok"])
        self.assertEqual("com.brave.ios.browser", restored_config.browser_bundle)
        self.assertEqual("org.example.Custom", restored_config.bundle_aliases["custom app"])
        self.assertEqual("com.brave.ios.browser", restored_registry.resolve_bundle("Brave Browser"))
        self.assertEqual(registry_snapshot(registry), captured["_registry"])

    def test_legacy_browser_bundle_wire_path_is_rejected_before_send(self):
        with patch("ipad_agent.runtime._client_send") as send:
            result = dispatch_client(
                {"op": "q", "browser_bundle": "com.example.Legacy"},
                config=Config(), registry=load_registry(),
            )
        self.assertFalse(result["ok"])
        self.assertIn("legacy browser_bundle", result["error"])
        send.assert_not_called()

    def test_unowned_listener_is_never_connected_or_sent_a_command(self):
        path = private_runtime_socket_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        with patch("ipad_agent.runtime._client_socket_path", return_value=path):
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                listener.bind(str(path))
                os.chmod(path, 0o600)
                listener.listen(1)
                listener.settimeout(0.05)
                operation = _operation_for_request({"op": "t", "selector": "button"})
                request = {
                    "op": "t", "selector": "button",
                    "_config": config_snapshot(Config()),
                    "_registry": registry_snapshot(load_registry()),
                }
                outcome = _client_send(request, operation, timeout=0.1)
                self.assertFalse(outcome.dispatched)
                self.assertEqual("untrusted_endpoint", outcome.error.code)
                with self.assertRaises(socket.timeout):
                    listener.accept()
            finally:
                listener.close()
                path.unlink(missing_ok=True)
                _socket_metadata_path(path).unlink(missing_ok=True)

    def test_stale_replacement_requires_matching_owned_socket_receipt(self):
        path = private_runtime_socket_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        old = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old.bind(str(path))
        os.chmod(path, 0o600)
        old.close()
        unowned = Daemon(path, idle_ttl=10, nonce="c" * 64)
        with self.assertRaisesRegex(RuntimeError, "unowned socket"):
            unowned._bind()
        self.assertTrue(path.exists())

        info = path.lstat()
        receipt = {
            "schema": SOCKET_OWNER_SCHEMA,
            "owner": SOCKET_OWNER,
            "protocol": RUNTIME_PROTOCOL,
            "nonce": "d" * 64,
            "socket": str(path),
            "inode": info.st_ino,
            "pid": os.getpid(),
            "uid": os.geteuid(),
        }
        private_write_text(
            _socket_metadata_path(path),
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        )
        replacement = Daemon(path, idle_ttl=10, nonce="e" * 64)
        listener = replacement._bind()
        try:
            self.assertNotEqual(info.st_ino, path.lstat().st_ino)
        finally:
            listener.close()
            path.unlink(missing_ok=True)
            _socket_metadata_path(path).unlink(missing_ok=True)

    def test_wrong_nonce_cannot_dispatch_even_to_owned_daemon(self):
        daemon = Daemon(runtime_path("tests", "wrong-nonce.sock"), idle_ttl=10, nonce="f" * 64)
        request = self._wire(daemon, {"op": "q"})
        request["_nonce"] = "0" * 64
        with patch.object(daemon.runtime, "execute") as execute:
            payload = self._authenticated_exchange(daemon, request)
        self.assertIsNone(payload)
        execute.assert_not_called()

    def test_screenshot_rejects_escape_and_symlink_before_contacting_wda(self):
        runtime = Daemon(runtime_path("tests", "screenshot.sock"), idle_ttl=10).runtime
        with tempfile.TemporaryDirectory() as temporary:
            runtime_root = Path(temporary) / ".runtime"
            artifact_root = runtime_root / "artifacts"
            artifact_root.mkdir(parents=True, mode=0o700)
            os.chmod(runtime_root, 0o700)
            os.chmod(artifact_root, 0o700)
            outside_artifacts = runtime_root / "config" / "not-an-artifact.png"
            with patch("ipad_agent.core.paths.RUNTIME_ROOT", runtime_root), \
                 patch("ipad_agent.core.paths.ARTIFACT_DIR", artifact_root):
                for output in (".", "../escape.png", "nested/../escape.png", str(outside_artifacts)):
                    with self.subTest(output=output), patch.object(runtime, "ensure_session") as session:
                        with self.assertRaises(ValueError):
                            runtime.screenshot(output)
                        session.assert_not_called()

                outside = Path(temporary) / "outside.png"
                outside.write_bytes(b"untouched")
                link = artifact_root / "linked.png"
                link.symlink_to(outside)
                with patch.object(runtime, "ensure_session") as session:
                    with self.assertRaisesRegex(ValueError, "symlinks are not allowed"):
                        runtime.screenshot("linked.png")
                    session.assert_not_called()
                self.assertEqual(b"untouched", outside.read_bytes())

    def test_screenshot_atomically_writes_private_artifact_without_truncating_on_failure(self):
        runtime = Daemon(runtime_path("tests", "atomic-screenshot.sock"), idle_ttl=10).runtime
        with tempfile.TemporaryDirectory() as temporary:
            runtime_root = Path(temporary) / ".runtime"
            artifact_root = runtime_root / "artifacts"
            artifact_root.mkdir(parents=True, mode=0o700)
            os.chmod(runtime_root, 0o700)
            os.chmod(artifact_root, 0o700)
            target = artifact_root / "capture.png"
            target.write_bytes(b"previous")
            os.chmod(target, 0o600)
            session = Mock()
            session._request.return_value = base64.b64encode(b"new-pixels").decode("ascii")
            with patch("ipad_agent.core.paths.RUNTIME_ROOT", runtime_root), \
                 patch("ipad_agent.core.paths.ARTIFACT_DIR", artifact_root), \
                 patch.object(runtime, "ensure_session", return_value=session), \
                 patch("ipad_agent.core.paths.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    runtime.screenshot("capture.png")
            self.assertEqual(b"previous", target.read_bytes())

            with patch("ipad_agent.core.paths.RUNTIME_ROOT", runtime_root), \
                 patch("ipad_agent.core.paths.ARTIFACT_DIR", artifact_root), \
                 patch.object(runtime, "ensure_session", return_value=session):
                self.assertEqual(str(target), runtime.screenshot("capture.png"))
            self.assertEqual(b"new-pixels", target.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(target.stat().st_mode))

    def test_deep_checkout_uses_private_bounded_socket_and_removes_it_cleanly(self):
        deep_root = Path("/checkout") / ("very-deep-" * 40) / secrets.token_hex(8)
        short_path = private_runtime_socket_path(deep_root)
        self.assertLessEqual(len(os.fsencode(short_path)), AF_UNIX_PATH_BUDGET)
        self.assertNotIn(str(deep_root), str(short_path))

        with patch("ipad_agent.runtime.REPOSITORY_ROOT", deep_root):
            self.assertEqual(short_path, _client_socket_path())
            daemon = Daemon(short_path, idle_ttl=10, nonce="9" * 64)
            listener = daemon._bind()
            ownership = _owned_socket_metadata(short_path)
            self.assertIsNotNone(ownership)
            self.assertEqual(str(short_path), ownership["socket"])
            self.assertEqual(short_path.lstat().st_ino, ownership["inode"])
            listener.close()
            # Let the normal serve-finally branch prove endpoint and receipt
            # teardown without rebinding the already-created socket.
            daemon._bind = lambda: listener
            daemon.stop = True
            daemon.serve()
            self.assertFalse(short_path.exists())
            self.assertFalse(_socket_metadata_path(short_path).exists())
            self.assertFalse(short_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
