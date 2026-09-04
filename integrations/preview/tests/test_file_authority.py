from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from integrations.preview import commands

DIRECTORY = Path(__file__).resolve().parents[1]
SCOPE = {"product_type": "iPad17,1", "hardware_model": "J817AP", "os_build": "23G83"}


class PreviewFileAuthorityTests(unittest.TestCase):
    def test_authority_is_exact_and_has_no_unrelated_formats(self) -> None:
        authority = commands._load_file_authority()
        extensions = set(authority["extensions"])
        self.assertIn(".pdf", extensions)
        self.assertIn(".png", extensions)
        self.assertIn(".psd", extensions)
        self.assertTrue(extensions.isdisjoint({".epub", ".zip", ".mov", ".docx", ".xlsx", ".pptx"}))

    def test_extension_gate_is_case_insensitive_and_runs_before_transport(self) -> None:
        for path in ("/tmp/report.PDF", Path("/tmp/image.JpEg"), "/tmp/art.JP2"):
            self.assertIs(commands._validated_preview_file(path), path)
        for path in ("/tmp/book.epub", "/tmp/archive.zip", "/tmp/no-extension"):
            with self.assertRaises(ValueError):
                commands._validated_preview_file(path)

    def test_drop_and_show_forward_once_after_app_gate(self) -> None:
        with mock.patch.object(commands.shared, "_airdrop", return_value="sent") as drop:
            self.assertEqual(commands.preview("drop", "/tmp/image.png"), "sent")
        drop.assert_called_once_with("/tmp/image.png")
        with mock.patch.object(commands.shared, "_show_local", return_value="pending") as show:
            self.assertEqual(commands.preview("show", "/tmp/doc.pdf"), "pending")
        show.assert_called_once_with("Preview", "/tmp/doc.pdf")
        with mock.patch.object(commands.shared, "_airdrop") as blocked:
            result = commands.preview("drop", "/tmp/book.epub")
        self.assertFalse(result["ok"])
        blocked.assert_not_called()

    def test_profile_and_compatibility_evidence_are_metadata_only(self) -> None:
        compatibility = json.loads((DIRECTORY / "route-compatibility.json").read_text())
        profile = json.loads((DIRECTORY / compatibility["profile"]).read_text())
        self.assertEqual({k: profile[k] for k in SCOPE}, SCOPE)
        self.assertNotIn("device_id", json.dumps(compatibility).casefold())
        commands_by_name = {item["command"]: item for item in compatibility["commands"]}
        self.assertEqual(commands_by_name["open"]["availability"], "proven")
        self.assertEqual(commands_by_name["drop"]["availability"], "candidate")
        self.assertEqual(commands_by_name["show"]["availability"], "proven")
        self.assertEqual(commands_by_name["show"]["production"], "admitted")
        evidence = commands_by_name["open"]["evidence"][0]
        self.assertEqual(evidence["proof_scope"], SCOPE)


if __name__ == "__main__":
    unittest.main()
