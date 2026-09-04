"""Regression: Safari URL delivery does not regain toolbar automation."""
from __future__ import annotations
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1];SAFARI=ROOT/"integrations/safari"
class SafariDirectOnlyRegressionTests(unittest.TestCase):
    def test_manifest_contains_only_launch_and_url_delivery(self):
        value=json.loads((SAFARI/"integration.json").read_text());self.assertEqual(value["selectors"],{});self.assertEqual(set(value["actions"]),{"activate","open-url"});self.assertEqual(set(value["scenarios"]),{"activate-direct","open-url-direct"})
    def test_toolbar_and_now_material_are_absent(self):
        text="\n".join((SAFARI/name).read_text().casefold() for name in ("integration.json","SKILL.md","WORKFLOWS.md"))
        for token in ("taboverviewbutton","newtabbutton","display server","now page"):
            self.assertNotIn(token,text)
    def test_policy_remains_http_https_only(self):
        policy=json.loads((SAFARI/"url-policy.json").read_text());self.assertEqual(policy["actions"],{"open-url":["http","https"]})
if __name__=="__main__":unittest.main()
