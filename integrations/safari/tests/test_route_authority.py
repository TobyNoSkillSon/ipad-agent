from __future__ import annotations

import copy
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from ipad_agent.core.registry import load_registry
from ipad_agent.lab import plan_scenario, run_fake_scenario, validate_manifest
from integrations.safari import commands


DIRECTORY = Path(commands.__file__).parent
PROFILE_PATH = DIRECTORY / "device-profiles/ipad17-1-j817ap-safari-26.6.1-ipados-26.6.1-23g83.json"
COMPATIBILITY_PATH = DIRECTORY / "route-compatibility.json"
MANIFEST_PATH = DIRECTORY / "integration.json"
POLICY_PATH = DIRECTORY / "url-policy.json"
EXPECTED_SCOPE = {
    "product_type": "iPad17,1",
    "hardware_model": "J817AP",
    "os_build": "23G83",
}


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def temporary_json(value: dict[str, object]) -> tempfile.NamedTemporaryFile:
    temporary = tempfile.NamedTemporaryFile(mode="w+", suffix=".json", encoding="utf-8")
    json.dump(value, temporary, ensure_ascii=False)
    temporary.flush()
    return temporary


def observer_pass() -> dict[str, object]:
    return {
        "kind": "observer-screenshot-pass",
        "actor": "agent",
        "method": "authorized-coredevice-observer-screenshot",
        "result": "expected-website-visible",
        "proof_scope": dict(EXPECTED_SCOPE),
    }


def visual_fail() -> dict[str, object]:
    return {
        "kind": "user-visual-fail",
        "actor": "user",
        "result": "expected-route-not-visible",
        "proof_scope": dict(EXPECTED_SCOPE),
    }


