from __future__ import annotations

import ast
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from ipad_agent.core.registry import load_registry
from ipad_agent.lab import PhysicalAuthorization, ScenarioPlan, run_fake_scenario
from integrations.apple_maps import commands


DIRECTORY = Path(commands.__file__).parent
PROFILE_PATH = DIRECTORY / "device-profiles/ipad-pro-11-inch-m5-wifi-ipados-26.6.1-23g83.json"
COMPATIBILITY_PATH = DIRECTORY / "route-compatibility.json"
POLICY_PATH = DIRECTORY / "url-policy.json"
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
EXPECTED_ROUTES = (
    "frame",
    "search",
    "place",
    "look-around",
    "directions",
    "navigate",
    "guides",
    "report-a-problem",
    "link",
)
EXPECTED_SCOPE = {
    "product_type": "iPad17,1",
    "hardware_model": "J817AP",
    "os_build": "23G83",
}
EXPECTED_POLICY_DIGEST = "568bf0daeed10f4ee55bb397f7c9256a38eb35556e808922ff34abbc4fe4accb"


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def temporary_json(value: dict[str, object]) -> tempfile.NamedTemporaryFile:
    temporary = tempfile.NamedTemporaryFile(mode="w+", suffix=".json", encoding="utf-8")
    json.dump(value, temporary, ensure_ascii=False)
    temporary.flush()
    return temporary


def visual_pass() -> dict[str, object]:
    return {
        "kind": "user-visual-pass",
        "actor": "user",
        "result": "expected-route-visible",
        "proof_scope": dict(EXPECTED_SCOPE),
    }


def observer_pass() -> dict[str, object]:
    return {
        "kind": "observer-screenshot-pass",
        "actor": "agent",
        "method": "project-owned-wda-screenshot",
        "result": "expected-route-visible",
        "proof_scope": dict(EXPECTED_SCOPE),
    }


def visual_fail() -> dict[str, object]:
    return {
        "kind": "user-visual-fail",
        "actor": "user",
        "result": "expected-route-not-visible",
        "observed": "Maps stayed on the prior view",
        "proof_scope": dict(EXPECTED_SCOPE),
    }


def all_candidate_authority() -> dict[str, dict[str, str]]:
    """Synthetic availability used only to exercise every candidate build branch."""
    return {command: {"availability": "candidate"} for command in EXPECTED_ROUTES}


