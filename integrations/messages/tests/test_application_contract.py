from __future__ import annotations
import json
from pathlib import Path
import unittest
from unittest import mock
from integrations._skill_test_support import assert_public_wrapper_forwarding
from integrations.messages import commands
DIRECTORY=Path(__file__).resolve().parents[1]
class MessagesTests(unittest.TestCase):
    def test_wrapper_and_surface(self):
        assert_public_wrapper_forwarding(self,public_name="ipadmessages",package="messages",implementation="messages")
        self.assertEqual(commands.COMMANDS,("open","compose","prepare"));self.assertEqual(commands.__all__,["messages"])
    def test_sms_grammar(self):
        self.assertEqual(commands._sms_url(),"sms:");self.assertEqual(commands._sms_url("+48-123.456"),"sms:+48-123.456")
        for bad in ("", " 123", "12 3", "abc", "+", "123?body=x"):
            with self.assertRaises(ValueError): commands._sms_url(bad)
    def test_compose_is_proven_while_private_routes_stay_gated(self):
        with mock.patch.object(commands.shared,"_direct_open",return_value="accepted") as direct:self.assertEqual(commands.messages("compose"),"accepted")
        direct.assert_called_once_with("Messages","sms:")
        for command,args in (("open",()),("prepare",("+48123456789",))):
            with mock.patch.object(commands.shared,"_direct_open") as direct: result=commands.messages(command,*args)
            self.assertFalse(result["ok"]);direct.assert_not_called()
    def test_metadata(self):
        data=json.loads((DIRECTORY/"route-compatibility.json").read_text());profile=json.loads((DIRECTORY/data["profile"]).read_text());self.assertEqual((profile["product_type"],profile["hardware_model"],profile["os_build"]),("iPad17,1","J817AP","23G83"));self.assertNotIn("device_id",json.dumps(data).casefold())
if __name__=="__main__":unittest.main()
