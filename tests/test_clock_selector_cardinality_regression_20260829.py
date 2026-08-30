import json
from pathlib import Path
import tempfile
import unittest

from ipad_agent.lab import plan_scenario, run_fake_scenario, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "integrations" / "clock" / "integration.json"
WORKFLOWS_PATH = MANIFEST_PATH.with_name("WORKFLOWS.md")


def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


class ClockSelectorCardinalityRegression20260829Tests(unittest.TestCase):
    def test_manifest_validates_and_tab_buttons_use_current_exact_labels(self):
        value = validate_manifest(MANIFEST_PATH)
        labels = {
            "world_clock": "World Clock",
            "alarm": "Alarms",
            "stopwatch": "Stopwatch",
            "timer": "Timers",
        }
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

    def test_stopwatch_controls_are_exact_accessible_visible_buttons_without_xpath(self):
        value = manifest()
        for name, label in {
            "start": "Start",
            "stopped_start": "Start",
            "stop": "Stop",
            "reset": "Reset",
        }.items():
            with self.subTest(selector=name):
                selector = value["selectors"][name]
                self.assertEqual("-ios predicate string", selector["using"])
                recipe = selector["value"]
                self.assertIn("type == 'XCUIElementTypeButton'", recipe)
                self.assertIn(f"label == '{label}'", recipe)
                self.assertIn("visible == 1", recipe)
                self.assertIn("accessible == 1", recipe)

        recipes = " ".join(
            f"{selector['using']} {selector['value']}"
            for selector in value["selectors"].values()
        ).casefold()
        for forbidden in ("xpath", "coordinate", "index ==", "rect."):
            self.assertNotIn(forbidden, recipes)
        self.assertNotIn("lap", value["selectors"])

    def test_zero_readiness_uses_stable_identifier_and_exact_value(self):
        selectors = manifest()["selectors"]
        self.assertEqual(
            {
                "using": "accessibility id",
                "value": "stopwatch-time",
                "cache": False,
            },
            selectors["stopwatch_reading"],
        )
        zero = selectors["stopwatch_zero"]
        self.assertEqual("-ios predicate string", zero["using"])
        for clause in (
            "type == 'XCUIElementTypeStaticText'",
            "name == 'stopwatch-time'",
            "value == '0 seconds'",
            "visible == 1",
            "accessible == 1",
        ):
            self.assertIn(clause, zero["value"])

    def test_baseline_precedes_start_and_cleanup_remains_stop_then_reset(self):
        value = manifest()
        inspect_steps = value["actions"]["inspect-stopwatch-state"]["steps"]
        self.assertEqual(
            ["stopwatch_reading", "stopwatch_zero", "start"],
            [step["selector"] for step in inspect_steps],
        )
        scenario_actions = value["scenarios"]["transient-stopwatch"]["actions"]
        self.assertLess(
            scenario_actions.index("inspect-stopwatch-state"),
            scenario_actions.index("start-stopwatch"),
        )
        self.assertEqual("reset-stopwatch", scenario_actions[-1])

        start_steps = value["actions"]["start-stopwatch"]["steps"]
        self.assertEqual(
            [("tap", "start"), ("wait", "stop")],
            [(step["operation"], step["selector"]) for step in start_steps],
        )
        stop_steps = value["actions"]["stop-stopwatch"]["steps"]
        self.assertEqual(
            [("tap", "stop"), ("wait", "stopped_start"), ("wait", "reset")],
            [(step["operation"], step["selector"]) for step in stop_steps],
        )
        reset_steps = value["actions"]["reset-stopwatch"]["steps"]
        self.assertEqual(
            [("tap", "reset"), ("wait", "start"), ("wait", "stopwatch_zero")],
            [(step["operation"], step["selector"]) for step in reset_steps],
        )
        workflow = WORKFLOWS_PATH.read_text(encoding="utf-8")
        self.assertIn("require exactly one `stopwatch_zero`", workflow)

    def test_uncertain_mutations_remain_single_attempt_and_never_safe_repeat(self):
        value = manifest()
        self.assertEqual(1, value["retry"]["max_attempts"])
        for action_id in ("start-stopwatch", "stop-stopwatch", "reset-stopwatch"):
            self.assertEqual("inspect_then_decide", value["actions"][action_id]["retry"])
            self.assertNotIn(action_id, value["retry"]["idempotent_actions"])
        self.assertIn("never replay blindly", value["safety"]["uncertain_outcome"])

    def test_workflow_documents_the_narrow_physical_evidence_boundary(self):
        text = WORKFLOWS_PATH.read_text(encoding="utf-8").casefold()
        for phrase in (
            "private physical evidence",
            "one unchanged, selected, reset stopwatch surface",
            "locale is unknown",
            "compatibility `unverified`",
            "no physical tab tap, start, stop, reset",
            "hard stop",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("physically verified", text)

    def test_every_clock_scenario_plans_and_passes_fake_execution(self):
        value = manifest()
        with tempfile.TemporaryDirectory() as temporary:
            for scenario_id in value["scenarios"]:
                with self.subTest(scenario=scenario_id):
                    plan = plan_scenario(MANIFEST_PATH, scenario_id)
                    result = run_fake_scenario(plan, repository_root=temporary, record=False)
                    self.assertTrue(result.ok)
                    self.assertFalse(result.uncertain)


if __name__ == "__main__":
    unittest.main()
