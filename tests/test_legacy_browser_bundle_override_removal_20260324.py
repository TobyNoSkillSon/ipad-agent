from pathlib import Path
import tempfile
import unittest

from ipad_agent.config import (
    Config,
    ConfigError,
    config_from_snapshot,
    config_snapshot,
    environment_for,
    load_config,
)
from ipad_agent.coredevice import _bundle_for_target
from ipad_agent.display import IPadShowError, _browser_identity
from ipad_agent.registry import AddonNotEnabledError, load_registry


class LegacyBrowserBundleOverrideRemovalTests(unittest.TestCase):
    def test_toml_override_is_rejected_with_migration_route(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                '[apps]\nbrowser = "safari"\nbrowser_bundle = "org.example.Browser"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ConfigError,
                r"apps\.browser_bundle.*apps\.browser.*integration ID.*low-level ip/open",
            ):
                load_config(path, environ={})

    def test_environment_override_is_rejected_even_when_empty(self):
        for value in ("org.example.Browser", ""):
            with self.subTest(value=value), self.assertRaisesRegex(
                ConfigError, r"integration ID.*IPAD_AGENT_BROWSER_BUNDLE"
            ):
                load_config(environ={"IPAD_AGENT_BROWSER_BUNDLE": value})

        with self.assertRaisesRegex(ConfigError, "IPAD_AGENT_BROWSER_BUNDLE"):
            environment_for(Config(), base={"IPAD_AGENT_BROWSER_BUNDLE": "stale"})
        self.assertNotIn("IPAD_AGENT_BROWSER_BUNDLE", environment_for(Config(), base={}))

    def test_legacy_snapshot_schemas_and_override_keys_are_rejected(self):
        current = config_snapshot(Config())
        self.assertEqual("ipad-agent.config-snapshot/v3", current["schema"])
        self.assertFalse(
            {"browser_bundle", "_browser_bundle", "browser_bundle_override", "_browser_bundle_override"}
            & current.keys()
        )
        self.assertEqual(Config(), config_from_snapshot(current))

        for key in (
            "browser_bundle",
            "_browser_bundle",
            "browser_bundle_override",
            "_browser_bundle_override",
        ):
            legacy = dict(current)
            legacy[key] = "org.example.Browser"
            with self.subTest(key=key), self.assertRaisesRegex(
                ConfigError, rf"legacy browser bundle overrides.*{key}"
            ):
                config_from_snapshot(legacy)

        for schema in ("ipad-agent.config-snapshot/v1", "ipad-agent.config-snapshot/v2"):
            legacy = dict(current)
            legacy["schema"] = schema
            with self.subTest(schema=schema), self.assertRaisesRegex(
                ConfigError, "legacy config snapshots.*apps.browser"
            ):
                config_from_snapshot(legacy)

    def test_now_browser_canonicalizes_enabled_registry_aliases(self):
        registry = load_registry()
        for reference in ("safari", "Safari", "Apple Safari"):
            with self.subTest(reference=reference):
                config = Config(browser=reference)
                self.assertEqual("safari", config.browser)
                self.assertEqual(
                    ("safari", "com.apple.mobilesafari"),
                    _browser_identity(config, registry),
                )

        invalid = (
            (Config(browser="com.apple.mobilesafari"), "integration ID 'safari'"),
            (Config(browser="maps"), "not a browser"),
            (
                Config(
                    browser="private-browser",
                    bundle_aliases={"private-browser": "org.example.Browser"},
                ),
                "enabled browser integration ID",
            ),
        )
        for config, message in invalid:
            with self.subTest(browser=config.browser), self.assertRaisesRegex(
                IPadShowError, message
            ):
                _browser_identity(config, registry)

        brave_registry = load_registry(enabled_addons=["brave"])
        self.assertEqual(
            ("brave", "com.brave.ios.browser"),
            _browser_identity(
                Config(browser="brave", enabled_addons=["brave"]), brave_registry
            ),
        )

    def test_exact_bundles_remain_a_low_level_route_only(self):
        registry = load_registry()
        config = Config()
        self.assertEqual(
            "org.example.Unindexed",
            _bundle_for_target("org.example.Unindexed", config, registry),
        )
        self.assertEqual(
            "com.brave.ios.browser",
            _bundle_for_target("com.brave.ios.browser", config, registry),
        )
        with self.assertRaises(AddonNotEnabledError):
            _bundle_for_target("brave", config, registry)
        with self.assertRaises(IPadShowError):
            _browser_identity(Config(browser="org.example.Unindexed"), registry)


if __name__ == "__main__":
    unittest.main()
