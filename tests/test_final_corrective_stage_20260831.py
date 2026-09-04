from __future__ import annotations

from email.message import Message
import importlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.error import HTTPError

from integrations.apple_maps import commands as maps_commands
from ipad_agent import commands as command_facade
from ipad_agent.config import Config
from ipad_agent.core import commands as shared
from ipad_agent.core.operations import OperationResult, OperationSpec, SafetyClass
from ipad_agent.core.projection import public_result
from ipad_agent.core import results
from ipad_agent.registry import IntegrationRegistry, RegistryError, load_registry
from ipad_agent.runtime import engine as runtime
from ipad_agent.transports import http
from scripts import release_check


ROOT = Path(__file__).resolve().parents[1]
_PRIVATE_KEYS = {"argv", "command", "device", "device_id", "raw_command", "stderr", "stdout", "url"}


def _assert_redacted(case: unittest.TestCase, value: object) -> None:
    if isinstance(value, dict):
        case.assertTrue(_PRIVATE_KEYS.isdisjoint({str(key).casefold() for key in value}))
        for item in value.values():
            _assert_redacted(case, item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_redacted(case, item)


class FinalCorrectiveStageTests(unittest.TestCase):
    def test_required_core_removal_fails_registry_and_release_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "integrations", root / "integrations")
            shutil.copytree(ROOT / "schemas", root / "schemas")
            index_path = root / "integrations/index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["integrations"] = [
                entry for entry in index["integrations"] if entry["id"] != "maps"
            ]
            index_path.write_text(json.dumps(index) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(
                RegistryError, "required core integration.*maps"
            ):
                IntegrationRegistry(index_path)

            candidates = {
                path.relative_to(root).as_posix()
                for path in root.rglob("*") if path.is_file()
            }
            issues = release_check.validate_manifests(root, candidates)
            self.assertTrue(
                any("required core integration" in issue and "maps" in issue for issue in issues),
                issues,
            )

    def test_historical_browser_accepts_registry_selectors_and_exact_bundles(self) -> None:
        cases = (
            (Config(), "Safari", "safari", "safari"),
            (Config(), "Apple Safari", "safari", "safari"),
            (Config(), "com.apple.mobilesafari", "safari", "safari"),
            (Config(enabled_addons=["brave"]), "Brave Browser", "brave", "brave"),
            (Config(enabled_addons=["brave"]), "com.brave.ios.browser", "brave", "brave"),
        )
        for config, target, module, function in cases:
            with self.subTest(target=target), mock.patch(
                "ipad_agent.core.config.load_config", return_value=config
            ), mock.patch.object(
                command_facade._forwards, "_application_command", return_value={"ok": True}
            ) as adapter:
                result = command_facade.browser(target, "website", "https://example.com")
            self.assertTrue(result["ok"])
            adapter.assert_called_once_with(
                module, function, "website", "https://example.com"
            )

        with mock.patch(
            "ipad_agent.core.config.load_config", return_value=Config()
        ), mock.patch.object(command_facade._forwards, "_application_command") as adapter:
            disabled = command_facade.browser(
                "com.brave.ios.browser", "website", "https://example.com"
            )
        self.assertFalse(disabled["ok"])
        self.assertIn("not enabled", disabled["error"])
        adapter.assert_not_called()

    def test_public_compatibility_results_recursively_redact_private_transport_data(self) -> None:
        raw = {
            "ok": True,
            "route": "coredevice",
            "device_id": "private-device",
            "url": "https://private.example/path",
            "nested": {
                "stdout": "private stdout",
                "stderr": "private stderr",
                "command": ["xcrun", "--device", "private-device"],
                "children": [{"raw_command": "secret", "device": "private-device"}],
            },
        }
        projected = public_result(raw)
        _assert_redacted(self, projected)

        with mock.patch.object(runtime, "argv_request", return_value={"op": "q"}), mock.patch.object(
            runtime, "dispatch_client", return_value=raw
        ):
            legacy_result = results.ipad("q")
        self.assertEqual("accepted", repr(legacy_result))
        _assert_redacted(self, legacy_result)

        with mock.patch.object(results, "_show", return_value=raw):
            display_result = results.show("a", "Safari")
        self.assertEqual("accepted", repr(display_result))
        _assert_redacted(self, display_result)

        operation = OperationSpec("open", "open", SafetyClass.NAVIGATE)
        runtime_result = runtime._project_transport(
            OperationResult.succeeded(operation, raw), path="coredevice"
        )
        _assert_redacted(self, runtime_result)

        semantic = shared._launch_payload(raw)
        self.assertEqual("accepted", repr(semantic))
        _assert_redacted(self, semantic)

    def test_display_compatibility_names_are_one_legacy_module_object(self) -> None:
        historical = importlib.import_module("ipad_agent.display")
        legacy = importlib.import_module("ipad_agent.legacy.display")
        transport = importlib.import_module("ipad_agent.transports.display")
        self.assertIs(historical, legacy)
        self.assertIs(transport, legacy)
        self.assertEqual(
            ROOT / "ipad_agent/legacy/display.py", Path(legacy.__file__).resolve()
        )

    def test_generic_http_transport_returns_one_redirect_without_following(self) -> None:
        headers = Message()
        headers["Location"] = "https://maps.apple.com/search?query=Warsaw"
        redirect = HTTPError(
            "https://abc.maps.apple/token", 302, "Found", headers, None
        )
        opener = mock.Mock()
        opener.open.side_effect = redirect
        with mock.patch.object(http, "build_opener", return_value=opener) as build:
            location = http.resolve_one_redirect("https://abc.maps.apple/token", timeout=2)
        self.assertEqual(headers["Location"], location)
        self.assertIsInstance(build.call_args.args[0], http._RejectRedirects)
        request = opener.open.call_args.args[0]
        self.assertEqual("bytes=0-0", request.get_header("Range"))
        self.assertEqual(2.0, opener.open.call_args.kwargs["timeout"])

    def test_maps_short_redirect_target_is_revalidated_by_inert_policy(self) -> None:
        arguments, options = maps_commands._maps_arguments(
            "link",
            ("https://abc.maps.apple/token",),
            {},
            resolver=lambda _url: "https://evil.example/private",
        )
        with self.assertRaisesRegex(ValueError, "host|route|match"):
            load_registry().resolve_url_route("maps", "link", arguments, options)


if __name__ == "__main__":
    unittest.main()
