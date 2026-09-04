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
    def assert_prohibition_covers(self, prohibitions, *concepts):
        normalized = [item.casefold() for item in prohibitions]
        self.assertTrue(
            any(all(concept.casefold() in item for concept in concepts) for item in normalized),
            f"no prohibition covers all concepts: {concepts!r}",
        )

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
        self.assertEqual({"activate-direct"}, set(manifest["scenarios"]))
        prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
        self.assertIn("exact file opening", prohibited)
        self.assertIn("airdrop recipient", prohibited)

    def test_books_and_appstore_navigation_uses_only_exact_fail_closed_selectors(self):
        for name in ("books", "appstore"):
            manifest = load_manifest(name)
            with self.subTest(integration=name):
                self.assertEqual(manifest["selectors"], {})
                self.assertEqual(manifest["capabilities"], ["launch"])
                self.assertEqual(set(manifest["actions"]), {"activate"})
                self.assertEqual(set(manifest["scenarios"]), {"activate-direct"})
                self.assertNotIn("xpath", json.dumps(manifest).casefold())
                prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
                self.assertTrue("protected" in prohibited or "payment" in prohibited)

    def test_settings_is_coredevice_catalogue_navigation_without_ui_recipes(self):
        settings = load_manifest("settings")
        self.assertEqual(["exact-settings-url-navigation"], settings["capabilities"])
        self.assertEqual({}, settings["selectors"])
        self.assertEqual({}, settings["actions"])
        self.assertEqual({}, settings["scenarios"])
        self.assertEqual([], settings["safety"]["requires_confirmation"])
        self.assertFalse(settings["safety"]["mutates_user_data"])
        self.assertEqual(1, settings["retry"]["max_attempts"])
        self.assertEqual([], settings["retry"]["idempotent_actions"])
        self.assertIn(
            "macOS with Xcode CoreDevice support",
            settings["requirements"]["host"],
        )
        self.assertEqual("unverified", settings["compatibility"]["verification"])
        self.assertEqual("26.6.1", settings["compatibility"]["minimum_os"])
        self.assertEqual("26.6.1", settings["compatibility"]["maximum_os"])
        notes = settings["privacy"]["notes"].casefold()
        for proof in ("11 user-visual passes", "product ipad17,1", "hardware j817ap", "os build 23g83"):
            self.assertIn(proof, notes)

        prohibited = settings["safety"]["prohibited"]
        for concepts in (
            ("arbitrary", "url"),
            ("caller", "dynamic", "identifier"),
            ("candidate", "incompatible", "template", "blocked", "production"),
            ("toggle", "row", "picker", "text field", "button"),
            ("protected", "confirmation"),
            ("reset", "erase", "install", "update"),
            ("passcode", "biometric", "account-changing"),
        ):
            self.assert_prohibition_covers(prohibited, *concepts)

        manifest_text = json.dumps(settings).casefold()
        for forbidden in ("w" + "da", "appium", "xcuitest"):
            self.assertNotIn(forbidden, manifest_text)


if __name__ == "__main__":
    unittest.main()
