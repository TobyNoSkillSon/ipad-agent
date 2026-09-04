from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

from ipad_agent.airdrop import (
    AccessibilitySelection,
    AirDropBuildError,
    AirDropError,
    AirDropSnapshotError,
    AirDropValidationError,
    HELPER_BUILD_SCRIPT,
    HELPER_SOURCE,
    _run_one_attempt,
    airdrop,
    send_file,
    validate_local_file,
)
from ipad_agent.config import Config, load_config


class _FakeStream:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._lines = [json.dumps(event) + "\n" for event in events]

    def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""

    def read(self, size: int = -1) -> str:
        return ""


class _FakeProcess:
    def __init__(self, events: list[dict[str, object]], returncode: int = 0) -> None:
        self.stdout = _FakeStream(events)
        self.stderr = _FakeStream([])
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode if not self._has_output() else None

    def _has_output(self) -> bool:
        return bool(self.stdout._lines)

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class AirDropV1Tests(unittest.TestCase):
    def _file(self, directory: str, name: str = "payload.PDF", data: bytes = b"abcd") -> Path:
        path = Path(directory).resolve() / name
        path.write_bytes(data)
        return path

    def test_validation_requires_canonical_regular_file_inside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = self._file(directory)
            validated = validate_local_file(
                path,
                allowed_roots=[root],
                allowed_extensions=[".pdf"],
                max_bytes=4,
            )
            self.assertEqual(path, validated.path)
            self.assertEqual(4, validated.size)
            self.assertEqual(".pdf", validated.extension)

            with self.assertRaisesRegex(AirDropValidationError, "exceeds"):
                validate_local_file(
                    path,
                    allowed_roots=[root],
                    allowed_extensions=[".pdf"],
                    max_bytes=3,
                )
            with self.assertRaisesRegex(AirDropValidationError, "extension"):
                validate_local_file(
                    path,
                    allowed_roots=[root],
                    allowed_extensions=[".png"],
                    max_bytes=4,
                )

    def test_validation_rejects_symlink_directory_and_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory).resolve()
            target = self._file(outside)
            link = root / "payload.pdf"
            link.symlink_to(target)
            with self.assertRaises(AirDropValidationError):
                validate_local_file(
                    link,
                    allowed_roots=[root],
                    allowed_extensions=[".pdf"],
                    max_bytes=100,
                )
            with self.assertRaisesRegex(AirDropValidationError, "outside"):
                validate_local_file(
                    target,
                    allowed_roots=[root],
                    allowed_extensions=[".pdf"],
                    max_bytes=100,
                )
            with self.assertRaisesRegex(AirDropValidationError, "regular"):
                validate_local_file(
                    root,
                    allowed_roots=[root.parent],
                    allowed_extensions=[".pdf"],
                    max_bytes=100,
                )

    def test_validation_rejects_unsafe_or_overbroad_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = self._file(directory)
            root.chmod(0o770)
            try:
                with self.assertRaisesRegex(AirDropValidationError, "writable"):
                    validate_local_file(
                        path,
                        allowed_roots=[root],
                        allowed_extensions=[".pdf"],
                        max_bytes=100,
                    )
            finally:
                root.chmod(0o700)
            path.chmod(0o660)
            try:
                with self.assertRaisesRegex(AirDropValidationError, "file must not be writable"):
                    validate_local_file(
                        path,
                        allowed_roots=[root],
                        allowed_extensions=[".pdf"],
                        max_bytes=100,
                    )
            finally:
                path.chmod(0o600)
        with self.assertRaisesRegex(AirDropValidationError, "too broad"):
            validate_local_file(
                Path.home() / "nonexistent-ipad-agent-fixture.pdf",
                allowed_roots=[Path.home().resolve()],
                allowed_extensions=[".pdf"],
                max_bytes=100,
            )

    def test_completed_callback_is_only_path_to_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            validated = validate_local_file(
                self._file(directory),
                allowed_roots=[Path(directory).resolve()],
                allowed_extensions=[".pdf"],
                max_bytes=100,
            )
        process = _FakeProcess([
            {
                "event": "dispatching",
                "attempt_id": "0" * 32,
                "snapshot_path": str(validated.path),
                "nominal_source_bytes": 4,
            },
            {
                "event": "completed",
                "nominal_source_bytes": 4,
                "elapsed_seconds": 2.0,
            },
        ])
        with patch("ipad_agent.airdrop.subprocess.Popen", return_value=process) as popen:
            result = _run_one_attempt(
                ["helper"],
                validated=validated,
                timeout_seconds=1,
                receiver=None,
                accessibility_selector=None,
                selector_timeout_seconds=0.5,
            )
        self.assertEqual("completed", result["status"])
        self.assertEqual(4, result["nominal_source_bytes"])
        self.assertEqual(2.0, result["elapsed_seconds"])
        self.assertEqual(2.0, result["nominal_source_bytes_per_second"])
        self.assertEqual("nominal_source_not_target_receipt", result["metrics_scope"])
        self.assertEqual("not_proven", result["target_receipt"])
        self.assertEqual(1, popen.call_count)

    def test_missing_callback_after_dispatch_is_structurally_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            validated = validate_local_file(
                self._file(directory),
                allowed_roots=[Path(directory).resolve()],
                allowed_extensions=[".pdf"],
                max_bytes=100,
            )
        process = _FakeProcess([{
            "event": "dispatching",
            "attempt_id": "0" * 32,
            "snapshot_path": str(validated.path),
            "nominal_source_bytes": 4,
        }], returncode=3)
        with patch("ipad_agent.airdrop.subprocess.Popen", return_value=process):
            result = _run_one_attempt(
                ["helper"],
                validated=validated,
                timeout_seconds=1,
                receiver=None,
                accessibility_selector=None,
                selector_timeout_seconds=0.5,
            )
        self.assertEqual("uncertain", result["status"])
        self.assertEqual("attempted", result["dispatch"])
        self.assertNotIn("nominal_source_bytes", result)
        self.assertNotIn("nominal_source_bytes_per_second", result)

    def test_native_helper_launch_cancellation_is_uncertain_and_redacted(self):
        private = "/private/project/.runtime/airdrop/attempts/badcafe/payload.pdf"
        with tempfile.TemporaryDirectory() as directory:
            validated = validate_local_file(
                self._file(directory),
                allowed_roots=[Path(directory).resolve()],
                allowed_extensions=[".pdf"],
                max_bytes=100,
            )
            with patch(
                "ipad_agent.airdrop.subprocess.Popen",
                side_effect=KeyboardInterrupt(f"cancelled while launching {private}"),
            ) as popen:
                result = _run_one_attempt(
                    ["helper"],
                    validated=validated,
                    timeout_seconds=1,
                    receiver=None,
                    accessibility_selector=None,
                    selector_timeout_seconds=0.5,
                )

        self.assertEqual(1, popen.call_count)
        self.assertEqual("uncertain", result["status"])
        self.assertEqual("unknown", result["dispatch"])
        self.assertNotIn(private, json.dumps(result))

    def test_semantic_entry_point_is_disabled_without_complete_policy(self):
        with patch("ipad_agent.config.load_config", return_value=Config()):
            result = airdrop("/does/not/matter.pdf")
        self.assertFalse(result["ok"])
        self.assertIn("disabled", result["error"])

    def test_semantic_entry_point_uses_only_configured_policy(self):
        config = Config(
            airdrop_allowed_roots=["/canonical/root"],
            airdrop_allowed_extensions=[".pdf"],
            airdrop_max_bytes=123,
            airdrop_timeout_seconds=9,
        )
        completed = {
            "schema": "ipad-agent.airdrop-result/v1",
            "status": "completed",
            "nominal_source_bytes": 4,
            "elapsed_seconds": 2.0,
            "nominal_source_bytes_per_second": 2.0,
        }
        with patch("ipad_agent.config.load_config", return_value=config), patch(
            "ipad_agent.airdrop.send_file", return_value=completed
        ) as sender:
            result = airdrop("/canonical/root/file.pdf")
        self.assertTrue(result["ok"])
        sender.assert_called_once_with(
            "/canonical/root/file.pdf",
            allowed_roots=["/canonical/root"],
            allowed_extensions=[".pdf"],
            max_bytes=123,
            timeout_seconds=9,
        )

    def test_semantic_airdrop_errors_are_stable_and_redacted(self):
        config = Config(
            airdrop_allowed_roots=["/canonical/root"],
            airdrop_allowed_extensions=[".pdf"],
            airdrop_max_bytes=123,
        )
        private = "/private/project/.runtime/airdrop/attempts/deadbeef/payload.pdf"
        for error_type in (
            AirDropError, AirDropValidationError, AirDropBuildError, AirDropSnapshotError,
        ):
            with self.subTest(error_type=error_type.__name__), patch(
                "ipad_agent.config.load_config", return_value=config
            ), patch(
                "ipad_agent.airdrop.send_file",
                side_effect=error_type(f"failed for {private} identifier=deadbeef"),
            ):
                result = airdrop("/canonical/root/file.pdf")

            self.assertEqual("AirDrop request failed before dispatch", result["error"])
            self.assertFalse(result["uncertain"])
            self.assertNotIn(private, json.dumps(result))
            self.assertNotIn("deadbeef", json.dumps(result))

    def test_semantic_helper_failures_drop_nested_private_text(self):
        config = Config(
            airdrop_allowed_roots=["/canonical/root"],
            airdrop_allowed_extensions=[".pdf"],
            airdrop_max_bytes=123,
        )
        private = "/private/project/.runtime/airdrop/attempts/feedface/payload.pdf"
        for dispatch, expected in (
            ("not_attempted", "AirDrop request failed before dispatch"),
            ("attempted", "AirDrop attempt failed"),
        ):
            failed = {
                "schema": "ipad-agent.airdrop-result/v1",
                "status": "failed",
                "dispatch": dispatch,
                "error": f"helper failed for {private} identifier=feedface",
                "diagnostics": {
                    "reason": f"recovery snapshot {private}",
                    "children": [f"attempt feedface at {private}"],
                },
            }
            with self.subTest(dispatch=dispatch), patch(
                "ipad_agent.config.load_config", return_value=config
            ), patch("ipad_agent.airdrop.send_file", return_value=failed):
                result = airdrop("/canonical/root/file.pdf")

            rendered = json.dumps(result)
            self.assertEqual(expected, result["error"])
            self.assertFalse(result["uncertain"])
            self.assertNotIn("diagnostics", result)
            self.assertNotIn(private, rendered)
            self.assertNotIn("feedface", rendered)

    def test_semantic_uncertain_result_redacts_private_attempt_details(self):
        config = Config(
            airdrop_allowed_roots=["/canonical/root"],
            airdrop_allowed_extensions=[".pdf"],
            airdrop_max_bytes=123,
        )
        private_path = "/private/project/.runtime/airdrop/attempts/deadbeef/payload.pdf"
        attempt_id = "deadbeef" * 4
        uncertain = {
            "schema": "ipad-agent.airdrop-result/v1",
            "status": "uncertain",
            "dispatch": "unknown",
            "reason": f"helper lost response for {private_path} ({attempt_id})",
            "attempt_id": attempt_id,
            "snapshot_path": private_path,
            "snapshot_retained": True,
            "diagnostics": {
                "message": f"private recovery path {private_path}",
                "children": [f"attempt identifier {attempt_id}"],
            },
        }
        with patch("ipad_agent.config.load_config", return_value=config), patch(
            "ipad_agent.airdrop.send_file", return_value=uncertain
        ):
            result = airdrop("/canonical/root/file.pdf")

        rendered = json.dumps(result)
        self.assertFalse(result["ok"])
        self.assertTrue(result["uncertain"])
        self.assertTrue(result["snapshot_retained"])
        self.assertEqual("AirDrop outcome is unknown", result["reason"])
        self.assertNotIn("attempt_id", result)
        self.assertNotIn("snapshot_path", result)
        self.assertNotIn("diagnostics", result)
        self.assertNotIn(private_path, rendered)
        self.assertNotIn(attempt_id, rendered)

    def test_semantic_completed_result_redacts_cleanup_failure_details(self):
        config = Config(
            airdrop_allowed_roots=["/canonical/root"],
            airdrop_allowed_extensions=[".pdf"],
            airdrop_max_bytes=123,
        )
        private_path = "/private/project/.runtime/airdrop/attempts/cafebabe/payload.pdf"
        completed = {
            "schema": "ipad-agent.airdrop-result/v1",
            "status": "completed",
            "attempt_id": "cafebabe" * 4,
            "snapshot_path": private_path,
            "snapshot_retained": True,
            "snapshot_cleanup_error": f"could not remove {private_path}: permission denied",
        }
        with patch("ipad_agent.config.load_config", return_value=config), patch(
            "ipad_agent.airdrop.send_file", return_value=completed
        ):
            result = airdrop("/canonical/root/file.pdf")

        rendered = json.dumps(result)
        self.assertTrue(result["ok"])
        self.assertTrue(result["snapshot_retained"])
        self.assertNotIn("attempt_id", result)
        self.assertNotIn("snapshot_path", result)
        self.assertNotIn("snapshot_cleanup_error", result)
        self.assertNotIn(private_path, rendered)

    def test_airdrop_config_requires_complete_narrow_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                '[airdrop]\nallowed_roots = ["/tmp"]\n'
                'allowed_extensions = [".pdf"]\nmax_bytes = 100\ntimeout_seconds = 30\n'
            )
            config = load_config(path)
            self.assertEqual(["/tmp"], config.airdrop_allowed_roots)
            self.assertEqual([".pdf"], config.airdrop_allowed_extensions)
            self.assertEqual(100, config.airdrop_max_bytes)
            self.assertEqual(30, config.airdrop_timeout_seconds)

    def test_target_receiver_requires_exact_fail_closed_selector(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._file(directory)
            helper = Path(directory).resolve() / "helper"
            helper.write_text("mock")
            helper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            with self.assertRaisesRegex(AirDropValidationError, "configured together"):
                send_file(
                    path,
                    allowed_roots=[Path(directory).resolve()],
                    allowed_extensions=[".pdf"],
                    max_bytes=100,
                    helper_path=helper,
                    target_receiver="Test iPad",
                )

    def test_selector_must_prove_one_exact_label(self):
        selector = Mock()
        selector.select_exact_receiver.return_value = AccessibilitySelection(
            requested_receiver="Test iPad",
            observed_label="Someone else",
            exact_match_count=1,
            activated=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            validated = validate_local_file(
                self._file(directory),
                allowed_roots=[Path(directory).resolve()],
                allowed_extensions=[".pdf"],
                max_bytes=100,
            )
        process = _FakeProcess([{
            "event": "dispatching",
            "attempt_id": "0" * 32,
            "snapshot_path": str(validated.path),
            "nominal_source_bytes": 4,
        }])
        with patch("ipad_agent.airdrop.subprocess.Popen", return_value=process):
            result = _run_one_attempt(
                ["helper"],
                validated=validated,
                timeout_seconds=1,
                receiver="Test iPad",
                accessibility_selector=selector,
                selector_timeout_seconds=0.5,
            )
        self.assertEqual("uncertain", result["status"])
        self.assertEqual("failed_closed", result["receiver_selection"])
        selector.select_exact_receiver.assert_called_once()

    def test_native_source_uses_official_service_once_and_builds_only_to_runtime(self):
        source = HELPER_SOURCE.read_text()
        build = HELPER_BUILD_SCRIPT.read_text()
        self.assertIn("NSSharingService(named: .sendViaAirDrop)", source)
        self.assertEqual(1, source.count("service.perform(withItems:"))
        self.assertIn("didShareItems", source)
        self.assertIn("didFailToShareItems", source)
        self.assertIn("MNT_LOCAL", source)
        self.assertIn("NSApplication.shared", source)
        self.assertIn("application.finishLaunching()", source)
        self.assertLess(
            source.index('"event": "dispatching"'),
            source.index("service.perform(withItems:"),
        )
        self.assertIn('"nominal_source_bytes"', source)
        self.assertNotIn("WebDriverAgent", source)
        self.assertNotIn("cliclick", source)
        self.assertIn('runtime_root="$repo_root/.runtime"', build)
        self.assertIn('output="$runtime_dir/airdrop-share"', build)
        self.assertNotIn('output="$repo_root/native/', build)


if __name__ == "__main__":
    unittest.main()
