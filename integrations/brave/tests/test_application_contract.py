from __future__ import annotations

import ast
from pathlib import Path
import unittest

from integrations._skill_test_support import assert_public_wrapper_forwarding
from integrations.brave import commands


EXPECTED_COMMANDS = (
    "website",
    "youtube",
    "search",
    "private-website",
    "ipfs",
    "ipns",
)


class BraveApplicationContractTests(unittest.TestCase):
    def test_public_wrapper_forwards_to_application_adapter(self) -> None:
        assert_public_wrapper_forwarding(
            self, public_name="ipadbrave", package="brave", implementation="brave"
        )

    def test_current_command_surface_is_explicit(self) -> None:
        self.assertEqual(commands.COMMANDS, EXPECTED_COMMANDS)
        self.assertEqual(len(commands.COMMANDS), len(set(commands.COMMANDS)))
        self.assertNotIn("_probe_candidate", commands.COMMANDS)
        self.assertEqual(commands.__all__, ["brave"])

    def test_skill_examples_are_one_call_and_expose_only_admitted_routes(self) -> None:
        text = Path(commands.__file__).with_name("SKILL.md").read_text(encoding="utf-8")
        blocks = text.split("```python\n")[1:]
        calls: list[ast.Call] = []
        for block in blocks:
            tree = ast.parse(block.split("```", 1)[0])
            calls.extend(node for node in ast.walk(tree) if isinstance(node, ast.Call))
        documented = {
            call.args[0].value
            for call in calls
            if isinstance(call.func, ast.Name)
            and call.func.id == "ipadbrave"
            and call.args
            and isinstance(call.args[0], ast.Constant)
        }
        self.assertEqual(documented, {"website", "youtube", "search"})
        for non_production_route in ("private-website", "ipfs", "ipns"):
            self.assertIn(f"`{non_production_route}`", text)
        self.assertNotIn("_probe_candidate", text)


if __name__ == "__main__":
    unittest.main()
