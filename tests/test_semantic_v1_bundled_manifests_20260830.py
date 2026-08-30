import json
from pathlib import Path
import unittest

from ipad_agent.lab.validation import validate_manifest
from ipad_agent.registry import CORE_INTEGRATIONS, load_registry
from scripts.release_check import validate_schema


ROOT = Path(__file__).resolve().parents[1]
NEW_IDS = ("preview", "books", "appstore")
BUNDLES = {
    "preview": "com.apple.Preview",
    "books": "com.apple.iBooks",
    "appstore": "com.apple.AppStore",
}


def load_manifest(integration_id):
    path = ROOT / "integrations" / integration_id / "integration.json"
    return json.loads(path.read_text(encoding="utf-8"))


class SemanticV1BundledManifests20260830Tests(unittest.TestCase):
    def test_bundled_candidates_are_fixed_core_integrations(self):
        registry = load_registry()
        self.assertEqual(
            {"preview", "books", "appstore"},
            set(NEW_IDS) & set(CORE_INTEGRATIONS),
        )
        for integration_id, bundle_id in BUNDLES.items():
            with self.subTest(integration_id=integration_id):
                integration = registry.resolve(integration_id)
                self.assertEqual("core", integration.kind)
                self.assertEqual(bundle_id, integration.bundle_id)
                self.assertEqual(integration_id, registry.resolve(bundle_id).id)
        self.assertEqual("appstore", registry.resolve("App Store").id)
        self.assertEqual("books", registry.resolve("iBooks").id)

    def test_new_manifests_pass_schema_and_strict_semantic_validation(self):
        schema = json.loads((ROOT / "schemas" / "integration-v1.json").read_text(encoding="utf-8"))
        for integration_id in NEW_IDS:
            with self.subTest(integration_id=integration_id):
                manifest = load_manifest(integration_id)
                validate_schema(manifest, schema, name=f"{integration_id} manifest")
                normalized = validate_manifest(
                    ROOT / "integrations" / integration_id / "integration.json"
                )
                self.assertEqual(integration_id, normalized["id"])
                self.assertEqual("unverified", normalized["compatibility"]["verification"])
                self.assertEqual([], normalized["compatibility"]["app_versions"])

    def test_preview_is_launch_only_and_makes_no_file_import_capability_claim(self):
        manifest = load_manifest("preview")
        self.assertEqual(["launch"], manifest["capabilities"])
        self.assertEqual({}, manifest["selectors"])
        self.assertEqual({"activate"}, set(manifest["actions"]))
        self.assertEqual(
            [{"operation": "activate"}],
            manifest["actions"]["activate"]["steps"],
        )
        exposed_ids = [
            *manifest["capabilities"],
            *manifest["actions"],
            *manifest["scenarios"],
        ]
        self.assertFalse(any("import" in value.casefold() for value in exposed_ids))
        prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
        self.assertIn("importing", prohibited)
        self.assertIn("document picker", prohibited)

    def test_books_and_appstore_navigation_uses_only_exact_fail_closed_selectors(self):
        books = load_manifest("books")
        for name, selector in books["selectors"].items():
            with self.subTest(integration="books", selector=name):
                self.assertEqual("-ios predicate string", selector["using"])
                value = selector["value"]
                self.assertIn("type == 'XCUIElementTypeButton'", value)
                self.assertIn("label == '", value)
                self.assertIn("visible == 1", value)
                self.assertIn("accessible == 1", value)
                for permissive in ("CONTAINS", "BEGINSWITH", "ENDSWITH", "MATCHES", " OR "):
                    self.assertNotIn(permissive, value)

        appstore = load_manifest("appstore")
        expected = {
            "today": "AppStore.tabBar.today",
            "games": "AppStore.tabBar.games",
            "apps": "AppStore.tabBar.apps",
            "arcade": "AppStore.tabBar.arcade",
            "search": "AppStore.tabBar.search",
        }
        self.assertEqual(expected, {name: item["value"] for name, item in appstore["selectors"].items()})
        self.assertTrue(all(item["using"] == "accessibility id" for item in appstore["selectors"].values()))

        for manifest in (books, appstore):
            for selector in manifest["selectors"].values():
                self.assertNotEqual("xpath", selector["using"].casefold())
            for action_name, action in manifest["actions"].items():
                with self.subTest(integration=manifest["id"], action=action_name):
                    self.assertTrue(all(step["operation"] in {"activate", "tap"} for step in action["steps"]))
            prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
            self.assertIn("protected confirmations", prohibited)

    def test_settings_recipes_remain_safe_navigation_without_protected_confirmation(self):
        settings = load_manifest("settings")
        self.assertEqual(
            {
                "activate", "open-general", "open-about", "open-wifi",
                "open-bluetooth", "open-battery", "open-accessibility",
            },
            set(settings["actions"]),
        )
        self.assertEqual([], settings["safety"]["requires_confirmation"])
        self.assertTrue(
            all(
                step["operation"] in {"activate", "tap", "wait"}
                for action in settings["actions"].values()
                for step in action["steps"]
            )
        )
        prohibited = " ".join(settings["safety"]["prohibited"]).casefold()
        self.assertIn("protected confirmations", prohibited)
        self.assertIn("operating any toggle", prohibited)


if __name__ == "__main__":
    unittest.main()
