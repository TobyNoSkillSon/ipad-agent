from __future__ import annotations

import inspect
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse

import ipad_agent
from ipad_agent import (
    ipadappstore,
    ipadbooks,
    ipadbrave,
    ipadc,
    ipadclock,
    ipadfiles,
    ipadmaps,
    ipadpreview,
    ipadsafari,
    ipadsettings,
)
from ipad_agent import commands, coredevice


SUCCESS = {"ok": True, "route": "test"}


class SemanticSurfaceV1Tests(unittest.TestCase):
    def test_package_exports_only_the_semantic_surface_and_result_types(self) -> None:
        expected = {
            "ipadc",
            "ipadpreview",
            "ipadbooks",
            "ipadfiles",
            "ipadsettings",
            "ipadclock",
            "ipadappstore",
            "ipadbrave",
            "ipadsafari",
            "ipadmaps",
            "Config",
            "IPadResult",
        }
        self.assertEqual(set(ipad_agent.__all__), expected)
        self.assertEqual(set(dir(ipad_agent)), expected)
        for removed in ("ip", "ipad", "sh", "show"):
            self.assertFalse(hasattr(ipad_agent, removed))

        functions = (
            ipadc,
            ipadpreview,
            ipadbooks,
            ipadfiles,
            ipadsettings,
            ipadclock,
            ipadappstore,
            ipadbrave,
            ipadsafari,
            ipadmaps,
        )
        self.assertTrue(all(inspect.isfunction(function) for function in functions))
        for function in functions:
            public = set(inspect.signature(function).parameters)
            self.assertTrue({"selector", "opcode", "wda", "session"}.isdisjoint(public))

    def test_package_and_semantic_imports_are_inert(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import os, pathlib, sys; "
                "before=dict(os.environ); runtime=pathlib.Path.cwd()/'.runtime'; "
                "existed=runtime.exists(); "
                "from ipad_agent import ipadc, ipadpreview, ipadbooks, ipadfiles, "
                "ipadsettings, ipadclock, ipadappstore, ipadbrave, ipadsafari, ipadmaps; "
                "assert 'ipad_agent.api' not in sys.modules; "
                "assert 'ipad_agent.runtime' not in sys.modules; "
                "assert 'ipad_agent.config' not in sys.modules; "
                "assert 'ipad_agent.registry' not in sys.modules; "
                "assert not any(name.startswith('ipad_agent.lab') for name in sys.modules); "
                "assert dict(os.environ)==before; assert runtime.exists()==existed",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_legacy_names_require_the_explicit_compatibility_module(self) -> None:
        from ipad_agent import legacy

        self.assertEqual(legacy.__all__, ["ip", "ipad", "sh", "show"])
        self.assertIs(legacy.ip, legacy.ipad)
        self.assertIs(legacy.sh, legacy.show)
        self.assertFalse(legacy._context_loaded)

        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import sys; from ipad_agent.legacy import ip, ipad, sh, show; "
                "import ipad_agent.legacy as legacy; "
                "assert ip is ipad and sh is show; "
                "assert legacy._context_loaded is False; "
                "assert 'ipad_agent.config' not in sys.modules; "
                "assert 'ipad_agent.registry' not in sys.modules; "
                "assert 'ipad_agent.api' not in sys.modules",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_semantic_runtime_bridge_imports_api_not_root_legacy_names(self) -> None:
        source = inspect.getsource(commands._runtime_ip)
        self.assertIn("from .api import ipad", source)
        self.assertNotIn("from . import", source)

    def test_direct_launch_adapter_targets_unlock_gated_coredevice_helper(self) -> None:
        launch = SimpleNamespace(
            bundle_id="com.example.App",
            device_id="device-1",
            elapsed_seconds=0.1,
            url=None,
            locked=False,
        )
        outcome = SimpleNamespace(status="dispatched", value=launch)
        with mock.patch.object(
            coredevice, "open_ipad_when_unlocked", return_value=outcome, create=True
        ) as helper, mock.patch.object(commands, "_runtime_ip") as legacy:
            result = commands._direct_open("Example")

        self.assertTrue(result["ok"])
        self.assertEqual(result["route"], "coredevice")
        helper.assert_called_once_with("Example")
        legacy.assert_not_called()

        with mock.patch.object(
            coredevice, "open_ipad_when_unlocked", return_value=outcome
        ) as helper:
            result = commands._direct_open("Safari", "https://example.com")
        self.assertTrue(result["ok"])
        helper.assert_called_once_with("Safari", url="https://example.com")

        for status, expected in (("locked", "locked"), ("unknown", "lock state")):
            with self.subTest(status=status), mock.patch.object(
                coredevice,
                "open_ipad_when_unlocked",
                return_value=SimpleNamespace(status=status, value=None),
                create=True,
            ):
                result = commands._direct_open("Example")
            self.assertFalse(result["ok"])
            self.assertIn(expected, result["error"])

    def test_core_surface_is_only_open_drop_status(self) -> None:
        with mock.patch.object(commands, "_direct_open", return_value=SUCCESS) as direct, mock.patch.object(
            commands, "_runtime_ip", return_value=SUCCESS
        ) as legacy:
            self.assertTrue(ipadc("open", "Brave")["ok"])
            self.assertTrue(ipadc("status")["ok"])
            self.assertFalse(ipadc("display", "legacy Now content")["ok"])
            self.assertFalse(ipadc("send", "/tmp/legacy")["ok"])

        direct.assert_called_once_with("Brave")
        legacy.assert_called_once_with("q")

    def test_preview_books_and_files_only_open_drop_show(self) -> None:
        calls: list[tuple[object, ...]] = []

        def direct(*args: object):
            calls.append(args)
            return {"ok": True, "route": "coredevice"}

        received: list[Path] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.pdf"
            path.write_bytes(b"PDF")
            backend = SimpleNamespace(
                airdrop=lambda value: received.append(value) or {"status": "completed", "route": "airdrop"}
            )
            with mock.patch.object(commands.importlib, "import_module", return_value=backend), mock.patch.object(
                commands, "_direct_open", side_effect=direct
            ), mock.patch.object(coredevice, "wait_for_ipad_unlocked", return_value="unlocked") as preflight:
                self.assertTrue(ipadpreview("open")["ok"])
                dropped = ipadbooks("drop", path)
                shown = ipadfiles("show", path)

        self.assertTrue(dropped["ok"])
        self.assertFalse(shown["ok"])
        self.assertEqual(shown["status"], "pending")
        self.assertTrue(shown["transfer_complete"])
        self.assertFalse(shown["handoff_verified"])
        self.assertFalse(shown["shown"])
        self.assertEqual(shown["transfer"]["status"], "completed")
        self.assertEqual(
            repr(shown),
            "failed: file transferred; exact handoff to Files is unverified",
        )
        self.assertEqual(preflight.call_count, 2)
        self.assertEqual(calls, [("Preview",), ("Files",)])
        self.assertEqual(received, [path.resolve(), path.resolve()])

        with mock.patch.object(commands, "_direct_open") as direct, mock.patch.object(
            commands, "_runtime_ip"
        ) as legacy:
            for function, operation in (
                (ipadpreview, "file"),
                (ipadbooks, "library"),
                (ipadbooks, "search"),
                (ipadfiles, "recents"),
                (ipadfiles, "browse"),
                (ipadfiles, "search"),
                (ipadfiles, "send"),
            ):
                with self.subTest(function=function.__name__, operation=operation):
                    self.assertFalse(function(operation)["ok"])
            direct.assert_not_called()
            legacy.assert_not_called()

    def test_drop_and_show_preserve_structural_uncertain_and_do_not_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "uncertain.pdf"
            path.write_bytes(b"PDF")
            backend = SimpleNamespace(
                airdrop=lambda value: {
                    "ok": True,
                    "status": "uncertain",
                    "reason": "response lost after dispatch",
                }
            )
            with mock.patch.object(commands.importlib, "import_module", return_value=backend), mock.patch.object(
                commands, "_direct_open"
            ) as direct, mock.patch.object(
                coredevice, "wait_for_ipad_unlocked", return_value="unlocked"
            ) as preflight:
                dropped = ipadpreview("drop", path)
                shown = ipadpreview("show", path)

        for result in (dropped, shown):
            self.assertFalse(result["ok"])
            self.assertTrue(result["uncertain"])
            self.assertEqual(result["status"], "uncertain")
        direct.assert_not_called()
        self.assertEqual(preflight.call_count, 2)

    def test_airdrop_lock_preflight_blocks_host_dispatch_and_show_handoff(self) -> None:
        for state, expected in (("locked", "locked"), ("unknown", "lock state")):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "document.pdf"
                path.write_bytes(b"PDF")
                backend = mock.Mock(return_value={"status": "completed"})
                module = SimpleNamespace(airdrop=backend)
                with mock.patch.object(
                    commands.importlib, "import_module", return_value=module
                ), mock.patch.object(
                    coredevice, "wait_for_ipad_unlocked", return_value=state
                ) as preflight, mock.patch.object(commands, "_direct_open") as direct:
                    dropped = ipadpreview("drop", path)
                    shown = ipadpreview("show", path)

            self.assertFalse(dropped["ok"])
            self.assertFalse(shown["ok"])
            self.assertIn(expected, dropped["error"])
            self.assertEqual(preflight.call_count, 2)
            backend.assert_not_called()
            direct.assert_not_called()

    def test_missing_airdrop_backend_fails_without_launch(self) -> None:
        missing = ModuleNotFoundError("no airdrop backend", name="ipad_agent.airdrop")
        with mock.patch.object(commands.importlib, "import_module", side_effect=missing) as importer, mock.patch.object(
            commands, "_direct_open"
        ) as direct:
            result = ipadpreview("drop", "/tmp/anything.pdf")
        self.assertFalse(result["ok"])
        self.assertIn("unsupported", result["error"])
        importer.assert_called_once_with("ipad_agent.airdrop")
        direct.assert_not_called()

    def test_settings_allowlist_uses_hidden_wda_and_guarantees_teardown(self) -> None:
        calls: list[tuple[object, ...]] = []

        def legacy(*args: object):
            calls.append(args)
            if args[0] == "b":
                return {"ok": False, "error": "control not ready", "uncertain": False}
            return SUCCESS

        with mock.patch.object(commands, "_direct_open", return_value=SUCCESS) as direct, mock.patch.object(
            commands, "_runtime_ip", side_effect=legacy
        ), mock.patch.object(
            coredevice, "wait_for_ipad_unlocked", return_value="unlocked"
        ) as preflight:
            result = ipadsettings("about")

        self.assertFalse(result["ok"])
        direct.assert_called_once_with("Settings")
        preflight.assert_called_once_with()
        self.assertEqual(calls[-1], ("x",))
        self.assertEqual(sum(call == ("x",) for call in calls), 1)
        hidden_batch = calls[0][1]
        self.assertEqual(hidden_batch[0], ["t", "settings.general"])
        self.assertEqual(hidden_batch[-1], ["t", "accessibility id=About"])

        with mock.patch.object(commands, "_direct_open") as direct, mock.patch.object(
            commands, "_runtime_ip"
        ) as legacy:
            for unsafe in ("toggle wifi", "join", "update", "reset", "privacy", "account"):
                self.assertFalse(ipadsettings(unsafe)["ok"])
            direct.assert_not_called()
            legacy.assert_not_called()

    def test_settings_rechecks_unlock_immediately_before_wda(self) -> None:
        with mock.patch.object(
            commands, "_direct_open", return_value=SUCCESS
        ) as direct, mock.patch.object(
            coredevice, "wait_for_ipad_unlocked", return_value="locked"
        ) as preflight, mock.patch.object(commands, "_runtime_ip", return_value=SUCCESS) as legacy:
            result = ipadsettings("general")

        self.assertFalse(result["ok"])
        self.assertTrue(result["locked"])
        direct.assert_called_once_with("Settings")
        preflight.assert_called_once_with()
        self.assertEqual(legacy.call_args_list, [mock.call("x")])

    def test_settings_safe_destinations_and_clock_open_only(self) -> None:
        for destination in ("general", "about", "wifi", "bluetooth", "battery", "accessibility"):
            calls: list[tuple[object, ...]] = []
            with self.subTest(destination=destination), mock.patch.object(
                commands, "_direct_open", return_value=SUCCESS
            ), mock.patch.object(
                commands, "_runtime_ip", side_effect=lambda *args: calls.append(args) or SUCCESS
            ), mock.patch.object(
                coredevice, "wait_for_ipad_unlocked", return_value="unlocked"
            ):
                self.assertTrue(ipadsettings(destination)["ok"])
            self.assertEqual(calls[-1], ("x",))

        with mock.patch.object(commands, "_direct_open", return_value=SUCCESS) as direct, mock.patch.object(
            commands, "_runtime_ip"
        ) as legacy:
            self.assertTrue(ipadclock("open")["ok"])
            for removed in ("world clock", "alarms", "stopwatch", "timer", "timers"):
                self.assertFalse(ipadclock(removed)["ok"])
        direct.assert_called_once_with("Clock")
        legacy.assert_not_called()

    def test_app_store_open_and_validated_product_show_only(self) -> None:
        calls: list[tuple[object, ...]] = []
        with mock.patch.object(
            commands, "_direct_open", side_effect=lambda *args: calls.append(args) or SUCCESS
        ), mock.patch.object(commands, "_runtime_ip") as legacy:
            self.assertTrue(ipadappstore("open")["ok"])
            self.assertTrue(ipadappstore("show", 123456789)["ok"])
            url = "https://apps.apple.com/gb/app/example/id987654321?mt=8"
            self.assertTrue(ipadappstore("show", url)["ok"])
            for command in ("get", "install", "today", "games", "apps", "arcade", "search"):
                self.assertFalse(ipadappstore(command)["ok"])
            self.assertFalse(ipadappstore("show", "https://example.com/app/id1")["ok"])
            self.assertFalse(ipadappstore("show", "https://apps.apple.com/app/example")["ok"])

        self.assertEqual(
            calls,
            [
                ("App Store",),
                ("App Store", "https://apps.apple.com/app/id123456789"),
                ("App Store", url),
            ],
        )
        legacy.assert_not_called()

    def test_browser_surface_is_website_or_youtube_only(self) -> None:
        calls: list[tuple[object, ...]] = []
        with mock.patch.object(
            commands, "_direct_open", side_effect=lambda *args: calls.append(args) or SUCCESS
        ), mock.patch.object(commands, "_runtime_ip") as legacy:
            self.assertTrue(ipadc("open", "Safari")["ok"])
            self.assertTrue(ipadc("open", "Brave")["ok"])
            self.assertTrue(ipadsafari("website", "https://example.com/a")["ok"])
            self.assertTrue(ipadbrave("youtube", "https://youtu.be/abc?x=1", at=90)["ok"])
            for removed in ("open", "show", "back", "reload", "tabs"):
                self.assertFalse(ipadbrave(removed)["ok"])
                self.assertFalse(ipadsafari(removed)["ok"])
            self.assertFalse(ipadsafari("open", "https://example.com")["ok"])

        youtube = urlparse(str(calls[3][1]))
        self.assertEqual(parse_qs(youtube.query)["t"], ["90s"])
        self.assertEqual(calls[0], ("Safari",))
        self.assertEqual(calls[1], ("Brave",))
        self.assertEqual(calls[2], ("Safari", "https://example.com/a"))
        legacy.assert_not_called()

    def test_maps_surface_is_show_only(self) -> None:
        calls: list[tuple[object, ...]] = []
        with mock.patch.object(
            commands, "_direct_open", side_effect=lambda *args: calls.append(args) or SUCCESS
        ), mock.patch.object(commands, "_runtime_ip") as legacy:
            self.assertTrue(ipadc("open", "Maps")["ok"])
            self.assertFalse(ipadmaps("open")["ok"])
            self.assertTrue(ipadmaps("show", "Warsaw & Praga")["ok"])
            self.assertFalse(ipadmaps("search", "Warsaw")["ok"])
            self.assertFalse(ipadmaps("directions", "Gdańsk")["ok"])

        self.assertEqual(calls[0], ("Maps",))
        query = parse_qs(urlparse(str(calls[1][1])).query)
        self.assertEqual(query, {"q": ["Warsaw & Praga"]})
        legacy.assert_not_called()

    def test_compact_opcodes_and_invalid_destinations_fail_before_dispatch(self) -> None:
        with mock.patch.object(commands, "_direct_open") as direct, mock.patch.object(
            commands, "_runtime_ip"
        ) as legacy:
            for function, operation in (
                (ipadc, "o"),
                (ipadpreview, "d"),
                (ipadbooks, "s"),
                (ipadfiles, "t"),
                (ipadsettings, "w"),
                (ipadclock, "x"),
                (ipadappstore, "g"),
                (ipadbrave, "b"),
                (ipadsafari, "r"),
                (ipadmaps, "m"),
            ):
                result = function(operation)
                self.assertFalse(result["ok"])
                self.assertIn("unsupported command", result["error"])
            self.assertFalse(ipadsafari("website", "file:///tmp/a")["ok"])
            self.assertFalse(ipadbrave("youtube", "https://example.com/video", at=1)["ok"])
            self.assertFalse(ipadmaps("show", "   ")["ok"])
            direct.assert_not_called()
            legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
