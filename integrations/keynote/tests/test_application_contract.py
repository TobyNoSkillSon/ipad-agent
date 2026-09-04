from __future__ import annotations
import json
from pathlib import Path
import unittest
from unittest import mock
from integrations._skill_test_support import assert_public_wrapper_forwarding
from integrations.keynote import commands

DIRECTORY = Path(__file__).resolve().parents[1]

class ContractTests(unittest.TestCase):
    def test_wrapper(self): assert_public_wrapper_forwarding(self, public_name="ipadkeynote", package="keynote", implementation="keynote")
    def test_surface(self): self.assertEqual(commands.COMMANDS, ("open", "drop", "show"))
    def test_file_gate(self):
        for value in ('/tmp/file.KEY', '/tmp/file.PPT', '/tmp/file.PPTX'): self.assertIs(commands._validated_file(value), value)
        for value in ("/tmp/file.zip", "/tmp/file.exe", "/tmp/noext"):
            with self.assertRaises(ValueError): commands._validated_file(value)
    def test_open_dispatches_after_exact_profile_proof(self):
        with mock.patch.object(commands.shared, "_direct_open", return_value="accepted") as direct: result=commands.keynote("open")
        self.assertEqual(result, "accepted"); direct.assert_called_once_with("Keynote")
    def test_file_dispatch_once(self):
        with mock.patch.object(commands.shared, "_airdrop", return_value="sent") as drop: self.assertEqual(commands.keynote("drop", "/tmp/file.key"), "sent")
        drop.assert_called_once()
    def test_metadata(self):
        data=json.loads((DIRECTORY/"route-compatibility.json").read_text());profile=json.loads((DIRECTORY/data["profile"]).read_text());self.assertEqual((profile["product_type"],profile["hardware_model"],profile["os_build"]),("iPad17,1","J817AP","23G83"));self.assertNotIn("device_id",json.dumps(data).casefold())

if __name__ == "__main__": unittest.main()
