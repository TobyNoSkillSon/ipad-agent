from pathlib import Path
import os
from unittest.mock import patch
import tempfile
import unittest

from ipad_agent.config import load_config


class ConfigTests(unittest.TestCase):
    def test_toml_loads_portable_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("""[device]
id = "device-1"
[apps]
browser = "safari"
[apps.aliases]
reader = "org.example.reader"
[display]
port = 9000
[automation]
team_id = "TEAM"
""")
            config = load_config(path)
        self.assertEqual("device-1", config.device)
        self.assertEqual("safari", config.browser)
        self.assertEqual(9000, config.display_port)
        self.assertEqual({"reader": "org.example.reader"}, config.app_aliases)

    def test_environment_overrides_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[device]\nid = \"file-device\"\n")
            with patch.dict(os.environ, {"IPAD_AGENT_DEVICE": "env-device", "IPAD_AGENT_DISPLAY_PORT": "9001"}):
                config = load_config(path)
        self.assertEqual("env-device", config.device)
        self.assertEqual(9001, config.display_port)


if __name__ == "__main__":
    unittest.main()