class AppleMapsAuthorityTests(unittest.TestCase):
    def test_non_unique_profile_is_exact_and_strict(self) -> None:
        profile = read_json(PROFILE_PATH)
        self.assertEqual(profile["scope_type"], "model-build")
        self.assertEqual(profile["marketing_model"], "iPad Pro 11-inch (M5, Wi-Fi)")
        self.assertEqual(profile["product_type"], "iPad17,1")
        self.assertEqual(profile["hardware_model"], "J817AP")
        self.assertEqual(profile["os_version"], "26.6.1")
        self.assertEqual(profile["os_build"], "23G83")
        self.assertEqual(
            profile["capabilities"],
            {"form_factor": "ipad", "wifi": True, "cellular": False},
        )
        self.assertEqual(
            [source["kind"] for source in profile["sources"]],
            ["devicectl", "apple-technical-specification"],
        )
        forbidden = {"udid", "serial", "serial_number", "ecid", "unique_device_id"}
        self.assertTrue(forbidden.isdisjoint(profile))
        commands._load_device_profile()

        malformed = copy.deepcopy(profile)
        malformed["serial"] = "not-allowed"
        with temporary_json(malformed) as temporary:
            with self.assertRaisesRegex(ValueError, "unknown or missing"):
                commands._load_device_profile(Path(temporary.name))

    def test_route_authority_has_exact_commands_counts_and_redacted_evidence(self) -> None:
        authority = read_json(COMPATIBILITY_PATH)
        routes = authority["routes"]
        self.assertEqual([route["command"] for route in routes], list(EXPECTED_ROUTES))
        self.assertEqual(
            Counter(route["availability"] for route in routes),
            {"proven": 7, "candidate": 2},
        )
        self.assertEqual(
            Counter(item["kind"] for route in routes for item in route["evidence"]),
            {
                "official-documentation": 9,
                "observer-screenshot-pass": 7,
                "user-visual-pass": 1,
            },
        )
        self.assertEqual(
            {route["command"] for route in routes if route["availability"] == "proven"},
            {"frame", "search", "place", "look-around", "directions", "guides", "link"},
        )
        self.assertEqual(
            {route["command"] for route in routes if route["availability"] == "candidate"},
            {"navigate", "report-a-problem"},
        )
        frame = routes[0]
        self.assertEqual(frame["evidence"][1], visual_pass())
        observers = [
            item
            for route in routes
            for item in route["evidence"]
            if item["kind"] == "observer-screenshot-pass"
        ]
        self.assertEqual(observers, [observer_pass()] * 7)
        for evidence in observers:
            self.assertEqual(
                set(evidence), {"kind", "actor", "method", "result", "proof_scope"}
            )
            self.assertTrue(
                {
                    "screenshot",
                    "hash",
                    "url",
                    "address",
                    "location",
                    "locator",
                    "query",
                    "route",
                    "route_details",
                }.isdisjoint(evidence)
            )
        loaded = commands._load_compatibility()
        self.assertEqual(set(loaded), set(EXPECTED_ROUTES))
        self.assertNotIn("open", loaded)
        self.assertNotIn("show", loaded)

    def test_candidate_proven_and_incompatible_are_derived_from_evidence(self) -> None:
        base = read_json(COMPATIBILITY_PATH)

        proven = copy.deepcopy(base)
        proven["routes"][5]["availability"] = "proven"
        proven["routes"][5]["evidence"].append(observer_pass())
        with temporary_json(proven) as temporary:
            loaded = commands._load_compatibility(Path(temporary.name))
            self.assertEqual(loaded["navigate"]["availability"], "proven")

        failed = copy.deepcopy(base)
        failed["routes"][7]["availability"] = "incompatible"
        failed["routes"][7]["evidence"].append(visual_fail())
        with temporary_json(failed) as temporary:
            loaded = commands._load_compatibility(Path(temporary.name))
            self.assertEqual(loaded["report-a-problem"]["availability"], "incompatible")

        mismatched = copy.deepcopy(base)
        mismatched["routes"][5]["availability"] = "incompatible"
        mismatched["routes"][5]["evidence"].append(
            {
                "kind": "profile-capability-mismatch",
                "capability": "cellular",
                "required": True,
                "observed": False,
                "proof_scope": dict(EXPECTED_SCOPE),
            }
        )
        with temporary_json(mismatched) as temporary:
            loaded = commands._load_compatibility(Path(temporary.name))
            self.assertEqual(loaded["navigate"]["availability"], "incompatible")

    def test_observer_screenshot_pass_schema_is_exact_and_profile_bound(self) -> None:
        authority = read_json(COMPATIBILITY_PATH)
        authority["routes"][5]["availability"] = "proven"
        authority["routes"][5]["evidence"].append(observer_pass())
        with temporary_json(authority) as temporary:
            self.assertEqual(
                commands._load_compatibility(Path(temporary.name))["navigate"]["availability"],
                "proven",
            )

        malformed_evidence = []
        extra = observer_pass()
        extra["screenshot"] = "private.png"
        malformed_evidence.append(extra)
        for field, value in (
            ("actor", "user"),
            ("method", "other-screenshot"),
            ("result", "dispatch-accepted"),
        ):
            evidence = observer_pass()
            evidence[field] = value
            malformed_evidence.append(evidence)
        missing = observer_pass()
        del missing["method"]
        malformed_evidence.append(missing)
        wrong_scope = observer_pass()
        wrong_scope["proof_scope"]["os_build"] = "OTHER"
        malformed_evidence.append(wrong_scope)

        for evidence in malformed_evidence:
            malformed = read_json(COMPATIBILITY_PATH)
            malformed["routes"][5]["availability"] = "proven"
            malformed["routes"][5]["evidence"].append(evidence)
            with self.subTest(evidence=evidence), temporary_json(malformed) as temporary:
                with self.assertRaises(ValueError):
                    commands._load_compatibility(Path(temporary.name))

    def test_proven_requires_exact_product_hardware_and_build_positive(self) -> None:
        authority = read_json(COMPATIBILITY_PATH)
        authority["routes"][5]["availability"] = "proven"
        evidence = observer_pass()
        evidence["proof_scope"]["hardware_model"] = "OTHER"
        authority["routes"][5]["evidence"].append(evidence)
        with temporary_json(authority) as temporary:
            with self.assertRaisesRegex(ValueError, "exact product/hardware/build"):
                commands._load_compatibility(Path(temporary.name))

        authority = read_json(COMPATIBILITY_PATH)
        authority["routes"][5]["availability"] = "proven"
        with temporary_json(authority) as temporary:
            with self.assertRaisesRegex(ValueError, "conflicts with its evidence"):
                commands._load_compatibility(Path(temporary.name))

    def test_transport_acceptance_is_not_public_evidence_or_a_schema_kind(self) -> None:
        authority = read_json(COMPATIBILITY_PATH)
        kinds = {
            item["kind"] for route in authority["routes"] for item in route["evidence"]
        }
        self.assertFalse(any("acceptance" in kind or "dispatch" in kind for kind in kinds))
        authority["routes"][1]["evidence"].append(
            {"kind": "coredevice-acceptance", "proof_scope": dict(EXPECTED_SCOPE)}
        )
        with temporary_json(authority) as temporary:
            with self.assertRaisesRegex(ValueError, "evidence kind"):
                commands._load_compatibility(Path(temporary.name))

    def test_authority_rejects_unknown_fields_duplicates_and_nondeterministic_order(self) -> None:
        cases = []
        unknown = read_json(COMPATIBILITY_PATH)
        unknown["extra"] = True
        cases.append(unknown)

        duplicate = read_json(COMPATIBILITY_PATH)
        duplicate["routes"][1]["command"] = "frame"
        cases.append(duplicate)

        reordered = read_json(COMPATIBILITY_PATH)
        reordered["routes"][0]["evidence"][1:] = reversed(
            reordered["routes"][0]["evidence"][1:]
        )
        cases.append(reordered)

        for index, malformed in enumerate(cases):
            with self.subTest(case=index), temporary_json(malformed) as temporary:
                with self.assertRaises(ValueError):
                    commands._load_compatibility(Path(temporary.name))

    def test_positive_and_negative_evidence_conflict(self) -> None:
        for command_index in (0, 1):
            conflicting = read_json(COMPATIBILITY_PATH)
            conflicting["routes"][command_index]["evidence"].append(visual_fail())
            with self.subTest(command=conflicting["routes"][command_index]["command"]), temporary_json(
                conflicting
            ) as temporary:
                with self.assertRaisesRegex(ValueError, "conflicting compatibility evidence"):
                    commands._load_compatibility(Path(temporary.name))

    def test_policy_exact_bundle_bound_and_digest_are_pinned(self) -> None:
        raw = read_json(POLICY_PATH)
        digest = hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
        integration = load_registry().resolve("maps")
        policy = integration.url_policy
        self.assertIsNotNone(policy)
        self.assertEqual(digest, EXPECTED_POLICY_DIGEST)
        self.assertEqual(policy.sha256, EXPECTED_POLICY_DIGEST)
        self.assertEqual(integration.policy_sha256, EXPECTED_POLICY_DIGEST)
        self.assertEqual(raw["target_bundle"], "com.apple.Maps")
        self.assertEqual(policy.target_bundle, "com.apple.Maps")
        self.assertEqual(raw["max_url_bytes"], 2048)
        self.assertEqual(tuple(raw["commands"]), ("open",) + EXPECTED_ROUTES[:-1] + ("link",))
        self.assertEqual(raw["commands"]["search"]["aliases"], ["show"])
        self.assertEqual(dict(policy.aliases), {"show": "search"})

    def test_manifest_is_coredevice_only_and_policy_bound(self) -> None:
        manifest = read_json(DIRECTORY / "integration.json")
        expected_actions = {
            "activate",
            "open-frame",
            "open-search",
            "open-place",
            "open-look-around",
            "open-directions",
            "start-navigation",
            "open-guides",
            "open-report-problem",
            "open-link",
        }
        expected_capabilities = {
            "launch",
            "direct-frame",
            "direct-search",
            "direct-place",
            "direct-look-around",
            "direct-directions",
            "explicit-navigation",
            "direct-guides",
            "report-problem-sheet",
            "exact-maps-link",
        }
        self.assertEqual(manifest["bundle_ids"], ["com.apple.Maps"])
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(
            set(manifest["scenarios"]),
            {"navigate-candidate", "report-problem-candidate"},
        )
        self.assertEqual(
            manifest["safety"]["requires_confirmation"],
            ["the exact candidate route, parameters, and transient effect were reviewed"],
        )
        for scenario in manifest["scenarios"].values():
            self.assertEqual(scenario["safety"], "transient")
            self.assertEqual(scenario["retry"], "inspect_then_decide")
            self.assertEqual(len(scenario["actions"]), 1)
        self.assertEqual(set(manifest["actions"]), expected_actions)
        self.assertEqual(set(manifest["capabilities"]), expected_capabilities)
        for action_id, action in manifest["actions"].items():
            self.assertEqual(len(action["steps"]), 1)
            operation = action["steps"][0]["operation"]
            self.assertEqual(operation, "activate" if action_id == "activate" else "open-url")
        self.assertEqual(manifest["retry"]["max_attempts"], 1)
        self.assertEqual(manifest["retry"]["idempotent_actions"], ["activate"])
        self.assertEqual(manifest["compatibility"]["minimum_os"], "26.6.1")
        self.assertEqual(manifest["compatibility"]["maximum_os"], "26.6.1")
        self.assertEqual(manifest["compatibility"]["verification"], "unverified")

    def test_route_dispatch_uses_only_the_registry_validated_boundary(self) -> None:
        source = (DIRECTORY / "commands.py").read_text(encoding="utf-8")
        self.assertFalse(hasattr(commands, "_load_policy"))
        self.assertFalse(hasattr(commands, "_policy_actions"))
        self.assertEqual(source.count("shared._direct_open("), 1)
        self.assertIn('registry.resolve_url_route("maps", command, route_args, route_options)', source)
        self.assertIn("route, config=config, registry=registry, terminate=True", source)

    def test_public_open_is_plain_activation_without_rendering_claim(self) -> None:
        sentinel = object()
        with mock.patch.object(commands.shared, "_direct_open", return_value=sentinel) as direct:
            self.assertIs(commands.maps("open"), sentinel)
        direct.assert_called_once_with("com.apple.Maps")

        for args, options in ((('extra',), {}), ((), {"page": "search"})):
            with mock.patch.object(commands.shared, "_direct_open") as direct:
                result = commands.maps("open", *args, **options)
                self.assertFalse(result["ok"])
                direct.assert_not_called()

    def test_current_proven_families_pass_the_public_dispatch_gate_once(self) -> None:
        calls = {
            "frame": ((), {"center": (1, 2)}, "frame"),
            "search": (("Warsaw",), {}, "search"),
            "show": (("Warsaw",), {}, "search"),
            "place": ((), {"address": "Paris"}, "place"),
            "look-around": ((), {"address": "Paris"}, "look-around"),
            "directions": (("Gdańsk",), {}, "directions"),
            "guides": ((), {}, "guides"),
            "link": (("https://maps.apple.com/guides",), {}, "link"),
        }
        config = SimpleNamespace(enabled_addons=())
        sentinel = object()
        for command, (args, options, canonical) in calls.items():
            registry = mock.Mock(wraps=load_registry())
            with self.subTest(command=command), mock.patch(
                "ipad_agent.core.config.load_config", return_value=config
            ) as load_config, mock.patch(
                "ipad_agent.core.registry.load_registry", return_value=registry
            ) as load_snapshot, mock.patch.object(
                commands.shared, "_validated_route_open", return_value=sentinel
            ) as dispatch:
                self.assertIs(commands.maps(command, *args, **options), sentinel)
                load_config.assert_called_once_with()
                load_snapshot.assert_called_once_with(enabled_addons=())
                route = dispatch.call_args.args[0]
                self.assertEqual(route.command, canonical)
                self.assertEqual(route.policy_sha256, EXPECTED_POLICY_DIGEST)
                dispatch.assert_called_once_with(
                    route, config=config, registry=registry, terminate=True,
                )

        with mock.patch("ipad_agent.core.config.load_config") as load_config, mock.patch(
            "ipad_agent.core.registry.load_registry"
        ) as load_snapshot, mock.patch.object(
            commands.shared, "_validated_route_open"
        ) as probe_dispatch:
            result = commands._plan_candidate("frame", center=(1, 2))
        self.assertFalse(result["ok"])
        load_config.assert_not_called()
        load_snapshot.assert_not_called()
        probe_dispatch.assert_not_called()

    def test_production_denies_both_candidates_before_registry_or_dispatch(self) -> None:
        calls = {
            "navigate": (("Gdańsk",), {"start": 0}),
            "report-a-problem": ((), {"address": "Paris"}),
        }
        for command, (args, options) in calls.items():
            with self.subTest(command=command), mock.patch(
                "ipad_agent.core.config.load_config"
            ) as config, mock.patch(
                "ipad_agent.core.registry.load_registry"
            ) as registry, mock.patch.object(
                commands.shared, "_validated_route_open"
            ) as dispatch:
                result = commands.maps(command, *args, **options)
                self.assertFalse(result["ok"])
                self.assertIn("candidate", result["error"])
                config.assert_not_called()
                registry.assert_not_called()
                dispatch.assert_not_called()

    def test_production_dispatches_only_a_proven_registry_route_once(self) -> None:
        authority = {name: {"availability": "candidate"} for name in EXPECTED_ROUTES}
        authority["search"] = {"availability": "proven"}
        base_registry = load_registry()
        config = SimpleNamespace(enabled_addons=())
        sentinel = object()
        for command in ("search", "show"):
            registry = mock.Mock(wraps=base_registry)
            with self.subTest(command=command), mock.patch.object(
                commands, "_load_compatibility", return_value=authority
            ), mock.patch(
                "ipad_agent.core.config.load_config", return_value=config
            ) as load_config, mock.patch(
                "ipad_agent.core.registry.load_registry", return_value=registry
            ) as load_snapshot, mock.patch.object(
                commands.shared, "_validated_route_open", return_value=sentinel
            ) as dispatch:
                self.assertIs(commands.maps(command, "Warsaw"), sentinel)
                load_config.assert_called_once_with()
                load_snapshot.assert_called_once_with(enabled_addons=())
                registry.resolve_url_route.assert_called_once_with(
                    "maps", "search", ("Warsaw",), {}
                )
                route = dispatch.call_args.args[0]
                self.assertEqual(route.url, "https://maps.apple.com/search?query=Warsaw")
                self.assertEqual(route.policy_sha256, EXPECTED_POLICY_DIGEST)
                dispatch.assert_called_once_with(
                    route, config=config, registry=registry, terminate=True,
                )

        authority["search"] = {"availability": "incompatible"}
        with mock.patch.object(
            commands, "_load_compatibility", return_value=authority
        ), mock.patch("ipad_agent.core.config.load_config") as load_config, mock.patch(
            "ipad_agent.core.registry.load_registry"
        ) as load_snapshot, mock.patch.object(
            commands.shared, "_validated_route_open"
        ) as dispatch:
            result = commands.maps("search", "Warsaw")
        self.assertFalse(result["ok"])
        self.assertIn("incompatible", result["error"])
        load_config.assert_not_called()
        load_snapshot.assert_not_called()
        dispatch.assert_not_called()

    def test_private_probe_returns_bound_candidate_plans_without_dispatch(self) -> None:
        cases = (
            (
                "navigate", ("Gdańsk",),
                {"origin": "Warsaw", "waypoints": ["Łódź"], "start": 0},
                "navigate-candidate", "navigate", "destination=Gda%C5%84sk",
            ),
            (
                "report-a-problem", (40.7, -74.0), {},
                "report-problem-candidate", "report-a-problem", "coordinate=40.7,-74",
            ),
        )
        for command, args, options, scenario, canonical, marker in cases:
            with self.subTest(command=command), mock.patch(
                "ipad_agent.core.config.load_config"
            ) as load_config, mock.patch(
                "ipad_agent.core.registry.load_registry"
            ) as load_registry_snapshot, mock.patch.object(
                commands.shared, "_validated_route_open"
            ) as dispatch, mock.patch.object(
                commands.shared, "_direct_open"
            ) as direct:
                plan = commands._plan_candidate(command, *args, **options)
            self.assertIsInstance(plan, ScenarioPlan)
            self.assertEqual(plan.scenario_id, scenario)
            self.assertEqual(plan.integration_id, "maps")
            self.assertEqual(plan.max_attempts, 1)
            self.assertEqual(len(plan.steps), 1)
            record = plan.steps[0].instruction["validated_route"]
            self.assertEqual(record["command"], canonical)
            self.assertEqual(record["policy_sha256"], EXPECTED_POLICY_DIGEST)
            self.assertIn(marker, record["url"])
            self.assertEqual(plan.steps[0].operation.retry_class.value, "inspect_then_decide")
            fake = run_fake_scenario(plan, record=False)
            self.assertTrue(fake.ok)
            self.assertEqual([1], [len(attempts) for attempts in fake.attempts])
            load_config.assert_not_called()
            load_registry_snapshot.assert_not_called()
            dispatch.assert_not_called()
            direct.assert_not_called()

    def test_candidate_plan_requires_exact_short_lived_authorization(self) -> None:
        plan = commands._plan_candidate("navigate", "Gdańsk", start=0)
        self.assertIsInstance(plan, ScenarioPlan)
        now = datetime.now(timezone.utc)
        confirmation = "the exact candidate route, parameters, and transient effect were reviewed"
        authorization = PhysicalAuthorization.for_plan(
            plan,
            actor="test reviewer",
            request="run this displayed navigation candidate once",
            authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
            confirmations=(confirmation,),
        )
        authorization.verify(plan, at=now + timedelta(seconds=1))

        changed = replace(plan, parameters={**plan.parameters, "start": 1})
        with self.assertRaisesRegex(PermissionError, "plan_digest|parameters"):
            authorization.verify(changed, at=now + timedelta(seconds=1))

        expired = PhysicalAuthorization.for_plan(
            plan,
            actor="test reviewer",
            request="expired candidate",
            authorized_at=(now - timedelta(minutes=10)).isoformat(),
            expires_at=(now - timedelta(minutes=5)).isoformat(),
            confirmations=(confirmation,),
        )
        with self.assertRaisesRegex(PermissionError, "expired"):
            expired.verify(plan, at=now)

    def test_stale_boolean_non_candidates_and_invalid_inputs_never_dispatch(self) -> None:
        cases = (
            ("navigate", ("Gdańsk",), {"start": 0, "allow_explicit": True}),
            ("navigate", ("Gdańsk",), {}),
            ("report-a-problem", (), {}),
            ("frame", (), {"center": (1, 2)}),
            ("open", (), {}),
            ("arbitrary", (), {}),
        )
        for command, args, options in cases:
            with self.subTest(command=command, options=options), mock.patch(
                "ipad_agent.core.config.load_config"
            ) as load_config, mock.patch(
                "ipad_agent.core.registry.load_registry"
            ) as registry, mock.patch.object(
                commands.shared, "_validated_route_open"
            ) as dispatch, mock.patch.object(
                commands.shared, "_direct_open"
            ) as direct:
                result = commands._plan_candidate(command, *args, **options)
            self.assertFalse(result["ok"])
            load_config.assert_not_called()
            registry.assert_not_called()
            dispatch.assert_not_called()
            direct.assert_not_called()

    def test_short_link_resolution_remains_separate_from_candidate_planning(self) -> None:
        short = "https://example.maps.apple/token"
        resolved = "https://maps.apple.com/search?query=C%2B%2B"
        resolver = mock.Mock(return_value=resolved)
        args, options = commands._maps_arguments(
            "link", (short,), {}, resolver=resolver,
        )
        self.assertEqual(args, (resolved,))
        self.assertEqual(options, {})
        resolver.assert_called_once_with(short)
        with self.assertRaisesRegex(ValueError, "maintenance resolver"):
            commands._maps_arguments("link", (short,), {})


    def test_docs_match_current_proven_and_candidate_families(self) -> None:
        authority = read_json(COMPATIBILITY_PATH)
        proven = {
            route["command"] for route in authority["routes"] if route["availability"] == "proven"
        }
        candidates = {
            route["command"]
            for route in authority["routes"]
            if route["availability"] == "candidate"
        }
        skill = (DIRECTORY / "SKILL.md").read_text(encoding="utf-8")
        workflows = (DIRECTORY / "WORKFLOWS.md").read_text(encoding="utf-8")
        for command in proven | candidates:
            self.assertIn(f"`{command}`", skill)
            self.assertIn(f"`{command}`", workflows)
        self.assertIn("`show` alias", skill)
        self.assertIn("ordinary proven route families", skill)
        self.assertIn("remain candidates", skill)
        self.assertIn("seven proven route families", workflows)
        self.assertIn("observer-screenshot-pass", workflows)
        self.assertIn("project-owned WDA screenshot", workflows)
        self.assertIn("private ephemeral `.runtime/` state", workflows)
        self.assertIn("CoreDevice acceptance", workflows)
        self.assertIn("candidate test matrix", workflows.casefold())
        self.assertIn("These sources establish syntax and semantics", workflows)

        source = (DIRECTORY / "commands.py").read_text(encoding="utf-8").casefold()
        self.assertNotIn("app" + "ium", source)
        self.assertNotIn("xcui" + "test", source)

    def test_skill_exposes_only_one_bare_open_call(self) -> None:
        text = (DIRECTORY / "SKILL.md").read_text(encoding="utf-8")
        blocks = text.split("```python\n")[1:]
        calls = []
        for block in blocks:
            tree = ast.parse(block.split("```", 1)[0])
            calls.extend(node for node in ast.walk(tree) if isinstance(node, ast.Call))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0].value, "open")
        self.assertNotIn("_plan_candidate", text)

    def test_import_is_inert_and_does_not_load_device_transport(self) -> None:
        script = (
            "import sys; import integrations.apple_maps.commands; "
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
