"""Regression: Clock remains launch-only after the CoreDevice cutover."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
CLOCK=ROOT/"integrations/clock"

class ClockLaunchOnlyRegressionTests(unittest.TestCase):
    def test_manifest_is_direct_launch_only(self):
        value=json.loads((CLOCK/"integration.json").read_text())
        self.assertEqual(value["capabilities"],["launch"]);self.assertEqual(value["selectors"],{})
        self.assertEqual(set(value["actions"]),{"activate"});self.assertEqual(set(value["scenarios"]),{"activate-direct"})
    def test_stopwatch_and_tab_automation_do_not_return(self):
        text="\n".join((CLOCK/name).read_text().casefold() for name in ("integration.json","SKILL.md","WORKFLOWS.md"))
        for token in ("start-stopwatch","inspect-stopwatch-state","world_clock","stopped_start","xpath"):
            self.assertNotIn(token,text)
    def test_exact_profile_evidence_is_metadata_only(self):
        evidence=json.loads((CLOCK/"route-compatibility.json").read_text());profile=json.loads((CLOCK/evidence["profile"]).read_text())
        self.assertEqual((profile["product_type"],profile["hardware_model"],profile["os_build"]),("iPad17,1","J817AP","23G83"));self.assertNotIn("device_id",json.dumps(evidence).casefold())

if __name__=="__main__":unittest.main()
