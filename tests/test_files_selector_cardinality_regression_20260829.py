"""Regression: Files remains CoreDevice/AirDrop-only with no selector navigation."""
from __future__ import annotations
import json
from pathlib import Path
import unittest
from unittest import mock
from integrations.files import commands
ROOT=Path(__file__).resolve().parents[1];FILES=ROOT/"integrations/files"
class FilesDirectOnlyRegressionTests(unittest.TestCase):
    def test_manifest_has_no_navigation_selectors(self):
        value=json.loads((FILES/"integration.json").read_text());self.assertEqual(value["capabilities"],["launch"]);self.assertEqual(value["selectors"],{});self.assertEqual(set(value["actions"]),{"activate"})
    def test_public_surface_is_open_drop_show_only(self):
        self.assertEqual(commands.COMMANDS,("open","drop","show"))
        for removed in ("recents","browse","search","path","smb"):
            with mock.patch.object(commands.shared,"_direct_open") as direct:result=commands.files(removed)
            self.assertFalse(result["ok"]);direct.assert_not_called()
    def test_bundle_schemes_are_explicitly_excluded(self):
        evidence=json.loads((FILES/"route-compatibility.json").read_text());self.assertEqual({r["scheme"] for r in evidence["excluded_routes"]},{"shareddocuments","smb"})

if __name__=="__main__":unittest.main()
