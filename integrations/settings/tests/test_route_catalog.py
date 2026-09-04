from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from integrations.settings import commands


DIRECTORY = Path(commands.__file__).parent
CATALOG_PATH = DIRECTORY / "route-catalog.json"
PROFILE_PATH = DIRECTORY / "device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json"
EXPECTED_URL_DIGEST = "439229248e3b334afc82806348a6846eb495aa69eaa7c78307a9a85d295e8ec1"
EXPECTED_SCOPE = {
    "product_type": "iPad17,1",
    "hardware_model": "J817AP",
    "os_build": "23G83",
}
EXPECTED_PROVEN = {
    "accessibility",
    "accessibility-motion-title",
    "apps-com-apple-mobilesafari",
    "apps-com-apple-mobilesafari-row-private-browsing-uses-normal-browsing-search-engine-selection",
    "battery",
    "bluetooth",
    "general",
    "general-about",
    "general-international",
    "general-keyboard",
    "wi-fi",
}
EXPECTED_SHORTCUTS = {
    "general": "general",
    "about": "general-about",
    "wifi": "wi-fi",
    "bluetooth": "bluetooth",
    "battery": "battery",
    "accessibility": "accessibility",
}
EXPECTED_INCOMPATIBLE = {
    "action-button": "action_button",
    "cellular": "cellular",
    "cellular-cellular-data-options": "cellular",
    "apps-com-apple-podcasts-cellular-downloads": "cellular",
    "general-airdrop-link-row-airdrop-cellular-usage-id": "cellular",
    "personal-hotspot": "personal_hotspot",
    "camera-camera-button-settings": "camera_control",
    "general-home-button": "home_button",
    "stand-by": "standby",
    "stand-by-always-on-display-options": "standby",
}


def raw_catalog() -> dict[str, object]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def raw_profile() -> dict[str, object]:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def write_temporary_json(value: dict[str, object]) -> tempfile.NamedTemporaryFile:
    temporary = tempfile.NamedTemporaryFile(mode="w+", suffix=".json", encoding="utf-8")
    json.dump(value, temporary, ensure_ascii=False)
    temporary.flush()
    return temporary


