import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ipad_agent.config import Config, ConfigError, apply_environment, load_config
from ipad_agent import paths


class StrictLazyConfigTests(unittest.TestCase):
    def _config_file(self, directory: str, content: str, *, mode: int = 0o600) -> Path:
        path = Path(directory) / "config.toml"
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)
        return path

    def setUp(self):
        self._fixture_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._fixture_directory.cleanup)
        self._default_fixture = self._config_file(
            self._fixture_directory.name,
            '[device]\nid = "fixture-device"\n[display]\nport = 9007\n',
        )
        self._default_path_patch = patch(
            "ipad_agent.config.DEFAULT_CONFIG_PATH", self._default_fixture
        )
        self._default_path_patch.start()
        self.addCleanup(self._default_path_patch.stop)

    def test_defaults_are_repository_local_and_lazy(self):
        existed = paths.RUNTIME_ROOT.exists()
        config = load_config(environ={})
        self.assertEqual("safari", config.browser)
        self.assertEqual([], config.enabled_addons)
        self.assertEqual("fixture-device", config.device)
        self.assertEqual(9007, config.display_port)
        self.assertEqual(paths.REPO_ROOT / ".runtime/config/config.toml", paths.DEFAULT_CONFIG_PATH)
        self.assertEqual(existed, paths.RUNTIME_ROOT.exists())

    def test_toml_is_strict_but_addon_names_are_deferred(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._config_file(
                directory,
                """[apps]
browser = "safari"
[apps.aliases]
reader = "org.example.reader"
[addons]
enabled = ["not-installed-yet"]
[display]
host = "192.168.10.5"
port = 9000
""",
            )
            config = load_config(path, environ={})
            self.assertEqual(["not-installed-yet"], config.enabled_addons)
            self.assertEqual({"reader": "org.example.reader"}, config.bundle_aliases)

            unknown = self._config_file(directory, "[display]\nporrt = 9000\n")
            with self.assertRaisesRegex(ConfigError, "unknown display"):
                load_config(unknown, environ={})
            wrong_type = self._config_file(directory, "[display]\nport = \"9000\"\n")
            with self.assertRaisesRegex(ConfigError, "must be an integer"):
                load_config(wrong_type, environ={})

    def test_environment_overrides_are_typed_and_do_not_mutate_environ(self):
        source = {
            "IPAD_AGENT_BROWSER": "safari",
            "IPAD_AGENT_ENABLED_ADDONS": '["alpha","future-addon"]',
            "IPAD_AGENT_BUNDLE_ALIASES": '{"reader":"org.example.reader"}',
            "IPAD_AGENT_DISPLAY_PORT": "9001",
            "IPAD_AGENT_DISPLAY_HOST": "10.2.3.4",
        }
        config = load_config(environ=source)
        self.assertEqual(9001, config.display_port)
        self.assertEqual(["alpha", "future-addon"], config.enabled_addons)
        self.assertEqual({"reader": "org.example.reader"}, config.bundle_aliases)

        before = dict(os.environ)
        generated = apply_environment(Config(device="device-1"))
        self.assertEqual(before, dict(os.environ))
        self.assertEqual("device-1", generated["IPAD_AGENT_DEVICE"])

        with self.assertRaisesRegex(ConfigError, "decimal integer"):
            load_config(environ={"IPAD_AGENT_DISPLAY_PORT": "1.5"})
        with self.assertRaisesRegex(ConfigError, "list of strings"):
            load_config(environ={"IPAD_AGENT_ENABLED_ADDONS": '"alpha"'})
        with self.assertRaisesRegex(ConfigError, "duplicate key"):
            load_config(environ={"IPAD_AGENT_BUNDLE_ALIASES": '{"x":"one","x":"two"}'})

    def test_environment_selected_config_must_be_private_regular_and_not_symlinked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._config_file(directory, "[device]\nid = \"one\"\n", mode=0o644)
            with self.assertRaisesRegex(ConfigError, "owner-only"):
                load_config(environ={"IPAD_AGENT_CONFIG": str(path)})

            path.chmod(0o600)
            self.assertEqual("one", load_config(environ={"IPAD_AGENT_CONFIG": str(path)}).device)
            with patch("ipad_agent.config.descriptor_has_extended_acl", return_value=True):
                with self.assertRaisesRegex(ConfigError, "extended ACL"):
                    load_config(environ={"IPAD_AGENT_CONFIG": str(path)})

            link = Path(directory) / "linked.toml"
            link.symlink_to(path)
            with self.assertRaisesRegex(ConfigError, "symlink"):
                load_config(environ={"IPAD_AGENT_CONFIG": str(link)})

            with self.assertRaisesRegex(ConfigError, "regular file"):
                load_config(environ={"IPAD_AGENT_CONFIG": directory})

    def test_non_rfc1918_display_host_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._config_file(directory, '[display]\nhost = "127.0.0.1"\n')
            with self.assertRaisesRegex(ConfigError, "RFC1918"):
                load_config(path, environ={})


class ContainedPathTests(unittest.TestCase):
    def test_acl_detection_uses_the_macos_mode_marker(self):
        plain = subprocess.CompletedProcess([], 0, "-rw-------  1 user staff 1 date file\n", "")
        acl = subprocess.CompletedProcess([], 0, "-rw-------+ 1 user staff 1 date file\n", "")
        with patch.object(paths.subprocess, "run", return_value=plain):
            self.assertFalse(paths.has_extended_acl("/fixture"))
        with patch.object(paths.subprocess, "run", return_value=acl):
            self.assertTrue(paths.has_extended_acl("/fixture"))

    def test_containment_symlinks_and_private_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / ".runtime"
            with patch.object(paths, "RUNTIME_ROOT", runtime_root):
                self.assertEqual(runtime_root / "state/item", paths.runtime_path("state", "item"))
                with self.assertRaisesRegex(ValueError, "escapes"):
                    paths.runtime_path("..", "outside")

                written = paths.private_write_text("config/config.toml", "value = 1\n")
                self.assertEqual("value = 1\n", written.read_text(encoding="utf-8"))
                self.assertEqual(0o600, stat.S_IMODE(written.stat().st_mode))
                self.assertEqual(0o700, stat.S_IMODE(written.parent.stat().st_mode))

                link = runtime_root / "linked"
                link.symlink_to(Path(directory) / "outside", target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    paths.runtime_path("linked", "file")

                public = runtime_root / "public"
                public.mkdir(mode=0o755)
                with self.assertRaisesRegex(PermissionError, "not private"):
                    paths.private_mkdir(public / "child")


if __name__ == "__main__":
    unittest.main()
