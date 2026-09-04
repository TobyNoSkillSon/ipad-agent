from __future__ import annotations

import importlib
import inspect
import unittest
from unittest import mock

from ipad_agent import ipadc
from ipad_agent.core import commands
import ipad_agent.core.controller as controller_owner


class ControllerOwnershipStage3Tests(unittest.TestCase):
    def test_public_ipadc_uses_the_core_controller_owner(self) -> None:
        sentinel = object()
        with mock.patch.object(
            controller_owner, "controller", return_value=sentinel
        ) as implementation:
            result = ipadc("status")
        self.assertIs(result, sentinel)
        implementation.assert_called_once_with("status")
        self.assertIn(
            "from ipad_agent.core.controller import controller",
            inspect.getsource(ipadc),
        )

    def test_historical_controller_is_a_true_module_object_alias(self) -> None:
        historical = importlib.import_module("ipad_agent.controller")
        self.assertIs(historical, controller_owner)

    def test_historical_core_commands_controller_is_a_lazy_forward(self) -> None:
        sentinel = object()
        with mock.patch.object(
            controller_owner, "controller", return_value=sentinel
        ) as implementation:
            result = commands.controller("open", "Safari")
        self.assertIs(result, sentinel)
        implementation.assert_called_once_with("open", "Safari")
        self.assertIn(
            "from ipad_agent.core.controller import controller as implementation",
            inspect.getsource(commands.controller),
        )

    def test_controller_owner_keeps_shared_effects_behind_lazy_helpers(self) -> None:
        source = inspect.getsource(controller_owner.controller)
        self.assertIn("from ipad_agent.core import commands as shared", source)
        self.assertNotIn("open_ipad_when_unlocked", source)
        self.assertNotIn("ipad_agent.transports", source)


if __name__ == "__main__":
    unittest.main()