class SafariRouteAuthorityTests(unittest.TestCase):
    def test_exact_profile_is_strict_non_unique_and_versioned(self) -> None:
        profile = read_json(PROFILE_PATH)
        self.assertEqual(profile["scope_type"], "model-build")
        self.assertEqual(profile["app_name"], "Safari")
        self.assertEqual(profile["app_version"], "26.6.1")
        self.assertEqual(profile["product_type"], "iPad17,1")
        self.assertEqual(profile["hardware_model"], "J817AP")
        self.assertEqual(profile["os_version"], "26.6.1")
        self.assertEqual(profile["os_build"], "23G83")
        self.assertEqual(
            [source["kind"] for source in profile["sources"]],
            ["devicectl", "installed-application-metadata"],
        )
        forbidden = {
            "udid", "serial", "serial_number", "ecid", "unique_device_id",
            "device_id", "identifier",
        }
        self.assertTrue(forbidden.isdisjoint(profile))
        commands._load_device_profile()

        for field, value in (("serial", "forbidden"), ("os_build", "OTHER")):
            malformed = copy.deepcopy(profile)
            malformed[field] = value
            with self.subTest(field=field), temporary_json(malformed) as temporary:
                with self.assertRaises(ValueError):
                    commands._load_device_profile(Path(temporary.name))

    def test_authority_truthfully_separates_route_status_and_admission(self) -> None:
        authority = read_json(COMPATIBILITY_PATH)
        routes = authority["routes"]
        self.assertEqual([route["command"] for route in routes], ["website", "youtube"])
        self.assertEqual(
            Counter(route["availability"] for route in routes),
            {"proven": 1, "candidate": 1},
        )
        self.assertEqual(routes[0]["production"], "admitted")
        self.assertEqual(routes[1]["production"], "legacy-admitted")
        self.assertEqual(routes[0]["evidence"][1], observer_pass())
        self.assertEqual(
            [item["kind"] for item in routes[1]["evidence"]],
            ["official-documentation"],
        )
        self.assertEqual(set(commands._load_compatibility()), {"website", "youtube"})

    def test_observer_evidence_is_exact_metadata_only_and_profile_bound(self) -> None:
        observer = read_json(COMPATIBILITY_PATH)["routes"][0]["evidence"][1]
        self.assertEqual(
            set(observer), {"kind", "actor", "method", "result", "proof_scope"}
        )
        forbidden = {
            "screenshot", "path", "hash", "url", "query", "fragment", "destination",
            "tab", "device_id", "udid", "identifier", "evidence_file",
        }
        self.assertTrue(forbidden.isdisjoint(observer))

        malformed = read_json(COMPATIBILITY_PATH)
        malformed["routes"][0]["evidence"][1]["url"] = "private"
        with temporary_json(malformed) as temporary:
            with self.assertRaisesRegex(ValueError, "observer-screenshot-pass"):
                commands._load_compatibility(Path(temporary.name))

        malformed = read_json(COMPATIBILITY_PATH)
        malformed["routes"][0]["evidence"][1]["proof_scope"]["os_build"] = "OTHER"
        with temporary_json(malformed) as temporary:
            with self.assertRaisesRegex(ValueError, "exact product/hardware/build"):
                commands._load_compatibility(Path(temporary.name))

    def test_availability_is_derived_and_conflicting_evidence_fails_closed(self) -> None:
        candidate = read_json(COMPATIBILITY_PATH)
        candidate["routes"][0]["availability"] = "candidate"
        candidate["routes"][0]["evidence"] = candidate["routes"][0]["evidence"][:1]
        with temporary_json(candidate) as temporary:
            loaded = commands._load_compatibility(Path(temporary.name))
            self.assertEqual(loaded["website"]["availability"], "candidate")

        incompatible = read_json(COMPATIBILITY_PATH)
        incompatible["routes"][1]["availability"] = "incompatible"
        incompatible["routes"][1]["evidence"].append(visual_fail())
        with temporary_json(incompatible) as temporary:
            loaded = commands._load_compatibility(Path(temporary.name))
            self.assertEqual(loaded["youtube"]["availability"], "incompatible")

        conflict = read_json(COMPATIBILITY_PATH)
        conflict["routes"][0]["evidence"].append(visual_fail())
        with temporary_json(conflict) as temporary:
            with self.assertRaisesRegex(ValueError, "conflicting"):
                commands._load_compatibility(Path(temporary.name))

        unsupported = read_json(COMPATIBILITY_PATH)
        unsupported["routes"][1]["evidence"].append(
            {"kind": "coredevice-acceptance", "proof_scope": dict(EXPECTED_SCOPE)}
        )
        with temporary_json(unsupported) as temporary:
            with self.assertRaisesRegex(ValueError, "evidence kind"):
                commands._load_compatibility(Path(temporary.name))

    def test_authority_rejects_unknown_duplicate_reordered_and_status_drift(self) -> None:
        cases = []
        extra = read_json(COMPATIBILITY_PATH)
        extra["extra"] = True
        cases.append(extra)
        duplicate = read_json(COMPATIBILITY_PATH)
        duplicate["routes"][1]["command"] = "website"
        cases.append(duplicate)
        reordered = read_json(COMPATIBILITY_PATH)
        reordered["routes"].reverse()
        cases.append(reordered)
        drift = read_json(COMPATIBILITY_PATH)
        drift["routes"][1]["production"] = "admitted"
        cases.append(drift)
        false_proof = read_json(COMPATIBILITY_PATH)
        false_proof["routes"][1]["availability"] = "proven"
        cases.append(false_proof)
        for index, malformed in enumerate(cases):
            with self.subTest(case=index), temporary_json(malformed) as temporary:
                with self.assertRaises(ValueError):
                    commands._load_compatibility(Path(temporary.name))

        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", encoding="utf-8") as temporary:
            temporary.write(
                '{"schema":"ipad-agent.safari-route-compatibility/v1",'
                '"schema":"ipad-agent.safari-route-compatibility/v1"}'
            )
            temporary.flush()
            with self.assertRaisesRegex(ValueError, "duplicate Safari authority key"):
                commands._load_compatibility(Path(temporary.name))

    def test_manifest_is_clean_direct_coredevice_authority(self) -> None:
        manifest = validate_manifest(MANIFEST_PATH)
        self.assertEqual(manifest["bundle_ids"], ["com.apple.mobilesafari"])
        self.assertEqual(set(manifest["capabilities"]), {"launch", "open-url"})
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(set(manifest["actions"]), {"activate", "open-url"})
        self.assertEqual(set(manifest["scenarios"]), {"activate-direct", "open-url-direct"})
        self.assertEqual(
            [step["operation"] for step in manifest["actions"]["activate"]["steps"]],
            ["activate"],
        )
        self.assertEqual(
            [step["operation"] for step in manifest["actions"]["open-url"]["steps"]],
            ["open-url"],
        )
        self.assertEqual(manifest["scenarios"]["open-url-direct"]["actions"], ["open-url"])
        self.assertEqual(manifest["retry"]["max_attempts"], 1)
        self.assertEqual(manifest["retry"]["idempotent_actions"], ["activate"])
        self.assertEqual(manifest["compatibility"]["minimum_os"], "26.6.1")
        self.assertEqual(manifest["compatibility"]["maximum_os"], "26.6.1")
        self.assertEqual(manifest["compatibility"]["verification"], "unverified")
        self.assertEqual(manifest["compatibility"]["app_versions"], [])

        activate = plan_scenario(MANIFEST_PATH, "activate-direct")
        direct = plan_scenario(
            MANIFEST_PATH, "open-url-direct", parameters={"url": "https://example.com"}
        )
        self.assertEqual([step.instruction["operation"] for step in activate.steps], ["activate"])
        self.assertEqual([step.instruction["operation"] for step in direct.steps], ["open-url"])
        self.assertTrue(run_fake_scenario(direct, record=False).ok)

    def test_v1_policy_is_exact_and_rejects_excluded_or_malformed_payloads(self) -> None:
        policy = read_json(POLICY_PATH)
        self.assertEqual(policy["actions"], {"open-url": ["http", "https"]})
        registry = load_registry()
        integration = registry.resolve("safari")
        self.assertEqual(integration.bundle_id, "com.apple.mobilesafari")
        self.assertEqual(integration.url_policy.max_url_bytes, 2048)
        accepted = "https://example.com:8443/path?q=1#part"
        self.assertEqual(registry.validate_v1_url("safari", "open-url", accepted), accepted)
        bad = (
            "ftp://example.com/file",
            "x-web-search://example.com",
            "x-safari-https://example.com",
            "webclip://example.com",
            "https://user:secret@example.com",
            "https://example.com/%zz",
            r"https://example.com\path",
            "https://example.com:" + "9" * 20,
            "https://example.com/" + "x" * 2050,
        )
        for url in bad:
            with self.subTest(url=url[:40]), self.assertRaises(ValueError):
                registry.validate_v1_url("safari", "open-url", url)

    def test_website_and_candidate_youtube_each_dispatch_exactly_once(self) -> None:
        authority = commands._load_compatibility()
        cases = (
            ("website", ("https://example.com/path?q=1#part",), {}, "https://example.com/path?q=1#part"),
            ("youtube", ("https://youtu.be/video?x=1",), {"at": 90.9}, None),
        )
        sentinel = object()
        for command, args, options, expected in cases:
            with self.subTest(command=command), mock.patch.object(
                commands, "_load_compatibility", return_value=authority
            ) as compatibility, mock.patch.object(
                commands.shared, "_browser_policy_url", side_effect=lambda _target, url: url
            ) as policy, mock.patch.object(
                commands.shared, "_direct_open", return_value=sentinel
            ) as dispatch:
                result = commands.safari(command, *args, **options)
                self.assertIs(result, sentinel)
                compatibility.assert_called_once_with()
                policy.assert_called_once()
                dispatch.assert_called_once()
                self.assertEqual(dispatch.call_args.args[0], "Safari")
                delivered = dispatch.call_args.args[1]
                if expected is not None:
                    self.assertEqual(delivered, expected)
                else:
                    self.assertEqual(parse_qs(urlparse(delivered).query)["t"], ["90s"])
                    self.assertEqual(parse_qs(urlparse(delivered).query)["x"], ["1"])

    def test_validation_and_authority_fail_before_policy_or_dispatch(self) -> None:
        invalid_calls = (
            ("website", ("ftp://example.com",), {}),
            ("website", (), {}),
            ("youtube", ("https://example.com/video",), {}),
            ("youtube", ("https://youtu.be/id",), {"at": -1}),
            ("youtube", ("https://youtu.be/id",), {"other": 1}),
            ("open", (), {}),
        )
        for command, args, options in invalid_calls:
            with self.subTest(command=command, args=args, options=options), mock.patch.object(
                commands.shared, "_browser_policy_url"
            ) as policy, mock.patch.object(commands.shared, "_direct_open") as dispatch:
                result = commands.safari(command, *args, **options)
                self.assertFalse(result["ok"])
                policy.assert_not_called()
                dispatch.assert_not_called()

        with mock.patch.object(
            commands, "_load_compatibility", side_effect=ValueError("invalid authority")
        ), mock.patch.object(commands.shared, "_browser_policy_url") as policy, mock.patch.object(
            commands.shared, "_direct_open"
        ) as dispatch:
            result = commands.safari("website", "https://example.com")
        self.assertFalse(result["ok"])
        policy.assert_not_called()
        dispatch.assert_not_called()

        authority = commands._load_compatibility()
        with mock.patch.object(
            commands, "_load_compatibility", return_value=authority
        ), mock.patch.object(
            commands.shared, "_browser_policy_url", side_effect=ValueError("policy rejected")
        ) as policy, mock.patch.object(commands.shared, "_direct_open") as dispatch:
            result = commands.safari("website", "https://example.com")
        self.assertFalse(result["ok"])
        policy.assert_called_once()
        dispatch.assert_not_called()

        incompatible = copy.deepcopy(authority)
        incompatible["youtube"]["availability"] = "incompatible"
        with mock.patch.object(
            commands, "_load_compatibility", return_value=incompatible
        ), mock.patch.object(commands.shared, "_browser_policy_url") as policy, mock.patch.object(
            commands.shared, "_direct_open"
        ) as dispatch:
            result = commands.safari("youtube", "https://youtu.be/video-id")
        self.assertFalse(result["ok"])
        policy.assert_not_called()
        dispatch.assert_not_called()

    def test_docs_cover_payloads_status_exclusions_and_tab_caveats_without_residue(self) -> None:
        skill = (DIRECTORY / "SKILL.md").read_text(encoding="utf-8")
        workflows = (DIRECTORY / "WORKFLOWS.md").read_text(encoding="utf-8")
        combined = (skill + workflows).casefold()
        for phrase in (
            "`website`", "`youtube`", "2,048 utf-8 bytes", "music.youtube.com",
            "x-web-search", "x-safari-https", "ftp", "webclip", "private-tab",
            "extension routes", "candidate", "legacy-admitted", "backward compatibility",
            "coredevice accepted", "does not prove", "no cleanup claim",
        ):
            self.assertIn(phrase, combined)
        for stale in (
            "display-now-page", "recover-now-page", "inspect-toolbar",
            "durable now", "historical residue", "two historical pilot",
            "display-server", "display server", "appium", "webdriveragent", "wda",
        ):
            self.assertNotIn(stale, combined)
        source = (DIRECTORY / "commands.py").read_text(encoding="utf-8").casefold()
        manifest = MANIFEST_PATH.read_text(encoding="utf-8").casefold()
        for stale in (
            "display-now-page", "recover-now-page", "inspect-toolbar", "durable now",
            "appium", "webdriveragent", "wda",
        ):
            self.assertNotIn(stale, source + manifest)

    def test_import_is_inert_and_does_not_load_device_transport(self) -> None:
        script = (
            "import sys; import integrations.safari.commands; "
            "assert 'ipad_agent.transports.coredevice' not in sys.modules"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=DIRECTORY.parents[1],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
