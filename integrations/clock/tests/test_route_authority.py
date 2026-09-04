from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from integrations.clock import commands

DIRECTORY = Path(__file__).resolve().parents[1]
SCOPE = {"product_type": "iPad17,1", "hardware_model": "J817AP", "os_build": "23G83"}


class ClockRouteAuthorityTests(unittest.TestCase):
    def test_manifest_is_launch_only_and_coredevice_only(self) -> None:
        manifest = json.loads((DIRECTORY / "integration.json").read_text())
        self.assertEqual(manifest["capabilities"], ["launch"])
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(set(manifest["actions"]), {"activate"})
        self.assertEqual(set(manifest["scenarios"]), {"activate-direct"})
        text = "\n".join((DIRECTORY / name).read_text().casefold() for name in ("integration.json", "SKILL.md"))
        for token in ("app" + "ium", "xcui" + "test"):
            self.assertNotIn(token, text)

    def test_exact_profile_and_rendered_evidence_are_metadata_only(self) -> None:
        profile = json.loads(next((DIRECTORY / "device-profiles").glob("*.json")).read_text())
        self.assertEqual(profile["scope_type"], "model-build")
        self.assertEqual({k: profile[k] for k in SCOPE}, SCOPE)
        self.assertTrue({"udid", "serial", "ecid", "device_id"}.isdisjoint(profile))
        authority = json.loads((DIRECTORY / "route-compatibility.json").read_text())
        self.assertEqual([route["command"] for route in authority["routes"]], ["open"])
        route = authority["routes"][0]
        self.assertEqual(route["availability"], "proven")
        visual = next(e for e in route["evidence"] if e["kind"] == "observer-screenshot-pass")
        self.assertEqual(visual["proof_scope"], SCOPE)
        forbidden = {"url", "query", "screenshot", "hash", "device_identifier"}
        self.assertTrue(forbidden.isdisjoint(visual))

    def test_open_dispatches_once_and_unknown_commands_fail(self) -> None:
        sentinel = object()
        with mock.patch.object(commands.shared, "_direct_open", return_value=sentinel) as direct:
            self.assertIs(commands.clock("open"), sentinel)
        direct.assert_called_once_with("Clock")
        with mock.patch.object(commands.shared, "_direct_open") as direct:
            result = commands.clock("timer")
        direct.assert_not_called()
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
