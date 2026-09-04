from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
import unittest
from unittest import mock

from ipad_agent import ipadbooks, ipadfiles, ipadpreview, ipadsettings
from ipad_agent.core import commands as shared


ROOT = Path(__file__).resolve().parents[1]


class CodeOwnershipStage4Tests(unittest.TestCase):
    def test_shared_commands_has_no_integration_dependency_or_app_selection(self) -> None:
        path = ROOT / "ipad_agent/core/commands.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        self.assertFalse(any(name.startswith("integrations") for name in imported))
        self.assertNotIn("integrations.", source)
        self.assertNotIn("def _local_app", source)
        self.assertNotIn("def _settings_ui", source)
        for name in ("preview", "books", "files", "settings", "clock", "maps"):
            self.assertNotIn(f"def {name}(", source)
            self.assertFalse(hasattr(shared, name))

    def test_local_file_adapters_own_selection_and_validation(self) -> None:
        for package, function, target in (("preview","preview","Preview"),("books","books","Books"),("files","files","Files")):
            with self.subTest(package=package):
                module = importlib.import_module(f"integrations.{package}.commands")
                source = inspect.getsource(getattr(module, function))
                self.assertTrue({"open", "drop", "show"}.issubset(module.COMMANDS))
                self.assertIn(f'_direct_open("{target}")', source)
                self.assertIn("_airdrop", source)
                self.assertIn("_show_local", source)
                self.assertNotIn("_local_app", source)

    def test_settings_owns_proof_gating_and_shared_core_owns_direct_dispatch(self) -> None:
        module = importlib.import_module("integrations.settings.commands")
        adapter = inspect.getsource(module)
        direct_dispatch = inspect.getsource(shared._direct_open)

        for owned in (
            "_PROFILE_PATH",
            "_CATALOG_PATH",
            "def _load_device_profile",
            "def _load_catalog",
            "def _validate_route",
            "def _open_proven",
        ):
            self.assertIn(owned, adapter)
        self.assertEqual(
            ("open", "general", "about", "wifi", "bluetooth", "battery", "accessibility", "show"),
            module.COMMANDS,
        )
        self.assertEqual(["settings"], module.__all__)
        self.assertFalse(hasattr(module, "_probe_candidate"))
        self.assertIn('shared._direct_open("Settings", str(route["url"]))', adapter)
        self.assertNotIn("route-catalog.json", inspect.getsource(shared))
        self.assertNotIn("settings-navigation://", inspect.getsource(shared))
        self.assertNotIn("_runtime_ip", inspect.getsource(module.settings))
        for forbidden in ("_bounded_wda_lifecycle", "appium", "xcuitest", "selector"):
            self.assertNotIn(forbidden, adapter.casefold())

        self.assertIn('import_module("ipad_agent.transports.coredevice")', direct_dispatch)
        self.assertIn('getattr(coredevice, "open_ipad_when_unlocked")', direct_dispatch)
        self.assertNotIn("Settings", direct_dispatch)

    def test_airdrop_preflight_failure_does_not_expose_local_path(self) -> None:
        private_path = "/tmp/private-person/Secret Folder/report.pdf"
        result = shared._airdrop(private_path)
        self.assertFalse(result["ok"])
        self.assertNotIn("private-person", result["error"])
        self.assertNotIn("Secret Folder", result["error"])
        with mock.patch(
            "ipad_agent.transports.coredevice.wait_for_ipad_unlocked",
            side_effect=RuntimeError("/tmp/private-person/device-output"),
        ):
            preflight = shared._unlock_preflight()
        self.assertFalse(preflight["ok"])
        self.assertNotIn("private-person", preflight["error"])

    def test_candidate_helpers_are_structurally_non_dispatching(self) -> None:
        forbidden = {
            "_direct_open", "_validated_route_open", "_airdrop", "_show_local",
            "open_ipad", "open_ipad_when_unlocked", "open_validated_route_when_unlocked",
        }
        for path in sorted((ROOT / "integrations").glob("*/commands.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            self.assertFalse(any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_probe_candidate"
                for node in tree.body
            ), f"{path.relative_to(ROOT)} retains an obsolete candidate probe")
            planners = [
                node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_plan_candidate"
            ]
            for probe in planners:
                called = {
                    node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                    for node in ast.walk(probe)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, (ast.Attribute, ast.Name))
                }
                self.assertTrue(
                    forbidden.isdisjoint(called),
                    f"{path.relative_to(ROOT)} candidate helper can dispatch: {sorted(forbidden & called)}",
                )

    def test_canonical_shared_monkeypatches_reach_application_adapters(self) -> None:
        sentinel = {"ok": True, "route": "patched"}
        with mock.patch.object(shared, "_direct_open", return_value=sentinel) as direct:
            self.assertIs(ipadpreview("open"), sentinel)
            self.assertIs(ipadbooks("open"), sentinel)
            self.assertIs(ipadfiles("open"), sentinel)
            self.assertIs(ipadsettings("open"), sentinel)
        self.assertEqual(direct.call_count, 4)


if __name__ == "__main__":
    unittest.main()
