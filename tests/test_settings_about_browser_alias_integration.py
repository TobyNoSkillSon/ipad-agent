from pathlib import Path
import tempfile
import unittest
from unittest import mock

from integrations.settings import commands as settings_commands
from ipad_agent import ipadsettings
from ipad_agent.config import Config, ConfigError, config_snapshot, load_config
from ipad_agent.registry import load_registry


class SettingsAboutBrowserAliasIntegrationTests(unittest.TestCase):
    def test_about_alias_uses_the_app_catalogue_and_shared_direct_dispatch(self):
        registry = load_registry()
        settings = registry.resolve("Apple Settings")
        self.assertEqual("settings", settings.id)
        self.assertEqual({}, settings["selectors"])
        self.assertEqual({}, settings["actions"])
        self.assertFalse(settings["safety"]["mutates_user_data"])

        route = settings_commands._load_catalog()["general-about"]
        self.assertEqual("normal", route["dispatch_policy"])
        self.assertEqual(
            "settings-navigation://com.apple.Settings.General/About",
            route["url"],
        )
        sentinel = object()
        with mock.patch.object(
            settings_commands.shared, "_direct_open", return_value=sentinel
        ) as direct_open:
            self.assertIs(ipadsettings("about"), sentinel)
        direct_open.assert_called_once_with("Settings", route["url"])

    def test_browser_alias_is_canonicalized_only_when_addon_is_enabled(self):
        config = Config(browser="Brave Browser", enabled_addons=["brave"])
        self.assertEqual("brave", config.browser)
        self.assertEqual("com.brave.ios.browser", config.browser_bundle)
        self.assertEqual("brave", config_snapshot(config)["browser"])

        disabled = Config(browser="Brave Browser")
        with self.assertRaisesRegex(ConfigError, "enabled browser integration ID"):
            _ = disabled.browser_bundle

    def test_toml_browser_alias_is_canonicalized_without_bypassing_enablement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                '[apps]\nbrowser = "Brave Browser"\n[addons]\nenabled = ["brave"]\n',
                encoding="utf-8",
            )
            self.assertEqual("brave", load_config(path, environ={}).browser)

            path.write_text('[apps]\nbrowser = "Brave Browser"\n', encoding="utf-8")
            configured_by_environment = load_config(
                path,
                environ={"IPAD_AGENT_ENABLED_ADDONS": '["brave"]'},
            )
            self.assertEqual("brave", configured_by_environment.browser)

            path.write_text(
                '[apps]\nbrowser = "Brave Browser"\n[addons]\nenabled = []\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "disabled addon"):
                load_config(path, environ={})


if __name__ == "__main__":
    unittest.main()
