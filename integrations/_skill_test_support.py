"""Shared assertions for colocated application contract tests."""
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
import re
from unittest import mock


_FENCED_PYTHON = re.compile(r"```python\n(.*?)```", re.DOTALL)


def assert_public_wrapper_forwarding(
    case, *, public_name: str, package: str, implementation: str
) -> None:
    public = getattr(importlib.import_module("ipad_agent"), public_name)
    sentinel = object()
    with mock.patch(
        f"integrations.{package}.commands.{implementation}", return_value=sentinel
    ) as command:
        result = public("probe", "value", option=3)
    case.assertIs(result, sentinel)
    command.assert_called_once_with("probe", "value", option=3)


def assert_command_surface(case, *, package: str, expected: tuple[str, ...]) -> None:
    module = importlib.import_module(f"integrations.{package}.commands")
    case.assertEqual(module.COMMANDS, expected)
    case.assertEqual(len(module.COMMANDS), len(set(module.COMMANDS)))
    if package == "apple_maps":
        policy = json.loads((Path(module.__file__).with_name("url-policy.json")).read_text())
        declared = []
        for command, definition in policy["commands"].items():
            declared.append(command)
            declared.extend(definition["aliases"])
        case.assertEqual(set(module.COMMANDS), set(declared))


def assert_skill_alignment(
    case, *, package: str, public_name: str, expected: tuple[str, ...]
) -> None:
    directory = Path(importlib.import_module(f"integrations.{package}").__file__).parent
    text = (directory / "SKILL.md").read_text()
    blocks = _FENCED_PYTHON.findall(text)
    case.assertTrue(blocks, "SKILL.md must contain Python examples")
    documented: list[str] = []
    for block in blocks:
        tree = ast.parse(block)
        for statement in tree.body:
            case.assertNotIsInstance(
                statement, (ast.Assign, ast.AnnAssign, ast.AugAssign),
                "examples must be bare calls, never result assignments",
            )
            if not isinstance(statement, ast.Expr):
                continue
            case.assertIsInstance(statement.value, ast.Call, "each example statement is one call")
            call = statement.value
            if isinstance(call.func, ast.Name) and call.func.id == public_name:
                case.assertTrue(call.args, f"{public_name} examples require a command")
                case.assertIsInstance(call.args[0], ast.Constant)
                case.assertIsInstance(call.args[0].value, str)
                documented.append(call.args[0].value)
    case.assertEqual(set(documented), set(expected))
