from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from ipad_agent.airdrop import HELPER_SOURCE


class AirDropCallbackClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        temporary = Path(cls._temporary.name)
        harness = temporary / "main.swift"
        cls._binary = temporary / "callback-classification"
        harness.write_text(
            HELPER_SOURCE.read_text()
            + r'''
import Foundation

let mode = CommandLine.arguments[1]
let items: [Any] = mode.hasSuffix("empty") ? [] : ["differently bridged callback item"]
let service = NSSharingService(title: "callback test", image: NSImage(), alternateImage: nil) { }
let delegate = ShareDelegate(
    nominalSourceBytes: 1061,
    dispatchStarted: ProcessInfo.processInfo.systemUptime
)
if mode.hasPrefix("completed") {
    delegate.sharingService(service, didShareItems: items)
} else {
    let error = NSError(
        domain: "AirDropLiveFailure",
        code: 73,
        userInfo: [NSLocalizedDescriptionKey: "picker reported failure"]
    )
    delegate.sharingService(service, didFailToShareItems: items, error: error)
}
let data = try! JSONSerialization.data(withJSONObject: delegate.result!, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
'''
        )
        completed = subprocess.run(
            [
                "/usr/bin/xcrun",
                "--sdk",
                "macosx",
                "swiftc",
                "-D",
                "AIRDROP_CALLBACK_TESTING",
                "-framework",
                "AppKit",
                str(harness),
                "-o",
                str(cls._binary),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"callback harness did not compile: {completed.stderr}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _classify(self, mode: str) -> dict[str, object]:
        completed = subprocess.run(
            [str(self._binary), mode],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return json.loads(completed.stdout)

    def test_empty_callback_items_keep_host_completion_and_failure_classification(self):
        completion = self._classify("completed-empty")
        self.assertEqual("completed", completion["event"])
        self.assertEqual(1061, completion["nominal_source_bytes"])
        self.assertGreaterEqual(completion["elapsed_seconds"], 0)

        failure = self._classify("failed-empty")
        self.assertEqual("failed", failure["event"])
        self.assertEqual("picker reported failure", failure["message"])
        self.assertEqual("AirDropLiveFailure", failure["error_domain"])
        self.assertEqual(73, failure["error_code"])

    def test_non_url_callback_items_keep_host_completion_and_failure_classification(self):
        completion = self._classify("completed-non-url")
        self.assertEqual("completed", completion["event"])
        self.assertEqual(1061, completion["nominal_source_bytes"])

        failure = self._classify("failed-non-url")
        self.assertEqual("failed", failure["event"])
        self.assertEqual("picker reported failure", failure["message"])
        self.assertEqual("AirDropLiveFailure", failure["error_domain"])
        self.assertEqual(73, failure["error_code"])


if __name__ == "__main__":
    unittest.main()
