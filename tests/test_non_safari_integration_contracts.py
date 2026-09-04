from collections import Counter
import json
from pathlib import Path
import unittest

from ipad_agent.registry import AddonNotEnabledError, load_registry


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = {
    "maps": ROOT / "integrations" / "apple_maps" / "integration.json",
    "files": ROOT / "integrations" / "files" / "integration.json",
    "settings": ROOT / "integrations" / "settings" / "integration.json",
    "clock": ROOT / "integrations" / "clock" / "integration.json",
    "brave": ROOT / "integrations" / "brave" / "integration.json",
}
DOCS = {name: path.with_name("WORKFLOWS.md") for name, path in MANIFESTS.items()}


def load_manifest(name):
    return json.loads(MANIFESTS[name].read_text(encoding="utf-8"))


class NonSafariIntegrationContracts(unittest.TestCase):
    def assert_prohibition_covers(self, prohibitions, *concepts):
        normalized = [item.casefold() for item in prohibitions]
        self.assertTrue(
            any(all(concept.casefold() in item for concept in concepts) for item in normalized),
            f"no prohibition covers all concepts: {concepts!r}",
        )

    def test_manifests_pass_registry_validation_and_use_exact_schema_surface(self):
        core = load_registry()
        with_addon = load_registry(enabled_addons={"brave"})
        self.assertEqual({"maps", "files", "settings", "clock"}, set(MANIFESTS) & set(core))
        self.assertEqual("addon", with_addon.resolve("brave").kind)

        schema = json.loads((ROOT / "schemas" / "integration-v1.json").read_text(encoding="utf-8"))
        expected_top_level = set(schema["properties"])
        for name in MANIFESTS:
            with self.subTest(name=name):
                manifest = load_manifest(name)
                self.assertEqual(expected_top_level, set(manifest))
                self.assertEqual("ipad-agent.integration/v1", manifest["schema"])
                self.assertEqual(1, manifest["version"])
                self.assertEqual(name, manifest["id"])

    def test_maps_is_coredevice_only_and_model_build_evidence_gated(self):
        manifest = load_manifest("maps")
        directory = MANIFESTS["maps"].parent
        actions = manifest["actions"]
        direct = {
            "open-frame", "open-search", "open-place", "open-look-around",
            "open-directions", "start-navigation", "open-guides",
            "open-report-problem", "open-link",
        }
        self.assertEqual({}, manifest["selectors"])
        self.assertEqual(
            {"navigate-candidate", "report-problem-candidate"},
            set(manifest["scenarios"]),
        )
        self.assertEqual({"activate", *direct}, set(actions))
        self.assertEqual([{"operation": "activate"}], actions["activate"]["steps"])
        for name in direct:
            self.assertEqual(1, len(actions[name]["steps"]))
            self.assertEqual("open-url", actions[name]["steps"][0]["operation"])
        self.assertFalse(any(
            step["operation"] in {"tap", "clear-type", "type", "wait", "swipe", "inspect"}
            for action in actions.values() for step in action["steps"]
        ))
        self.assertNotIn("fallback", " ".join(actions).casefold())
        self.assertEqual(1, manifest["retry"]["max_attempts"])
        self.assertEqual(["activate"], manifest["retry"]["idempotent_actions"])

        profile = json.loads((directory / "device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json").read_text(encoding="utf-8"))
        authority = json.loads((directory / "route-compatibility.json").read_text(encoding="utf-8"))
        self.assertEqual("model-build", profile["scope_type"])
        self.assertEqual(
            {"product_type": "iPad17,1", "hardware_model": "J817AP", "os_build": "23G83"},
            {key: profile[key] for key in ("product_type", "hardware_model", "os_build")},
        )
        self.assertEqual(
            "device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json",
            authority["profile"],
        )
        self.assertEqual(Counter({"proven": 7, "candidate": 2}), Counter(
            route["availability"] for route in authority["routes"]
        ))
        self.assertEqual(
            {"navigate", "report-a-problem"},
            {
                route["command"]
                for route in authority["routes"]
                if route["availability"] == "candidate"
            },
        )
        self.assertTrue(all(
            [item["kind"] for item in route["evidence"]] == ["official-documentation"]
            for route in authority["routes"] if route["availability"] == "candidate"
        ))
        frame = next(route for route in authority["routes"] if route["command"] == "frame")
        self.assertEqual(
            ["official-documentation", "user-visual-pass", "observer-screenshot-pass"],
            [item["kind"] for item in frame["evidence"]],
        )
        prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
        self.assertIn("candidate or incompatible", prohibited)
        self.assertIn("retries after dispatch", prohibited)

    def test_files_is_navigation_and_visible_search_without_enumeration(self):
        manifest = load_manifest("files")
        self.assertEqual(manifest["capabilities"], ["launch"])
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(set(manifest["actions"]), {"activate"})
        self.assertEqual(set(manifest["scenarios"]), {"activate-direct"})
        prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
        for concept in ("enumerating", "searching", "smb", "airdrop"):
            self.assertIn(concept, prohibited)

    def test_settings_manifest_is_coredevice_only_with_bounded_prohibitions(self):
        manifest = load_manifest("settings")
        self.assertEqual(["exact-settings-url-navigation"], manifest["capabilities"])
        self.assertEqual({}, manifest["selectors"])
        self.assertEqual({}, manifest["actions"])
        self.assertEqual({}, manifest["scenarios"])
        self.assertEqual("settings-navigation-only", manifest["safety"]["classification"])
        self.assertFalse(manifest["safety"]["mutates_user_data"])
        self.assertEqual([], manifest["safety"]["requires_confirmation"])
        self.assertEqual(1, manifest["retry"]["max_attempts"])
        self.assertEqual([], manifest["retry"]["idempotent_actions"])
        self.assertEqual(
            ["macOS with Xcode CoreDevice support", "Python 3.11 or newer"],
            manifest["requirements"]["host"],
        )

        prohibited = manifest["safety"]["prohibited"]
        for concepts in (
            ("arbitrary", "url"),
            ("caller", "dynamic", "identifier"),
            ("candidate", "incompatible", "template", "blocked", "production"),
            ("toggle", "row", "picker", "text field", "button"),
            ("protected", "confirmation"),
            ("payment", "reset", "erase", "install", "update"),
            ("passcode", "biometric", "account-changing"),
        ):
            self.assert_prohibition_covers(prohibited, *concepts)
        manifest_text = MANIFESTS["settings"].read_text(encoding="utf-8").casefold()
        for forbidden in ("w" + "da", "appium", "xcuitest"):
            self.assertNotIn(forbidden, manifest_text)

    def test_settings_catalogue_is_bound_to_exact_model_build_proof(self):
        directory = MANIFESTS["settings"].parent
        profile_path = directory / "device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        catalogue = json.loads((directory / "route-catalog.json").read_text(encoding="utf-8"))
        expected_scope = {
            "product_type": "iPad17,1",
            "hardware_model": "J817AP",
            "os_build": "23G83",
        }

        self.assertEqual("model-build", profile["scope_type"])
        self.assertEqual("26.6.1", profile["os_version"])
        self.assertEqual(expected_scope, {key: profile[key] for key in expected_scope})
        self.assertEqual(
            "device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json",
            catalogue["profile"],
        )
        self.assertEqual(
            {"actor": "user", "proof_scope": expected_scope},
            catalogue["source"]["user_visual_source"],
        )

        routes = catalogue["routes"]
        self.assertEqual(
            Counter(route["availability"] for route in routes),
            {"proven": 11, "candidate": 209, "incompatible": 10, "template": 21},
        )
        for route in routes:
            passes = [item for item in route["evidence"] if item["kind"] == "user-visual-pass"]
            if route["availability"] == "proven":
                self.assertEqual(1, len(passes), route["id"])
                self.assertEqual("user", passes[0]["actor"])
                self.assertEqual("expected-target-visible", passes[0]["result"])
                self.assertEqual(expected_scope, passes[0]["proof_scope"])
            else:
                self.assertEqual([], passes, route["id"])

    def test_clock_stopwatch_is_transient_and_reset_is_required_cleanup(self):
        manifest = load_manifest("clock")
        self.assertEqual(manifest["capabilities"], ["launch"])
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(set(manifest["actions"]), {"activate"})
        self.assertEqual(set(manifest["scenarios"]), {"activate-direct"})
        text = json.dumps(manifest).casefold()
        for removed in ("stopwatch", "alarm", "timer"):
            self.assertIn(removed, text)
        self.assertNotIn("clear-type", text)

    def test_brave_is_optional_and_has_no_tab_cleanup_action(self):
        with self.assertRaises(AddonNotEnabledError):
            load_registry().resolve("brave")
        manifest = load_manifest("brave")
        self.assertEqual(manifest["kind"], "addon")
        self.assertEqual(manifest["selectors"], {})
        text = json.dumps(manifest).casefold()
        self.assertIn("tab ownership", text)
        self.assertIn("automatically cleaning", text)
        self.assertNotIn("close-tab", text)

    def test_every_integration_documents_its_current_operating_contract(self):
        for name, workflow in DOCS.items():
            with self.subTest(name=name):
                text = workflow.read_text(encoding="utf-8")
                self.assertTrue(text.startswith(f"# {load_manifest(name)['name']}"))
                self.assertIn("## ", text)
                self.assertTrue(any(term in text.casefold() for term in ("evidence", "compatibility", "result semantics")))
                self.assertNotIn("automatic cleanup is supported", text.casefold())


if __name__ == "__main__":
    unittest.main()
