from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ExecutableEntrypointsStage4Tests(unittest.TestCase):
    def _probe(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            arguments,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_historical_daemon_module_help(self) -> None:
        completed = self._probe(sys.executable, "-m", "ipad_agent.daemon", "--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("ipad-agent-daemon", completed.stdout)
        self.assertIn("--idle-ttl", completed.stdout)

    def test_historical_runtime_module_help(self) -> None:
        completed = self._probe(sys.executable, "-m", "ipad_agent.runtime", "--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("persistent iPad CoreDevice/XCTest runtime", completed.stdout)
        self.assertIn("--socket", completed.stdout)

    def test_historical_server_path_is_directly_executable(self) -> None:
        entry = ROOT / "ipad_agent/server.py"
        self.assertTrue(os.access(entry, os.X_OK))
        completed = self._probe(str(entry), "--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--host", completed.stdout)
        self.assertIn("--runtime-dir", completed.stdout)


if __name__ == "__main__":
    unittest.main()
