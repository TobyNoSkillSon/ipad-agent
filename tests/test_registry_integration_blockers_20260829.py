import json
from pathlib import Path
import shutil
import tempfile
import unittest

from ipad_agent.config import Config, ConfigError, config_from_snapshot, config_snapshot
from ipad_agent.registry import AddonNotEnabledError, IntegrationRegistry, RegistryError, load_registry


ROOT = Path(__file__).resolve().parents[1]


class RegistryIntegrationBlockers20260829Tests(unittest.TestCase):
    def _copy_registry(self, directory: str) -> Path:
        project = Path(directory) / "project"
        shutil.copytree(ROOT / "integrations", project / "integrations")
        shutil.copytree(ROOT / "schemas", project / "schemas")
        return project / "integrations" / "index.json"

    def test_disabled_addon_manifest_is_never_opened_or_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            index = self._copy_registry(directory)
            expected = {entry["id"] for entry in json.loads(index.read_text())["integrations"] if entry["kind"] == "core"}
            addon = index.parent.parent / "integrations" / "brave" / "integration.json"
            addon.write_text("not json", encoding="utf-8")
            registry = IntegrationRegistry(index)
            self.assertEqual(expected, set(registry))
            with self.assertRaises(AddonNotEnabledError):
                registry.resolve("com.brave.ios.browser")
            with self.assertRaisesRegex(RegistryError, "cannot load"):
                IntegrationRegistry(index, enabled_addons=["brave"])

    def test_known_addon_bundle_cannot_use_low_level_alias(self):
        with self.assertRaisesRegex(ConfigError, "disabled addon 'brave'"):
            Config(bundle_aliases={"private-browser": "com.brave.ios.browser"})

        configured = Config(
            browser="brave",
            enabled_addons=["brave"],
            bundle_aliases={"brave-low-level": "com.brave.ios.browser"},
        )
        self.assertEqual("com.brave.ios.browser", configured.browser_bundle)

    def test_config_snapshot_v3_round_trips_without_browser_bundle_state(self):
        original = Config(browser="brave", enabled_addons=["brave"])
        snapshot = config_snapshot(original)
        self.assertEqual("ipad-agent.config-snapshot/v3", snapshot["schema"])
        self.assertNotIn("browser_bundle_override", snapshot)
        restored = config_from_snapshot(snapshot)
        self.assertEqual("com.brave.ios.browser", restored.browser_bundle)

        legacy = dict(snapshot)
        legacy["schema"] = "ipad-agent.config-snapshot/v2"
        legacy["browser_bundle_override"] = "org.example.external-browser"
        with self.assertRaisesRegex(ConfigError, "legacy browser bundle overrides"):
            config_from_snapshot(legacy)

    def test_registry_rejects_prose_classes_wrong_step_fields_and_hyphen_placeholders(self):
        mutations = (
            (lambda manifest: manifest["actions"]["open-search"].__setitem__("safety", "navigation prose"), "safety must be one of"),
            (lambda manifest: manifest["actions"]["activate"]["steps"][0].__setitem__("seconds", 1), "not valid for activate"),
            (lambda manifest: manifest["actions"]["open-search"]["steps"][0].__setitem__("value", "maps://?q={encoded-query}"), "unsupported placeholder"),
        )
        for mutate, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                index = self._copy_registry(directory)
                path = index.parent / "apple_maps" / "integration.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                mutate(manifest)
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(RegistryError, message):
                    IntegrationRegistry(index)

    def test_clock_and_reload_have_state_gates_and_compatibility_is_unverified(self):
        clock = load_registry().resolve("clock")
        self.assertEqual(clock["selectors"], {})
        self.assertEqual(set(clock["actions"]), {"activate"})
        self.assertEqual(set(clock["scenarios"]), {"activate-direct"})
        brave = load_registry(enabled_addons=["brave"]).resolve("brave")
        self.assertEqual(brave["selectors"], {})
        self.assertNotIn("reload-page", brave["actions"])
        for integration in [*load_registry().integrations.values(), brave]:
            self.assertEqual("unverified", integration["compatibility"]["verification"])
            self.assertEqual([], integration["compatibility"]["app_versions"])


if __name__ == "__main__":
    unittest.main()