class SettingsRouteCatalogTests(unittest.TestCase):
    def test_catalogue_counts_and_orthogonal_classification_are_pinned(self) -> None:
        routes = raw_catalog()["routes"]
        self.assertEqual(len(routes), 251)
        self.assertEqual(len({route["id"] for route in routes}), 251)
        self.assertEqual(len({route["url"] for route in routes}), 251)
        self.assertEqual(
            Counter(route["target_kind"] for route in routes),
            {"page": 201, "dynamic": 21, "action": 15, "row": 14},
        )
        self.assertEqual(
            Counter(route["dispatch_policy"] for route in routes),
            {"normal": 132, "explicit": 70, "blocked": 49},
        )
        self.assertEqual(
            Counter(route["availability"] for route in routes),
            {"candidate": 209, "template": 21, "proven": 11, "incompatible": 10},
        )
        self.assertEqual(
            Counter(evidence["kind"] for route in routes for evidence in route["evidence"]),
            {
                "runtime-literal": 248,
                "user-visual-pass": 11,
                "observer-screenshot-pass": 11,
                "profile-capability-mismatch": 10,
                "user-visual-fail": 1,
            },
        )
        indexed = {route["id"]: route for route in routes}
        self.assertEqual(indexed["action-button"]["dispatch_policy"], "normal")
        self.assertEqual(indexed["action-button"]["availability"], "incompatible")
        self.assertEqual(indexed["general-reset"]["availability"], "candidate")
        self.assertEqual(indexed["general-reset"]["dispatch_policy"], "blocked")

    def test_exact_url_bytes_and_mixed_case_are_preserved(self) -> None:
        routes = raw_catalog()["routes"]
        digest = hashlib.sha256(
            b"\0".join(route["url"].encode("utf-8") for route in routes)
        ).hexdigest()
        self.assertEqual(digest, EXPECTED_URL_DIGEST)
        indexed = {route["id"]: route["url"] for route in routes}
        self.assertEqual(
            indexed["camera-camera-formats-settings-list"],
            "settings-navigation://com.apple.Settings.Camera/CameraFormatsSettingsList",
        )
        self.assertEqual(
            indexed["apps-com-apple-mobile-sms-row-filter-new-senders-switch"],
            "settings-navigation://com.apple.Settings.Apps/com.apple.MobileSMS#FILTER_NEW_SENDERS_SWITCH",
        )
        self.assertEqual(
            indexed["siri-external-aimodel-query-view-upgrade-plan"],
            "settings-navigation://com.apple.Settings.Siri/ExternalAIModel?view=upgradePlan",
        )

    def test_non_unique_profile_has_exact_capabilities_and_sources(self) -> None:
        profile = raw_profile()
        self.assertEqual(profile["scope_type"], "model-build")
        self.assertEqual(profile["marketing_model"], "iPad Pro 11-inch (M5, Wi-Fi)")
        self.assertEqual(profile["product_type"], "iPad17,1")
        self.assertEqual(profile["hardware_model"], "J817AP")
        self.assertEqual(profile["os_version"], "26.6.1")
        self.assertEqual(profile["os_build"], "23G83")
        self.assertEqual(
            profile["capabilities"],
            {
                "form_factor": "ipad",
                "cellular": False,
                "personal_hotspot": False,
                "face_id": True,
                "home_button": False,
                "action_button": False,
                "camera_control": False,
                "standby": False,
                "top_button": True,
                "apple_pencil": True,
                "usb_c": True,
            },
        )
        self.assertEqual(
            [source["kind"] for source in profile["sources"]],
            ["devicectl", "apple-technical-specification"],
        )
        forbidden_keys = {"udid", "serial", "serial_number", "ecid", "unique_device_id"}
        self.assertTrue(forbidden_keys.isdisjoint(profile))
        commands._load_device_profile()

    def test_proven_allowlist_has_exact_user_visual_scope(self) -> None:
        indexed = commands._load_catalog()
        proven = {route_id for route_id, route in indexed.items() if route["availability"] == "proven"}
        self.assertEqual(proven, EXPECTED_PROVEN)
        self.assertEqual(proven, commands._PROVEN_ROUTE_IDS)
        for route_id in proven:
            evidence = indexed[route_id]["evidence"]
            visual = next(item for item in evidence if item["kind"] == "user-visual-pass")
            self.assertEqual(visual["actor"], "user")
            self.assertEqual(visual["result"], "expected-target-visible")
            self.assertEqual(visual["proof_scope"], EXPECTED_SCOPE)
            observer = next(
                item for item in evidence if item["kind"] == "observer-screenshot-pass"
            )
            self.assertEqual(observer["actor"], "agent")
            self.assertEqual(observer["method"], "project-owned-wda-screenshot")
            self.assertEqual(observer["result"], "expected-target-visible")
            self.assertEqual(observer["proof_scope"], EXPECTED_SCOPE)

    def test_profile_mismatch_invalidates_proof(self) -> None:
        profile = copy.deepcopy(raw_profile())
        profile["hardware_model"] = "OTHER"
        with write_temporary_json(profile) as temporary:
            with self.assertRaisesRegex(ValueError, "exact target profile scope"):
                commands._load_catalog(CATALOG_PATH, Path(temporary.name))

        catalog = copy.deepcopy(raw_catalog())
        route = next(route for route in catalog["routes"] if route["id"] == "general")
        visual = next(item for item in route["evidence"] if item["kind"] == "user-visual-pass")
        visual["proof_scope"]["os_build"] = "OTHER"
        with write_temporary_json(catalog) as temporary:
            with self.assertRaisesRegex(ValueError, "exact target profile scope"):
                commands._load_catalog(Path(temporary.name))

    def test_negative_evidence_and_capability_mismatches_are_exact(self) -> None:
        indexed = commands._load_catalog()
        incompatible = {
            route_id: route for route_id, route in indexed.items() if route["availability"] == "incompatible"
        }
        self.assertEqual(set(incompatible), set(EXPECTED_INCOMPATIBLE))
        for route_id, capability in EXPECTED_INCOMPATIBLE.items():
            mismatch = next(
                item
                for item in incompatible[route_id]["evidence"]
                if item["kind"] == "profile-capability-mismatch"
            )
            self.assertEqual(mismatch["capability"], capability)
            self.assertIs(mismatch["required"], True)
            self.assertIs(mismatch["observed"], False)
            self.assertEqual(mismatch["proof_scope"], EXPECTED_SCOPE)

        standby = incompatible["stand-by-always-on-display-options"]
        failure = next(item for item in standby["evidence"] if item["kind"] == "user-visual-fail")
        self.assertEqual(failure["actor"], "user")
        self.assertEqual(failure["result"], "settings-launched-prior-page-remained-visible")
        self.assertEqual(failure["observed_page"], "Apple Intelligence & Siri")
        self.assertEqual(failure["proof_scope"], EXPECTED_SCOPE)
        self.assertNotIn(
            "user-visual-fail", {item["kind"] for item in incompatible["stand-by"]["evidence"]}
        )

    def test_open_is_app_activation_without_page_claim(self) -> None:
        sentinel = object()
        with mock.patch.object(commands.shared, "_direct_open", return_value=sentinel) as direct_open:
            self.assertIs(commands.settings("open"), sentinel)
        direct_open.assert_called_once_with("Settings")

    def test_every_proven_shortcut_and_show_dispatch_once(self) -> None:
        indexed = commands._load_catalog()
        sentinel = object()
        for command, route_id in EXPECTED_SHORTCUTS.items():
            with self.subTest(command=command), mock.patch.object(
                commands.shared, "_direct_open", return_value=sentinel
            ) as direct_open:
                self.assertIs(commands.settings(command), sentinel)
                direct_open.assert_called_once_with("Settings", indexed[route_id]["url"])
        for route_id in EXPECTED_PROVEN:
            with self.subTest(route_id=route_id), mock.patch.object(
                commands.shared, "_direct_open", return_value=sentinel
            ) as direct_open:
                self.assertIs(commands.settings("show", route_id), sentinel)
                direct_open.assert_called_once_with("Settings", indexed[route_id]["url"])

    def test_production_denies_candidate_incompatible_template_blocked_and_urls(self) -> None:
        route_ids = (
            "display",
            "action-button",
            "apps-placeholder",
            "general-reset",
            "general-reset-exit-buddy",
        )
        for route_id in route_ids:
            with self.subTest(route_id=route_id), mock.patch.object(
                commands.shared, "_direct_open"
            ) as direct_open:
                result = commands.settings("show", route_id)
                self.assertFalse(result["ok"])
                direct_open.assert_not_called()
        for value in (
            "settings-navigation://com.apple.Settings.General",
            "https://example.com",
            "missing-id",
        ):
            with self.subTest(value=value), mock.patch.object(
                commands.shared, "_direct_open"
            ) as direct_open:
                result = commands.settings("show", value)
                self.assertFalse(result["ok"])
                direct_open.assert_not_called()

    def test_candidate_routes_have_no_dispatch_helper(self) -> None:
        self.assertFalse(hasattr(commands, "_probe_candidate"))
        self.assertNotIn("_probe_candidate", commands.__all__)

    def test_dynamic_routes_are_templates_and_remain_blocked(self) -> None:
        for route in commands._load_catalog().values():
            if route["target_kind"] == "dynamic":
                self.assertEqual(route["availability"], "template")
                self.assertEqual(route["dispatch_policy"], "blocked")

    def test_malformed_catalogue_fails_closed(self) -> None:
        cases = []
        unknown_field = copy.deepcopy(raw_catalog())
        unknown_field["routes"][0]["extra"] = True
        cases.append(unknown_field)

        false_proof = copy.deepcopy(raw_catalog())
        false_proof["routes"][0]["availability"] = "proven"
        cases.append(false_proof)

        unblocked_dynamic = copy.deepcopy(raw_catalog())
        placeholder = next(
            route for route in unblocked_dynamic["routes"] if route["id"] == "apps-placeholder"
        )
        placeholder["dispatch_policy"] = "explicit"
        cases.append(unblocked_dynamic)

        wrong_scheme = copy.deepcopy(raw_catalog())
        wrong_scheme["routes"][0]["url"] = "https://example.com/settings"
        cases.append(wrong_scheme)

        for malformed in cases:
            with write_temporary_json(malformed) as temporary:
                with self.assertRaises(ValueError):
                    commands._load_catalog(Path(temporary.name))

    def test_manifest_and_text_surface_remain_coredevice_only(self) -> None:
        manifest = json.loads((DIRECTORY / "integration.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(manifest["actions"], {})
        self.assertEqual(manifest["scenarios"], {})
        self.assertEqual(manifest["capabilities"], ["exact-settings-url-navigation"])
        self.assertEqual(manifest["retry"]["max_attempts"], 1)
        self.assertEqual(manifest["retry"]["idempotent_actions"], [])
        self.assertEqual(manifest["compatibility"]["minimum_os"], "26.6.1")
        self.assertEqual(manifest["compatibility"]["maximum_os"], "26.6.1")
        self.assertEqual(manifest["compatibility"]["verification"], "unverified")
        self.assertIn("product iPad17,1", manifest["privacy"]["notes"])
        self.assertIn("hardware J817AP", manifest["privacy"]["notes"])
        self.assertIn("OS build 23G83", manifest["privacy"]["notes"])
        forbidden = ("w" + "da", "app" + "ium", "xcui" + "test")
        # Observer provenance may appear in maintenance evidence, but never in
        # production commands, manifests, or the operator-facing skill.
        for path in (
            DIRECTORY / "integration.json",
            DIRECTORY / "SKILL.md",
        ):
            text = path.read_text(encoding="utf-8").casefold()
            for token in forbidden:
                self.assertNotIn(token, text, path)

    def test_progressive_docs_match_availability_and_scoped_evidence(self) -> None:
        routes = raw_catalog()["routes"]
        catalogue_dir = DIRECTORY / "catalogue"
        index = (catalogue_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn("read only that section", index.casefold())
        self.assertIn("Candidates are development-only", index)
        self.assertIn("product `iPad17,1`, hardware `J817AP`, OS build `23G83`", index)
        self.assertIn("11 proven", index)
        self.assertIn("209 candidate", index)
        self.assertIn("10 incompatible", index)
        self.assertIn("21 template", index)

        documented: set[str] = set()
        for route_file in catalogue_dir.glob("*/ROUTES.md"):
            text = route_file.read_text(encoding="utf-8")
            self.assertNotIn("settings-navigation://", text)
            self.assertIn("controlled development testing only", text)
            self.assertIn("iPad17,1", text)
            self.assertIn("J817AP", text)
            self.assertIn("23G83", text)
            for route in routes:
                marker = f"| `{route['id']}` |"
                if marker in text:
                    self.assertNotIn(route["id"], documented)
                    documented.add(route["id"])
                    self.assertIn(f"| **{route['availability']}** |", text)
                    for evidence in route["evidence"]:
                        self.assertIn(evidence["kind"], text)
        self.assertEqual(documented, {route["id"] for route in routes})

        skill = (DIRECTORY / "SKILL.md").read_text(encoding="utf-8")
        for route_id in EXPECTED_PROVEN:
            self.assertIn(route_id, skill)
        for route_id in EXPECTED_INCOMPATIBLE:
            self.assertNotIn(f"`{route_id}`", skill)
        self.assertIn("catalogue/README.md", skill)
        self.assertIn("development-only candidates", skill)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        raw = b'{"schema":"x","schema":"y"}'
        with tempfile.NamedTemporaryFile() as temporary:
            temporary.write(raw)
            temporary.flush()
            with self.assertRaisesRegex(ValueError, "duplicate catalogue key"):
                commands._load_catalog(Path(temporary.name))

    def test_import_is_inert_and_does_not_load_device_transport(self) -> None:
        script = (
            "import sys; import integrations.settings.commands; "
            "assert 'ipad_agent.transports.coredevice' not in sys.modules"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=DIRECTORY.parents[1],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
