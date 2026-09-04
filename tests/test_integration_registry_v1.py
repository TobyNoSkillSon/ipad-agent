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
    def test_default_registry_contains_every_required_core_integration(self):
        registry = load_registry()
        self.assertTrue(CORE_INTEGRATIONS <= frozenset(registry.integrations))
        self.assertEqual("com.apple.Maps", registry.resolve_bundle("  APPLE_maps "))
        self.assertEqual("settings", registry.resolve("com.apple.Preferences").id)

    def test_settings_is_indexed_exactly_without_selectors_or_wda_actions(self):
        registry = load_registry()
        settings = registry.resolve("settings")
        self.assertIs(settings, registry.resolve("Apple Settings"))
        self.assertIs(settings, registry.resolve("com.apple.Preferences"))
        self.assertEqual("settings", settings.id)
        self.assertEqual("core", settings.kind)
        self.assertEqual("com.apple.Preferences", settings.bundle_id)
        self.assertEqual(["exact-settings-url-navigation"], settings["capabilities"])
        self.assertEqual({}, settings["selectors"])
        self.assertEqual({}, settings["actions"])
        self.assertEqual({}, settings["scenarios"])
        with self.assertRaises(KeyError):
            registry.resolve_selector("settings.wifi")

        index = json.loads((ROOT / "integrations/index.json").read_text(encoding="utf-8"))
        indexed = [item for item in index["integrations"] if item["id"] == "settings"]
        self.assertEqual(
            indexed,
            [{
                "id": "settings",
                "kind": "core",
                "manifest": "settings/integration.json",
                "category": "application",
                "aliases": ["settings", "apple settings"],
                "bundle_ids": ["com.apple.Preferences"],
            }],
        )

    def test_brave_requires_explicit_addon_enablement(self):
        with self.assertRaises(AddonNotEnabledError):
            load_registry().resolve("com.brave.ios.browser")
        registry = load_registry(enabled_addons={"brave"})
        self.assertEqual(frozenset({"brave"}), registry.enabled_addons)
        brave = registry.resolve("Brave Browser")
        self.assertEqual("brave", brave.id)
        self.assertEqual(brave["selectors"], {})
        self.assertIn("open-search", brave["actions"])
        with self.assertRaises(KeyError):
            registry.resolve_selector("brave.address")

    def test_unlisted_directories_are_not_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "project"
            shutil.copytree(ROOT / "integrations", copy / "integrations")
            ignored = copy / "integrations" / "not-indexed" / "integration.json"
            ignored.parent.mkdir()
            ignored.write_text("not json", encoding="utf-8")
            registry = IntegrationRegistry(copy / "integrations" / "index.json")
            self.assertNotIn("not-indexed", registry.integrations)

    def test_new_indexed_package_needs_no_directory_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "project"
            shutil.copytree(ROOT / "integrations", copy / "integrations")
            package = copy / "integrations" / "example_package"
            package.mkdir()
            manifest = json.loads(
                (ROOT / "integrations/preview/integration.json").read_text(encoding="utf-8")
            )
            manifest.update({
                "id": "example-app",
                "name": "Example App",
                "kind": "core",
                "bundle_ids": ["org.example.IndexedApp"],
                "aliases": ["example-app"],
            })
            (package / "integration.json").write_text(
                json.dumps(manifest) + "\n", encoding="utf-8"
            )
            index_path = copy / "integrations/index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["integrations"].append({
                "id": "example-app",
                "kind": "core",
                "manifest": "example_package/integration.json",
                "category": "application",
                "aliases": ["example-app"],
                "bundle_ids": ["org.example.IndexedApp"],
            })
            index_path.write_text(json.dumps(index) + "\n", encoding="utf-8")
            registry = IntegrationRegistry(index_path)
            self.assertEqual(
                "org.example.IndexedApp", registry.resolve_bundle("example app")
            )

    def test_duplicate_json_keys_and_duplicate_aliases_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "project"
            shutil.copytree(ROOT / "integrations", copy / "integrations")
            index_path = copy / "integrations" / "index.json"
            original = index_path.read_text(encoding="utf-8")
            index_path.write_text(original.replace('"version": 1,', '"version": 1,\n  "version": 1,'), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "duplicate JSON key"):
                IntegrationRegistry(index_path)

            index_path.write_text(original, encoding="utf-8")
            brave_path = copy / "integrations" / "brave" / "integration.json"
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
            manifest_path = copy / "integrations" / "apple_maps" / "integration.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["implementation"] = "dynamic.module"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "unknown fields"):
                IntegrationRegistry(copy / "integrations" / "index.json")


if __name__ == "__main__":
    unittest.main()
