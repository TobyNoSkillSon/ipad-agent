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
        self.assertEqual(value["capabilities"], ["launch", "open-url"])
        self.assertEqual(value["selectors"], {})
        self.assertEqual(set(value["actions"]), {"activate", "open-url"})
        self.assertEqual(set(value["scenarios"]), {"activate-direct", "open-url-direct"})

    def test_url_policy_is_explicit_and_plans_are_bound_to_it(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual({"open-url": ["http", "https"]}, policy["actions"])
        plan = plan_scenario(MANIFEST, "open-url-direct", parameters={"url": "https://example.com"})
        url_step = plan.steps[-1]
        self.assertEqual(["http", "https"], url_step.instruction["allowed_schemes"])
        for bad in ("ftp://example.com", "https://user:pass@example.com", "https:///missing-host", "https://bad host"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                plan_scenario(MANIFEST, "open-url-direct", parameters={"url": bad})

    def test_all_production_scenarios_plan_and_simulate_without_compatibility_claims(self):
        value = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for scenario_id, scenario in value["scenarios"].items():
            parameters = {"url": "https://example.com"} if "open-url" in scenario["actions"] else {}
            with self.subTest(scenario=scenario_id):
                plan = plan_scenario(MANIFEST, scenario_id, parameters=parameters)
                self.assertTrue(run_fake_scenario(plan, record=False).ok)

    def test_persistent_tab_state_and_unsupported_cleanup_are_explicit(self):
        value = json.loads(MANIFEST.read_text(encoding="utf-8"))
        text = json.dumps(value).casefold() + (WORKFLOW).read_text().casefold()
        self.assertIn("persistent-tab-state", json.dumps(value["safety"]["classification"]).casefold())
        self.assertIn("automatic tab cleanup", text)
        self.assertIn("tab ownership", text)
        self.assertNotIn("close-tab", json.dumps(value["actions"]).casefold())


if __name__ == "__main__":
    unittest.main()
