from __future__ import annotations

import ast
from pathlib import Path
import unittest

from integrations._skill_test_support import assert_public_wrapper_forwarding
from integrations.apple_maps import commands


EXPECTED_COMMANDS = (
    "open",
    "frame",
    "search",
    "show",
    "place",
    "look-around",
    "directions",
    "navigate",
    "guides",
    "report-a-problem",
    "link",
)


class AppleMapsApplicationContractTests(unittest.TestCase):
    def test_public_ipadmaps_wrapper_is_unchanged(self) -> None:
        assert_public_wrapper_forwarding(
            self,
            public_name="ipadmaps",
            package="apple_maps",
            implementation="maps",
        )

    def test_current_command_surface_is_exact(self) -> None:
        self.assertEqual(commands.COMMANDS, EXPECTED_COMMANDS)
        self.assertEqual(len(commands.COMMANDS), len(set(commands.COMMANDS)))
        self.assertNotIn("_plan_candidate", commands.COMMANDS)
        self.assertEqual(commands.__all__, ["maps"])

    def test_compact_skill_has_one_bare_open_call(self) -> None:
        path = Path(commands.__file__).with_name("SKILL.md")
        text = path.read_text(encoding="utf-8")
        blocks = text.split("```python\n")[1:]
        calls: list[ast.Call] = []
        for block in blocks:
            tree = ast.parse(block.split("```", 1)[0])
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    calls.append(node)
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0].func, ast.Name)
        self.assertEqual(calls[0].func.id, "ipadmaps")
        self.assertEqual(calls[0].args[0].value, "open")
        self.assertNotIn("_plan_candidate", text)
        self.assertIn("WORKFLOWS.md", text)


if __name__ == "__main__":
    unittest.main()
