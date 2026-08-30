import json
from pathlib import Path
import shutil
import tempfile
import unittest

from ipad_agent.registry import (
    AddonNotEnabledError,
    CORE_INTEGRATIONS,
    IntegrationRegistry,
    RegistryError,
    load_registry,
)


ROOT = Path(__file__).resolve().parents[1]


class IntegrationRegistryV1Tests(unittest.TestCase):
    def test_default_registry_has_only_fixed_core_integrations(self):
        registry = load_registry()
        self.assertEqual(CORE_INTEGRATIONS, frozenset(registry.integrations))
        self.assertEqual("com.apple.Maps", registry.resolve_bundle("  APPLE_maps "))
        self.assertEqual("settings", registry.resolve("com.apple.Preferences").id)

    def test_selectors_resolve_by_alias_bundle_and_qualified_name(self):
        registry = load_registry()
        expected = {
            "using": "accessibility id",
            "value": "com.apple.settings.wifi",
            "_bundle": "com.apple.Preferences",
            "_integration": "settings",
            "_selector": "wifi",
        }
        self.assertEqual(expected, registry.resolve_selector("settings.wifi"))
        self.assertEqual(expected, registry.resolve_selector("com.apple.Preferences", "WIFI"))

    def test_brave_requires_explicit_addon_enablement(self):
        with self.assertRaises(AddonNotEnabledError):
            load_registry().resolve("com.brave.ios.browser")
        registry = load_registry(enabled_addons={"brave"})
        self.assertEqual(frozenset({"brave"}), registry.enabled_addons)
        self.assertEqual("brave", registry.resolve("Brave Browser").id)
        selector = registry.resolve_selector("brave.address")
        self.assertEqual("-ios predicate string", selector["using"])
        self.assertEqual("name == 'url'", selector["value"])

    def test_unlisted_directories_are_not_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "project"
            shutil.copytree(ROOT / "integrations", copy / "integrations")
            shutil.copytree(ROOT / "addons", copy / "addons")
            ignored = copy / "integrations" / "not-indexed" / "integration.json"
            ignored.parent.mkdir()
            ignored.write_text("not json", encoding="utf-8")
            registry = IntegrationRegistry(copy / "integrations" / "index.json")
            self.assertNotIn("not-indexed", registry.integrations)

    def test_duplicate_json_keys_and_duplicate_aliases_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "project"
            shutil.copytree(ROOT / "integrations", copy / "integrations")
            shutil.copytree(ROOT / "addons", copy / "addons")
            index_path = copy / "integrations" / "index.json"
            original = index_path.read_text(encoding="utf-8")
            index_path.write_text(original.replace('"version": 1,', '"version": 1,\n  "version": 1,'), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "duplicate JSON key"):
                IntegrationRegistry(index_path)

            index_path.write_text(original, encoding="utf-8")
            brave_path = copy / "addons" / "brave" / "integration.json"
            brave = json.loads(brave_path.read_text(encoding="utf-8"))
            brave["aliases"].append("Apple Maps")
            brave_path.write_text(json.dumps(brave), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "duplicate integration alias"):
                IntegrationRegistry(index_path, enabled_addons={"brave"})

    def test_unknown_fields_and_unknown_addons_are_rejected(self):
        with self.assertRaisesRegex(RegistryError, "unknown addon"):
            load_registry(enabled_addons={"ghost"})
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "project"
            shutil.copytree(ROOT / "integrations", copy / "integrations")
            shutil.copytree(ROOT / "addons", copy / "addons")
            manifest_path = copy / "integrations" / "maps" / "integration.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["implementation"] = "dynamic.module"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "unknown fields"):
                IntegrationRegistry(copy / "integrations" / "index.json")


if __name__ == "__main__":
    unittest.main()
