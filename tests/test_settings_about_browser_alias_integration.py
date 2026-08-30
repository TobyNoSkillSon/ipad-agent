from pathlib import Path
import tempfile
import unittest

from ipad_agent.config import Config, ConfigError, config_snapshot, load_config
from ipad_agent.registry import load_registry


class SettingsAboutBrowserAliasIntegrationTests(unittest.TestCase):
    def test_about_selector_matches_semantic_command_key_and_action_is_bounded(self):
        registry = load_registry()
        selector = registry.resolve_selector("settings", "accessibility id=About")
        self.assertEqual("accessibility id", selector["using"])
        self.assertEqual("About", selector["value"])
        self.assertFalse(selector["cache"])
        self.assertEqual("settings", selector["_integration"])
        self.assertEqual("accessibility id=About", selector["_selector"])

        action = registry.resolve("settings")["actions"]["open-about"]
        self.assertEqual(
            [
                {"operation": "tap", "selector": "general"},
                {"operation": "wait", "selector": "accessibility id=About", "seconds": 5},
                {"operation": "tap", "selector": "accessibility id=About"},
            ],
            action["steps"],
        )
        self.assertFalse(registry.resolve("settings")["safety"]["mutates_user_data"])

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
