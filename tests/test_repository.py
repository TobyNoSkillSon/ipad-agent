from pathlib import Path
import unittest
from unittest.mock import patch

from ipad_agent import display, runtime


class RepositoryLayoutTests(unittest.TestCase):
    def test_package_is_repository_native(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            root / "ipad_agent" / "runtime", Path(runtime.__file__).resolve().parent
        )
        self.assertFalse((root / "src").exists())

    def test_daemon_starts_from_repository_root(self):
        root = Path(__file__).resolve().parents[1]
        with (
            patch.object(runtime, "_client_socket_path", return_value=Path("/tmp/ipad-agent-test.sock")),
            patch.object(runtime, "_client_daemon_running", return_value=True),
            patch.object(runtime.subprocess, "Popen") as popen,
        ):
            self.assertTrue(runtime._client_start_daemon())
        command = popen.call_args.args[0]
        self.assertEqual(
            [runtime.sys.executable, "-m", "ipad_agent.runtime.daemon"], command[:3]
        )
        self.assertEqual(str(root), popen.call_args.kwargs["cwd"])

    def test_display_server_uses_repository_module(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual("ipad_agent.runtime.server", display.SERVER_MODULE)
        self.assertEqual(root, display.REPOSITORY_ROOT)


if __name__ == "__main__":
    unittest.main()
