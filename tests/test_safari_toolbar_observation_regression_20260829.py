import json
from pathlib import Path
import unittest

from ipad_agent.lab import plan_scenario, validate_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "integrations" / "safari" / "integration.json"
WORKFLOW = MANIFEST.with_name("WORKFLOWS.md")


class SafariToolbarObservationRegression20260829Tests(unittest.TestCase):
    def test_observed_toolbar_recipes_match_the_retained_accessibility_contract(self):
        value = validate_manifest(MANIFEST)
        selectors = value["selectors"]
        self.assertEqual({
            "observed-address-control", "observed-tabs-control",
            "observed-toolbar-new-tab-control",
        }, set(selectors))
        for selector in selectors.values():
            self.assertEqual("-ios predicate string", selector["using"])
            predicate = selector["value"]
            self.assertIn("visible == 1", predicate)
            self.assertIn("accessible == 1", predicate)
            self.assertNotIn("xpath", predicate.casefold())

    def test_toolbar_inspection_contains_only_the_three_observed_controls(self):
        plan = plan_scenario(MANIFEST, "inspect-toolbar-bounded")
        self.assertEqual(
            [
                "observed-address-control", "observed-tabs-control",
                "observed-toolbar-new-tab-control",
            ],
            [step.instruction["selector"] for step in plan.steps if step.instruction["operation"] == "inspect"],
        )
        self.assertTrue(all(step.instruction["operation"] in {"activate", "inspect"} for step in plan.steps))

    def test_overview_and_task_tab_surfaces_are_absent(self):
        value = json.loads(MANIFEST.read_text(encoding="utf-8"))
        encoded = json.dumps(value).casefold()
        for phrase in ("observed-normal-tab-mode", "observed-overview-new-tab-control", "show-tab-overview", "create-normal-task-tab"):
            self.assertNotIn(phrase, encoded)

    def test_workflow_states_the_narrow_observation_boundary(self):
        text = WORKFLOW.read_text(encoding="utf-8").casefold()
        for phrase in (
            "bounded toolbar observation", "must not tap the tabs or new tab controls",
            "do not authorize tab overview entry", "zero or multiple matches",
            "does not establish public compatibility",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
