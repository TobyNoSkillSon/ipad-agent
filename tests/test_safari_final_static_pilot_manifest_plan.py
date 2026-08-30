import json
from pathlib import Path
import unittest

from ipad_agent.lab import plan_scenario, run_fake_scenario, validate_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "integrations" / "safari" / "integration.json"
POLICY = MANIFEST.with_name("url-policy.json")
WORKFLOW = MANIFEST.with_name("WORKFLOWS.md")


class SafariFinalStaticPilotManifestPlanTests(unittest.TestCase):
    def test_safari_is_the_built_in_core_browser_and_static_example_default(self):
        value = validate_manifest(MANIFEST)
        self.assertEqual("safari", value["id"])
        self.assertEqual("core", value["kind"])
        self.assertEqual("unverified", value["compatibility"]["verification"])
        self.assertEqual([], value["compatibility"]["app_versions"])

    def test_manifest_exposes_only_url_now_foreground_and_toolbar_routes(self):
        value = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual({"activate", "open-url", "inspect-toolbar"}, set(value["actions"]))
        self.assertEqual({
            "foreground-only", "show-web-page", "display-now-page",
            "recover-now-page", "inspect-toolbar-bounded",
        }, set(value["scenarios"]))
        encoded = json.dumps(value).casefold()
        for forbidden in ("create-normal-task-tab", "create-task-tab-with-url", "show-tab-overview", "close-tab"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual([], value["safety"]["requires_confirmation"])

    def test_url_policy_is_explicit_and_plans_are_bound_to_it(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual({"open-url": ["http", "https"]}, policy["actions"])
        plan = plan_scenario(MANIFEST, "show-web-page", parameters={"url": "https://example.com"})
        url_step = plan.steps[-1]
        self.assertEqual(["http", "https"], url_step.instruction["allowed_schemes"])
        for bad in ("ftp://example.com", "https://user:pass@example.com", "https:///missing-host", "https://bad host"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                plan_scenario(MANIFEST, "show-web-page", parameters={"url": bad})

    def test_all_production_scenarios_plan_and_simulate_without_compatibility_claims(self):
        value = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for scenario_id, scenario in value["scenarios"].items():
            parameters = {"url": "https://example.com"} if "open-url" in scenario["actions"] else {}
            with self.subTest(scenario=scenario_id):
                plan = plan_scenario(MANIFEST, scenario_id, parameters=parameters)
                self.assertTrue(run_fake_scenario(plan, record=False).ok)

    def test_persistent_tab_state_and_unsupported_cleanup_are_explicit(self):
        value = json.loads(MANIFEST.read_text(encoding="utf-8"))
        text = (json.dumps(value) + WORKFLOW.read_text(encoding="utf-8")).casefold()
        for phrase in (
            "persistent tab state", "exact automatic cleanup is unsupported",
            "no production task-tab creation", "coredevice acceptance proves dispatch only",
            "two historical pilot task tabs remain", "compatibility remains `unverified`",
        ):
            self.assertIn(phrase, text)
        self.assertIn("locked coredevice result is terminal", text)


if __name__ == "__main__":
    unittest.main()
