from __future__ import annotations

import ast
import importlib
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ipad_agent"
ALIASES = {
    "controller": "core.controller",
    "api": "core.results",
    "operations": "core.operations",
    "config": "core.config",
    "paths": "core.paths",
    "registry": "core.registry",
    "urlroutes": "core.urlroutes",
    "coredevice": "transports.coredevice",
    "airdrop": "transports.airdrop",
    "wda": "transports.wda",
    "display": "legacy.display",
    "runtime": "runtime.engine",
    "daemon": "runtime.daemon",
    "server": "runtime.server",
    "bootstrap": "maintenance.bootstrap",
    "setup": "maintenance.setup",
    "doctor": "maintenance.doctor",
    "cleanup": "maintenance.cleanup",
    "versions": "maintenance.versions",
}


class SharedModuleArchitectureStage2Tests(unittest.TestCase):
    def test_implementations_live_only_in_the_approved_packages(self) -> None:
        for old_name, relocated_name in ALIASES.items():
            with self.subTest(module=old_name):
                relocated = PACKAGE.joinpath(*relocated_name.split(".")).with_suffix(".py")
                self.assertTrue(relocated.is_file(), relocated)
                if old_name != "runtime":
                    shim = PACKAGE / f"{old_name}.py"
                    tree = ast.parse(shim.read_text(encoding="utf-8"), filename=str(shim))
                    definitions = [
                        node for node in ast.walk(tree)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    ]
                    self.assertEqual([], definitions, f"implementation remains in {shim}")
        self.assertTrue((PACKAGE / "legacy" / "__init__.py").is_file())
        self.assertFalse((PACKAGE / "legacy.py").exists())

    def test_historical_imports_alias_the_relocated_module_objects(self) -> None:
        for old_name, relocated_name in ALIASES.items():
            with self.subTest(module=old_name):
                old = importlib.import_module(f"ipad_agent.{old_name}")
                relocated = importlib.import_module(f"ipad_agent.{relocated_name}")
                self.assertIs(old, relocated)
                expected = PACKAGE.joinpath(*relocated_name.split(".")).with_suffix(".py")
                self.assertEqual(expected.resolve(), Path(relocated.__file__).resolve())

        commands = importlib.import_module("ipad_agent.commands")
        shared_commands = importlib.import_module("ipad_agent.core.commands")
        self.assertIsNot(commands, shared_commands)
        self.assertIs(commands._direct_open, shared_commands._direct_open)
        for name in ("preview", "books", "files", "settings", "clock", "maps"):
            self.assertTrue(callable(getattr(commands, name)))

        display = importlib.import_module("ipad_agent.display")
        legacy_display = importlib.import_module("ipad_agent.legacy.display")
        transport_display = importlib.import_module("ipad_agent.transports.display")
        self.assertIs(display, legacy_display)
        self.assertIs(transport_display, legacy_display)
        transport_shim = PACKAGE / "transports" / "display.py"
        transport_tree = ast.parse(
            transport_shim.read_text(encoding="utf-8"), filename=str(transport_shim)
        )
        self.assertEqual(
            [],
            [
                node for node in ast.walk(transport_tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ],
        )
        marker = object()
        with patch("ipad_agent.display._launch", marker):
            self.assertIs(legacy_display._launch, marker)
            self.assertIs(transport_display._launch, marker)

        engine = importlib.import_module("ipad_agent.runtime.engine")
        with patch("ipad_agent.runtime._client_send", marker):
            self.assertIs(engine._client_send, marker)


if __name__ == "__main__":
    unittest.main()
