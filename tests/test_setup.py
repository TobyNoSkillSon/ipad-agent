import unittest

from ipad_agent.setup import APPIUM_VERSION, XCUITEST_VERSION, _default_config


class SetupTests(unittest.TestCase):
    def test_versions_are_pinned(self):
        self.assertRegex(APPIUM_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertRegex(XCUITEST_VERSION, r"^\d+\.\d+\.\d+$")

    def test_generated_config_contains_no_identity(self):
        value = _default_config()
        self.assertIn('team_id = ""', value)
        self.assertIn('wda_bundle_id = ""', value)


if __name__ == "__main__":
    unittest.main()
