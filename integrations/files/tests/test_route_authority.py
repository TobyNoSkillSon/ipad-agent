from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from integrations.files import commands

DIRECTORY = Path(__file__).resolve().parents[1]


class FilesRouteAuthorityTests(unittest.TestCase):
    def test_manifest_is_launch_only(self) -> None:
        manifest = json.loads((DIRECTORY / "integration.json").read_text())
        self.assertEqual(manifest["capabilities"], ["launch"])
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(set(manifest["actions"]), {"activate"})
        self.assertEqual(set(manifest["scenarios"]), {"activate-direct"})

    def test_transfer_is_delegated_once_without_claiming_handoff(self) -> None:
        with mock.patch.object(commands.shared, "_airdrop", return_value="sent") as drop:
            self.assertEqual(commands.files("drop", "/tmp/file.pdf"), "sent")
        drop.assert_called_once_with("/tmp/file.pdf")
        with mock.patch.object(commands.shared, "_show_local", return_value="pending") as show:
            self.assertEqual(commands.files("show", "/tmp/file.pdf"), "pending")
        show.assert_called_once_with("Files", "/tmp/file.pdf")

    def test_route_exclusions_and_profile_evidence_are_exact(self) -> None:
        data = json.loads((DIRECTORY / "route-compatibility.json").read_text())
        profile = json.loads((DIRECTORY / data["profile"]).read_text())
        scope = {"product_type": "iPad17,1", "hardware_model": "J817AP", "os_build": "23G83"}
        self.assertEqual({key: profile[key] for key in scope}, scope)
        self.assertEqual({item["scheme"] for item in data["excluded_routes"]}, {"shareddocuments", "smb"})
        self.assertEqual({item["command"]: item["availability"] for item in data["commands"]}, {"open": "proven", "drop": "proven", "show": "candidate"})
        self.assertEqual({item["command"]: item["production"] for item in data["commands"]}, {"open": "admitted", "drop": "admitted", "show": "legacy-admitted"})
        self.assertNotIn("device_id", json.dumps(data).casefold())
        workflows = (DIRECTORY / "WORKFLOWS.md").read_text()
        self.assertIn("`drop` is therefore proven and admitted", workflows)
        self.assertIn("`show` remains candidate and `legacy-admitted`", workflows)

    def test_public_surface_has_no_path_or_search_navigation(self) -> None:
        self.assertEqual(commands.COMMANDS, ("open", "drop", "show"))
        for operation in ("path", "browse", "recents", "search", "smb"):
            with mock.patch.object(commands.shared, "_direct_open") as direct:
                result = commands.files(operation, "x")
            self.assertFalse(result["ok"])
            direct.assert_not_called()


if __name__ == "__main__":
    unittest.main()
