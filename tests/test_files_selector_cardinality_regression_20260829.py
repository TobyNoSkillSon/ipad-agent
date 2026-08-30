import json
from pathlib import Path
import tempfile
import unittest

from ipad_agent.lab import plan_scenario, run_fake_scenario, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "integrations" / "files" / "integration.json"
WORKFLOWS_PATH = MANIFEST_PATH.with_name("WORKFLOWS.md")


def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


class FilesSelectorCardinalityRegressionTests(unittest.TestCase):
    def test_manifest_validates_and_base_controls_exclude_inaccessible_duplicates(self):
        value = validate_manifest(MANIFEST_PATH)
        labels = {"recents": "Recents", "browse": "Browse", "search": "Search"}
        for name, label in labels.items():
            with self.subTest(selector=name):
                selector = value["selectors"][name]
                self.assertEqual("-ios predicate string", selector["using"])
                self.assertFalse(selector["cache"])
                recipe = selector["value"]
                self.assertIn("type == 'XCUIElementTypeButton'", recipe)
                self.assertIn(f"label == '{label}'", recipe)
                self.assertIn("visible == 1", recipe)
                self.assertIn("accessible == 1", recipe)
                self.assertNotIn("selected ==", recipe)

    def test_destination_verification_is_selected_and_search_typing_targets_a_field(self):
        value = manifest()
        for name in ("recents", "browse"):
            base = value["selectors"][name]["value"]
            selected = value["selectors"][f"{name}-selected"]["value"]
            self.assertIn("selected == 1", selected)
            self.assertEqual(
                base.replace(" AND visible == 1", " AND selected == 1 AND visible == 1"),
                selected,
            )

        field = value["selectors"]["search-field"]["value"]
        self.assertIn("type == 'XCUIElementTypeSearchField'", field)
        self.assertIn("visible == 1", field)
        self.assertIn("accessible == 1", field)
        self.assertEqual(
            [{"operation": "tap", "selector": "search"}],
            value["actions"]["focus-search"]["steps"],
        )
        self.assertEqual(
            [{"operation": "clear-type", "selector": "search-field", "value": "{query}"}],
            value["actions"]["enter-search"]["steps"],
        )

    def test_selectors_and_normal_workflow_have_no_broad_or_coordinate_fallback(self):
        value = manifest()
        recipes = " ".join(item["value"] for item in value["selectors"].values()).casefold()
        for forbidden in ("xpath", "descendant", "children", "rect.", "coordinate", "index =="):
            self.assertNotIn(forbidden, recipes)

        text = WORKFLOWS_PATH.read_text(encoding="utf-8")
        lowered = text.casefold()
        self.assertIn("state preflight", lowered)
        self.assertIn("no tap", lowered)
        self.assertIn("do not request page source", lowered)
        self.assertIn("hard stop", lowered)
        self.assertIn("compatibility `unverified`", lowered)
        self.assertNotIn("physically verified", lowered)

    def test_every_files_scenario_plans_and_passes_fake_execution(self):
        value = manifest()
        with tempfile.TemporaryDirectory() as temporary:
            for scenario_id in value["scenarios"]:
                with self.subTest(scenario=scenario_id):
                    parameters = {"query": "synthetic-selector-check"} if scenario_id == "visible-search-only" else {}
                    plan = plan_scenario(MANIFEST_PATH, scenario_id, parameters=parameters)
                    result = run_fake_scenario(plan, repository_root=temporary, record=False)
                    self.assertTrue(result.ok)
                    self.assertFalse(result.uncertain)


if __name__ == "__main__":
    unittest.main()
