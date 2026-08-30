import json
from pathlib import Path
import unittest

from ipad_agent.registry import AddonNotEnabledError, load_registry


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = {
    "maps": ROOT / "integrations" / "maps" / "integration.json",
    "files": ROOT / "integrations" / "files" / "integration.json",
    "settings": ROOT / "integrations" / "settings" / "integration.json",
    "clock": ROOT / "integrations" / "clock" / "integration.json",
    "brave": ROOT / "addons" / "brave" / "integration.json",
}
DOCS = {name: path.with_name("WORKFLOWS.md") for name, path in MANIFESTS.items()}


def load_manifest(name):
    return json.loads(MANIFESTS[name].read_text(encoding="utf-8"))


class NonSafariIntegrationContracts(unittest.TestCase):
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

    def test_maps_uses_direct_urls_before_one_bounded_ui_fallback(self):
        manifest = load_manifest("maps")
        actions = manifest["actions"]
        order = list(actions)
        self.assertLess(order.index("open-search"), order.index("search-ui-fallback"))
        self.assertLess(order.index("open-destination"), order.index("search-ui-fallback"))
        self.assertLess(order.index("open-directions"), order.index("search-ui-fallback"))
        for name in ("open-search", "open-destination", "open-directions"):
            self.assertEqual("open-url", actions[name]["steps"][0]["operation"])
            self.assertTrue(actions[name]["steps"][0]["value"].startswith("maps://?"))
        self.assertEqual(
            [{"operation": "clear-type", "selector": "search", "value": "{query}"}],
            actions["search-ui-fallback"]["steps"],
        )
        self.assertEqual(1, manifest["retry"]["max_attempts"])
        self.assertTrue(manifest["safety"]["mutates_user_data"])
        prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
        self.assertIn("turn-by-turn", prohibited)
        self.assertIn("ambiguous", prohibited)

    def test_files_is_navigation_and_visible_search_without_enumeration(self):
        manifest = load_manifest("files")
        self.assertEqual(
            {"activate", "open-recents", "open-browse", "focus-search", "enter-search"},
            set(manifest["actions"]),
        )
        operations = {
            step["operation"]
            for action in manifest["actions"].values()
            for step in action["steps"]
        }
        self.assertLessEqual(operations, {"activate", "tap", "clear-type"})
        self.assertFalse(manifest["safety"]["mutates_user_data"])
        prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
        for phrase in ("opening", "enumerating", "traversing", "deleting", "more"):
            self.assertIn(phrase, prohibited)
        self.assertIn("must not scrape", manifest["privacy"]["notes"].casefold())

    def test_settings_exposes_bounded_navigation_and_exact_about_route(self):
        manifest = load_manifest("settings")
        self.assertEqual(
            {
                "activate", "open-general", "open-about", "open-wifi",
                "open-bluetooth", "open-battery", "open-accessibility",
            },
            set(manifest["actions"]),
        )
        self.assertEqual(
            {
                "general", "accessibility id=About", "wifi", "bluetooth",
                "battery", "accessibility",
            },
            set(manifest["selectors"]),
        )
        about = manifest["selectors"]["accessibility id=About"]
        self.assertEqual(
            {"using": "accessibility id", "value": "About", "cache": False},
            about,
        )
        self.assertEqual(
            [
                {"operation": "tap", "selector": "general"},
                {"operation": "wait", "selector": "accessibility id=About", "seconds": 5},
                {"operation": "tap", "selector": "accessibility id=About"},
            ],
            manifest["actions"]["open-about"]["steps"],
        )
        recipes = " ".join(
            f"{selector['using']}={selector['value']}"
            for selector in manifest["selectors"].values()
        ).casefold()
        self.assertNotIn("xpath", recipes)
        self.assertFalse(any("x" in step or "y" in step for action in manifest["actions"].values() for step in action["steps"]))
        prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
        for phrase in ("toggle", "account", "privacy", "security", "software update"):
            self.assertIn(phrase, prohibited)
        self.assertNotIn("focus-search", manifest["capabilities"])
        self.assertIn("open-about", manifest["capabilities"])

    def test_clock_stopwatch_is_transient_and_reset_is_required_cleanup(self):
        manifest = load_manifest("clock")
        scenario = manifest["scenarios"]["transient-stopwatch"]
        self.assertEqual("reset-stopwatch", scenario["actions"][-1])
        self.assertEqual(
            [
                {"operation": "tap", "selector": "reset"},
                {"operation": "wait", "selector": "start", "seconds": 3},
                {"operation": "wait", "selector": "stopwatch_zero", "seconds": 3},
            ],
            manifest["actions"]["reset-stopwatch"]["steps"],
        )
        self.assertFalse(manifest["safety"]["mutates_user_data"])
        self.assertIn("transient", manifest["safety"]["classification"])
        self.assertIn("leaving a task-owned stopwatch running or nonzero", manifest["safety"]["prohibited"])
        for unsafe_retry in ("start-stopwatch", "stop-stopwatch", "reset-stopwatch"):
            self.assertNotIn(unsafe_retry, manifest["retry"]["idempotent_actions"])

    def test_brave_is_optional_and_has_no_tab_cleanup_action(self):
        with self.assertRaises(AddonNotEnabledError):
            load_registry().resolve("brave")
        manifest = load_manifest("brave")
        self.assertEqual("addon", manifest["kind"])
        self.assertTrue(manifest["safety"]["mutates_user_data"])
        self.assertIn("persistent-tab-state", manifest["safety"]["classification"])
        self.assertFalse(any("close" in name or "new-tab" in name for name in manifest["actions"]))
        prohibited = " ".join(manifest["safety"]["prohibited"]).casefold()
        self.assertIn("durable now tab", prohibited)
        self.assertIn("claiming tab ownership", prohibited)
        self.assertIn("explicit brave addon enablement", manifest["requirements"]["permissions"])

    def test_every_integration_documents_required_operating_contract(self):
        headings = (
            "## Instructions",
            "## Selector rationale",
            "## State, locale, and version caveats",
            "## Safety and retry classes",
            "## Benchmark scenarios",
            "## Completion gates",
        )
        for name, path in DOCS.items():
            with self.subTest(name=name):
                text = path.read_text(encoding="utf-8")
                for heading in headings:
                    self.assertIn(heading, text)
                lowered = text.casefold()
                self.assertTrue("not been exercised on a physical ipad" in lowered or "no physical" in lowered)
                self.assertNotIn("physically verified", lowered)


if __name__ == "__main__":
    unittest.main()
