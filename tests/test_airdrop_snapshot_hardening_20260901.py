from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from ipad_agent.airdrop import (
    AirDropSnapshotError,
    AttemptSnapshot,
    _create_attempt_snapshot,
    _run_one_attempt,
    send_file,
    validate_local_file,
)

from tests.test_airdrop_v1 import _FakeProcess


class AirDropSnapshotHardeningTests(unittest.TestCase):
    def _validated(self, directory: str, name: str = "report final.PDF"):
        root = Path(directory).resolve()
        path = root / name
        path.write_bytes(b"fixed source bytes")
        return validate_local_file(
            path,
            allowed_roots=[root],
            allowed_extensions=[".pdf"],
            max_bytes=1024,
        )

    def test_bounded_fd_fallback_creates_private_same_basename_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._validated(directory)
            with patch("ipad_agent.airdrop._clone_from_fd", return_value=""):
                snapshot = _create_attempt_snapshot(
                    source,
                    attempt_id=uuid.uuid4().hex,
                    deadline=time.monotonic() + 2,
                )
            try:
                self.assertEqual(source.path.name, snapshot.file.path.name)
                self.assertEqual(b"fixed source bytes", snapshot.file.path.read_bytes())
                self.assertEqual("bounded_fd_copy", snapshot.method)
                self.assertEqual(0, stat.S_IMODE(snapshot.directory.stat().st_mode) & 0o077)
                self.assertEqual(0, stat.S_IMODE(snapshot.file.path.stat().st_mode) & 0o077)
                self.assertNotEqual(source.inode, snapshot.file.inode)
            finally:
                snapshot.file.path.unlink(missing_ok=True)
                snapshot.directory.rmdir()

    def test_replaced_source_is_rejected_before_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._validated(directory)
            replacement = source.path.with_name("replacement.PDF")
            replacement.write_bytes(b"fixed source bytes")
            os.replace(replacement, source.path)
            attempt_id = uuid.uuid4().hex
            with self.assertRaisesRegex(AirDropSnapshotError, "source changed"):
                _create_attempt_snapshot(
                    source,
                    attempt_id=attempt_id,
                    deadline=time.monotonic() + 2,
                )
            self.assertFalse(
                (Path(__file__).resolve().parents[1] / ".runtime" / "airdrop" / "attempts" / attempt_id).exists()
            )

    def test_same_inode_content_change_is_rejected_before_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._validated(directory)
            source.path.write_bytes(b"changed same size!")
            self.assertEqual(source.size, source.path.stat().st_size)
            attempt_id = uuid.uuid4().hex
            with self.assertRaisesRegex(AirDropSnapshotError, "source changed"):
                _create_attempt_snapshot(
                    source,
                    attempt_id=attempt_id,
                    deadline=time.monotonic() + 2,
                )

    def test_send_passes_snapshot_to_helper_and_cleans_after_completion(self):
        captured: dict[str, object] = {}

        def complete(arguments, **kwargs):
            validated = kwargs["validated"]
            captured["path"] = validated.path
            captured["arguments"] = arguments
            self.assertTrue(validated.path.exists())
            self.assertEqual(b"fixed source bytes", validated.path.read_bytes())
            return {
                "schema": "ipad-agent.airdrop-result/v1",
                "status": "completed",
                "attempts": 1,
                "dispatch": "attempted",
                "callback": "completed",
            }

        with tempfile.TemporaryDirectory() as directory, patch(
            "ipad_agent.airdrop.build_helper", return_value=Path("/unused/mock-helper")
        ), patch("ipad_agent.airdrop._clone_from_fd", return_value=""), patch(
            "ipad_agent.airdrop._run_one_attempt", side_effect=complete
        ):
            source = self._validated(directory)
            result = send_file(
                source.path,
                allowed_roots=[Path(directory).resolve()],
                allowed_extensions=[".pdf"],
                max_bytes=1024,
                timeout_seconds=2,
            )

        snapshot_path = captured["path"]
        self.assertIsInstance(snapshot_path, Path)
        assert isinstance(snapshot_path, Path)
        self.assertEqual(source.path.name, snapshot_path.name)
        self.assertNotEqual(source.path, snapshot_path)
        self.assertIn(".runtime/airdrop/attempts/", str(snapshot_path))
        self.assertFalse(snapshot_path.exists())
        self.assertFalse(snapshot_path.parent.exists())
        self.assertFalse(result["snapshot_retained"])
        self.assertEqual(1, result["attempts"])

    def test_uncertain_attempt_retains_exact_snapshot_for_inspection(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "ipad_agent.airdrop.build_helper", return_value=Path("/unused/mock-helper")
        ), patch("ipad_agent.airdrop._clone_from_fd", return_value=""), patch(
            "ipad_agent.airdrop._run_one_attempt",
            return_value={
                "schema": "ipad-agent.airdrop-result/v1",
                "status": "uncertain",
                "attempts": 1,
                "dispatch": "unknown",
                "reason": "lost helper response",
                "receiver_selection": "unknown",
            },
        ):
            source = self._validated(directory)
            result = send_file(
                source.path,
                allowed_roots=[Path(directory).resolve()],
                allowed_extensions=[".pdf"],
                max_bytes=1024,
                timeout_seconds=2,
            )

        snapshot_path = Path(result["snapshot_path"])
        try:
            self.assertTrue(result["snapshot_retained"])
            self.assertTrue(snapshot_path.is_file())
            self.assertEqual(source.path.name, snapshot_path.name)
            self.assertEqual(b"fixed source bytes", snapshot_path.read_bytes())
        finally:
            snapshot_path.unlink(missing_ok=True)
            snapshot_path.parent.rmdir()

    def test_cancellation_before_helper_invocation_cleans_and_propagates(self):
        private = "/private/project/.runtime/airdrop/attempts/preinvoke/payload.pdf"
        with tempfile.TemporaryDirectory() as directory:
            source = self._validated(directory)
            snapshot = AttemptSnapshot(
                "a" * 32,
                Path(private).parent,
                source,
                "bounded_fd_copy",
            )
            with patch("ipad_agent.airdrop._require_runtime_executable"), patch(
                "ipad_agent.airdrop._create_attempt_snapshot", return_value=snapshot
            ), patch(
                "ipad_agent.airdrop._remaining",
                side_effect=[1.0, KeyboardInterrupt(f"cancelled before {private}")],
            ), patch("ipad_agent.airdrop._cleanup_snapshot", return_value=None) as cleanup, patch(
                "ipad_agent.airdrop._run_one_attempt"
            ) as run:
                with self.assertRaises(KeyboardInterrupt):
                    send_file(
                        source.path,
                        allowed_roots=[Path(directory).resolve()],
                        allowed_extensions=[".pdf"],
                        max_bytes=1024,
                        timeout_seconds=2,
                        helper_path=Path("/mock/runtime/helper"),
                    )

        cleanup.assert_called_once_with(snapshot)
        run.assert_not_called()

    def test_cancellation_at_helper_boundary_is_uncertain_and_retains_snapshot(self):
        private = "/private/project/.runtime/airdrop/attempts/postinvoke/payload.pdf"
        with tempfile.TemporaryDirectory() as directory:
            source = self._validated(directory)
            snapshot = AttemptSnapshot(
                "b" * 32,
                Path(private).parent,
                source,
                "bounded_fd_copy",
            )
            with patch("ipad_agent.airdrop._require_runtime_executable"), patch(
                "ipad_agent.airdrop._create_attempt_snapshot", return_value=snapshot
            ), patch("ipad_agent.airdrop._remaining", return_value=1.0), patch(
                "ipad_agent.airdrop._run_one_attempt",
                side_effect=KeyboardInterrupt(f"cancelled after invoking {private}"),
            ) as run, patch("ipad_agent.airdrop._cleanup_snapshot") as cleanup:
                result = send_file(
                    source.path,
                    allowed_roots=[Path(directory).resolve()],
                    allowed_extensions=[".pdf"],
                    max_bytes=1024,
                    timeout_seconds=2,
                    helper_path=Path("/mock/runtime/helper"),
                )

        self.assertEqual(1, run.call_count)
        cleanup.assert_not_called()
        self.assertEqual("uncertain", result["status"])
        self.assertEqual("unknown", result["dispatch"])
        self.assertTrue(result["snapshot_retained"])
        self.assertEqual(str(source.path), result["snapshot_path"])
        self.assertNotIn(private, result["reason"])

    def test_helper_loss_before_observed_marker_is_unknown_not_pre_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            validated = self._validated(directory)
        process = _FakeProcess([], returncode=9)
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
        self.assertEqual("unknown", result["dispatch"])
        self.assertEqual(1, result["attempts"])


if __name__ == "__main__":
    unittest.main()
