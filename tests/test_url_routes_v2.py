from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.parse import parse_qsl, urlsplit

from ipad_agent import ipadbrave, ipadmaps
from ipad_agent import api, coredevice
from ipad_agent.core import commands
from ipad_agent.coredevice import IPadControlError
from integrations.apple_maps import commands as maps_commands
from ipad_agent.config import Config
from ipad_agent.registry import IntegrationRegistry, RegistryError, load_registry
from ipad_agent.lab import PhysicalAuthorization, ScenarioPlan, plan_scenario, run_fake_scenario
from ipad_agent.lab.runner import PhysicalExecutor
from ipad_agent.lab.validation import manifest_digest, validate_evidence, validate_manifest
from ipad_agent.runtime import dispatch_client, registry_snapshot
from ipad_agent.urlroutes import (
    URLPolicyError, ValidatedURLRoute, load_url_policy, revalidate_validated_route,
)
from scripts.release_check import validate_manifests
from tests.lab_fixture import isolate_authorization_receipts, lab_fixture_manifest


ROOT = Path(__file__).resolve().parents[1]
LAB_FIXTURE = lab_fixture_manifest()


class URLRoutesV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        isolate_authorization_receipts(self)
        device_aliases = {"resolved-device", "00008101-private-device-identifier"}
        device_patch = mock.patch.object(
            coredevice,
            "_paired_physical_ipads",
            return_value=[("resolved-device", device_aliases)],
        )
        device_patch.start()
        self.addCleanup(device_patch.stop)

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_registry()
        cls.maps = cls.registry.resolve("maps")
        cls.policy = cls.maps.url_policy
        cls.lab_manifest = validate_manifest(LAB_FIXTURE)
        fixture_policy_bytes = json.dumps(
            LAB_FIXTURE["_lab_url_policy"], ensure_ascii=False, allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        cls.lab_policy = load_url_policy(
            fixture_policy_bytes, integration_id="lab-fixture",
            bundle_ids=("org.example.LabFixture",),
            actions=cls.lab_manifest["actions"],
        )
        cls.lab_integration = SimpleNamespace(
            bundle_id="org.example.LabFixture", url_policy=cls.lab_policy,
        )

    def route(self, command, *args, **options):
        return self.registry.resolve_url_route("maps", command, args, options)

    def fixture_registry(self):
        registry = mock.Mock()
        registry.resolve.return_value = self.lab_integration
        return registry

    def test_all_unified_maps_families_are_canonical_and_target_maps(self) -> None:
        cases = [
            ("frame", (), {"center": (40.75, -73.98), "heading": 180, "pitch": 15, "distance": 10000, "map": "explore"},
             "https://maps.apple.com/frame?center=40.75,-73.98&heading=180&pitch=15&distance=10000&map=explore"),
            ("search", ("pizza & pasta",), {"center": (40.7, -74), "span": (0.05, 0.05)},
             "https://maps.apple.com/search?query=pizza%20%26%20pasta&center=40.7,-74&span=0.05,0.05"),
            ("place", (), {"place_id": "opaque/+", "name": "A # B", "map": "hybrid"},
             "https://maps.apple.com/place?place-id=opaque%2F%2B&name=A%20%23%20B&map=hybrid"),
            ("look-around", (), {"coordinate": (40.706974, -74.011281)},
             "https://maps.apple.com/look-around?coordinate=40.706974,-74.011281"),
            ("directions", ("Library", "Park"), {
                "source_place_id": "source-id", "waypoint": ["Museum", "Cafe"],
                "waypoint_place_id": ["m-id", "c-id"], "destination_place_id": "dest-id",
                "mode": "transit", "avoid": ["stairs"],
                "transit_preferences": ["bus", "ferry"],
             }, "https://maps.apple.com/directions?destination=Library&source=Park&source-place-id=source-id&waypoint=Museum&waypoint=Cafe&waypoint-place-id=m-id&waypoint-place-id=c-id&destination-place-id=dest-id&mode=transit&avoid=stairs&transit-preferences=bus,ferry"),
            ("navigate", ("City Hall",), {"start": 5, "mode": "driving"},
             "https://maps.apple.com/directions?destination=City%20Hall&mode=driving&start=5"),
            ("guides", (), {}, "https://maps.apple.com/guides"),
            ("report-a-problem", (), {"address": "1000 Fifth Avenue"},
             "https://maps.apple.com/report-a-problem?address=1000%20Fifth%20Avenue"),
        ]
        for command, args, options, expected in cases:
            with self.subTest(command=command):
                route = self.registry.resolve_url_route("maps", command, args, options)
                self.assertEqual(expected, route.url)
                self.assertEqual("com.apple.Maps", route.bundle_id)
                self.assertEqual(self.maps.policy_sha256, route.policy_sha256)
                revalidate_validated_route(self.policy, route)

        show = self.route("show", "Warsaw")
        search = self.route("search", "Warsaw")
        self.assertEqual(search.url, show.url)
        self.assertEqual("search", show.command)

    def test_raw_query_values_encode_once_and_round_trip(self) -> None:
        raw = "space & equals= hash# percent% plus+ slash/ ? unicode Łódź"
        route = self.route("search", raw)
        self.assertNotIn("#", route.url)
        self.assertIn("%25", route.url)
        self.assertIn("%2B", route.url)
        self.assertIn("%2F", route.url)
        self.assertEqual([("query", raw)], parse_qsl(urlsplit(route.url).query))
        preencoded = self.route("search", "Warsaw%20Central")
        self.assertIn("Warsaw%2520Central", preencoded.url)

    def test_controls_limits_coordinates_enums_and_dependencies_fail_closed(self) -> None:
        for control in ("\x00", "\t", "\r", "\n", "\x7f", "\x85"):
            with self.subTest(control=repr(control)), self.assertRaises(URLPolicyError):
                self.route("search", "A" + control + "B")
        for coordinate in ((True, 1), (91, 0), (0, 181), (float("nan"), 0), (0, float("inf"))):
            with self.subTest(coordinate=coordinate), self.assertRaises(URLPolicyError):
                self.route("place", coordinate=coordinate)
        for call in (
            lambda: self.route("frame"),
            lambda: self.route("frame", span=(1, 1)),
            lambda: self.route("search", "x", span=(1, 1)),
            lambda: self.route("place"),
            lambda: self.route("look-around", address="x", place_id="id"),
            lambda: self.route("directions", "x", source_place_id="id"),
            lambda: self.route("directions", "x", waypoint=["a", "b"], waypoint_place_id=["id"]),
            lambda: self.route("directions", "x", transit_preferences=["bus"]),
            lambda: self.route("directions", "x", start=1),
            lambda: self.route("navigate", "x"),
            lambda: self.route("navigate", "x", start=-1),
            lambda: self.route("report-a-problem"),
            lambda: self.route("guides", query="x"),
        ):
            with self.assertRaises(URLPolicyError):
                call()

        for command, options in (
            ("search", {"query": None}),
            ("navigate", {"destination": "x", "start": None}),
            ("link", {"url": None}),
        ):
            with self.subTest(command=command), self.assertRaises(URLPolicyError):
                self.route(command, **options)

        span_camera = self.route(
            "frame", center=(1, 2), span=(0.1, 0.2), heading=90, pitch=15, distance=1000,
        )
        tracking_camera = self.route(
            "frame", center=(1, 2), mode="follow", heading=90, pitch=15, distance=1000,
        )
        self.assertIn("span=0.1,0.2&heading=90", span_camera.url)
        self.assertIn("mode=follow&heading=90", tracking_camera.url)
        self.assertIn("start=999999999999999999999999", self.route(
            "navigate", "x", start=999999999999999999999999,
        ).url)

    def test_hard_limit_counts_canonical_utf8_percent_encoding(self) -> None:
        prefix = "https://maps.apple.com/search?query="
        exact = "a" * (2048 - len(prefix.encode("utf-8")))
        self.assertEqual(2048, len(self.route("search", exact).url.encode("utf-8")))
        with self.assertRaisesRegex(URLPolicyError, "2048-byte"):
            self.route("search", exact + "a")
        # Each UTF-8 byte becomes one three-byte percent escape in the ASCII URL.
        with self.assertRaises(URLPolicyError):
            self.route("search", "é" * 400)

    def test_exact_links_are_reparsed_revalidated_and_canonicalized(self) -> None:
        route = self.route("link", "https://maps.apple.com/search?query=C++")
        self.assertEqual("https://maps.apple.com/search?query=C%2B%2B", route.url)
        self.assertEqual("link", route.command)
        self.assertEqual("open-link", route.action_id)
        revalidate_validated_route(self.policy, route)

        with mock.patch.object(
            maps_commands, "_resolve_short_maps_url",
            return_value="https://maps.apple.com/place?place-id=opaque",
        ) as resolver:
            args, options = maps_commands._maps_arguments(
                "link", ("https://abc.maps.apple/token",), {},
                resolver=maps_commands._resolve_short_maps_url,
            )
        resolver.assert_called_once()
        short = self.registry.resolve_url_route("maps", "link", args, options)
        self.assertEqual("https://maps.apple.com/place?place-id=opaque", short.url)

        with mock.patch.object(
            maps_commands, "_resolve_short_maps_url",
            return_value="https://maps.apple.com/search?query=keyword",
        ) as keyword_resolver:
            keyword_args, keyword_options = maps_commands._maps_arguments(
                "link", (), {"url": "https://abc.maps.apple/token"},
                resolver=maps_commands._resolve_short_maps_url,
            )
        keyword_resolver.assert_called_once_with("https://abc.maps.apple/token")
        keyword_route = self.registry.resolve_url_route(
            "maps", "link", keyword_args, keyword_options,
        )
        self.assertEqual("https://maps.apple.com/search?query=keyword", keyword_route.url)

        bad = (
            "http://maps.apple.com/search?query=x",
            "https://user:secret@maps.apple.com/search?query=x",
            "https://maps.apple.com:444/search?query=x",
            "https://maps.apple.com/search?query=x#fragment",
            "https://maps.apple.com/private?query=x",
            "https://maps.apple.com/search?query=x&query=y",
            "https://maps.apple.com/search?unknown=x",
            "https://maps.apple.com/directions?destination=x&start=1",
            "https://maps.apple.com/report-a-problem?address=x",
            "https://maps.apple.evil.example/token",
            "https://maps.apple.com/search?query=%zz",
        )
        for url in bad:
            with self.subTest(url=url), self.assertRaises(URLPolicyError):
                self.route("link", url)

    def test_policy_parser_rejects_unknown_fields_identity_and_action_drift(self) -> None:
        raw = json.loads((ROOT / "integrations/apple_maps/url-policy.json").read_text())
        mutations = []
        unknown = json.loads(json.dumps(raw)); unknown["commands"]["search"]["unexpected"] = True; mutations.append(unknown)
        wrong_id = json.loads(json.dumps(raw)); wrong_id["integration_id"] = "safari"; mutations.append(wrong_id)
        wrong_bundle = json.loads(json.dumps(raw)); wrong_bundle["target_bundle"] = "com.apple.mobilesafari"; mutations.append(wrong_bundle)
        missing = json.loads(json.dumps(raw)); del missing["commands"]["search"]; mutations.append(missing)
        path_drift = copy.deepcopy(raw); path_drift["commands"]["search"]["path"] = "/place"; mutations.append(path_drift)
        host_drift = copy.deepcopy(raw); host_drift["commands"]["search"]["host"] = "example.com"; mutations.append(host_drift)
        bad_contract = copy.deepcopy(raw); bad_contract["commands"]["link"]["canonical_commands"] = ["navigate"]; mutations.append(bad_contract)
        duplicate_alias = json.loads(json.dumps(raw)); duplicate_alias["commands"]["frame"]["aliases"] = ["show"]; mutations.append(duplicate_alias)
        for value in mutations:
            with self.assertRaises(URLPolicyError):
                load_url_policy(
                    (json.dumps(value) + "\n").encode(), integration_id="maps",
                    bundle_ids=self.maps.bundle_ids, actions=self.maps["actions"],
                )
        duplicate_json = b'{"schema":"ipad-agent.url-policy/v2","schema":"ipad-agent.url-policy/v2"}'
        with self.assertRaisesRegex(URLPolicyError, "duplicate JSON key"):
            load_url_policy(duplicate_json, integration_id="maps", bundle_ids=self.maps.bundle_ids, actions=self.maps["actions"])

        for action_id, value in (
            ("open-search", "https://maps.apple.com/place?query={query}"),
            ("open-search", "https://evil.example/search?query={query}"),
            ("open-link", "https://maps.apple.com/search"),
        ):
            actions = copy.deepcopy(self.maps["actions"])
            actions[action_id]["steps"][0]["value"] = value
            with self.subTest(action_id=action_id, value=value), self.assertRaises(URLPolicyError):
                load_url_policy(
                    (ROOT / "integrations/apple_maps/url-policy.json").read_bytes(),
                    integration_id="maps", bundle_ids=self.maps.bundle_ids, actions=actions,
                )

        weak_exact_actions = copy.deepcopy(self.maps["actions"])
        weak_exact_actions["open-link"]["retry"] = "safe_repeat"
        with self.assertRaisesRegex(URLPolicyError, "may not weaken canonical action retry"):
            load_url_policy(
                (ROOT / "integrations/apple_maps/url-policy.json").read_bytes(),
                integration_id="maps", bundle_ids=self.maps.bundle_ids,
                actions=weak_exact_actions,
            )

        negative_minimum = copy.deepcopy(raw)
        negative_minimum["commands"]["navigate"]["parameters"][-1]["minimum"] = -1
        with self.assertRaisesRegex(URLPolicyError, "minimum must be nonnegative"):
            load_url_policy(
                (json.dumps(negative_minimum) + "\n").encode(), integration_id="maps",
                bundle_ids=self.maps.bundle_ids, actions=self.maps["actions"],
            )

    def test_v2_is_generic_and_exact_routes_use_declared_canonical_builds(self) -> None:
        actions = {
            "activate": {
                "steps": [{"operation": "activate"}], "safety": "navigate", "retry": "safe_repeat",
            },
            "open-item": {
                "steps": [{"operation": "open-url", "value": "https://links.example.org/item?query={query}"}],
                "safety": "transient", "retry": "inspect_then_decide",
            },
            "open-exact": {
                "steps": [{"operation": "open-url", "value": "{url}"}],
                "safety": "transient", "retry": "inspect_then_decide",
            },
        }
        command_base = {
            "aliases": [], "scheme": None, "host": None, "path": None,
            "paths": [], "canonical_commands": [], "parameters": [], "constraints": [],
        }
        policy_value = {
            "$schema": "../../schemas/url-policy-v2.json", "schema": "ipad-agent.url-policy/v2",
            "version": 2, "integration_id": "example-app", "target_bundle": "org.example.App",
            "max_url_bytes": 1024,
            "commands": {
                "open": {**command_base, "action": "activate", "kind": "launch"},
                "item": {
                    **command_base, "action": "open-item", "kind": "build", "scheme": "https",
                    "host": "links.example.org", "path": "/item",
                    "parameters": [{
                        "name": "query", "query": "query", "type": "text", "required": True,
                        "positional": True, "repeatable": False,
                    }],
                },
                "link": {
                    **command_base, "action": "open-exact", "kind": "exact", "scheme": "https",
                    "host": "links.example.org", "paths": ["/item"],
                    "canonical_commands": ["item"],
                    "parameters": [{
                        "name": "url", "query": "url", "type": "text", "required": True,
                        "positional": True, "repeatable": False,
                    }],
                },
            },
        }
        policy = load_url_policy(
            (json.dumps(policy_value) + "\n").encode(), integration_id="example-app",
            bundle_ids=("org.example.App",), actions=actions,
        )
        from ipad_agent.urlroutes import resolve_url_route
        route = resolve_url_route(
            policy, "link", ("https://links.example.org/item?query=C++",), {},
        )
        self.assertEqual("https://links.example.org/item?query=C%2B%2B", route.url)
        self.assertEqual("open-exact", route.action_id)
        revalidate_validated_route(policy, route)

        for host, path in (("Links.example.org", "/item"), ("links.example.org", "/a/../item")):
            changed = copy.deepcopy(policy_value)
            changed["commands"]["item"]["host"] = host
            changed["commands"]["item"]["path"] = path
            with self.subTest(host=host, path=path), self.assertRaises(URLPolicyError):
                load_url_policy(
                    (json.dumps(changed) + "\n").encode(), integration_id="example-app",
                    bundle_ids=("org.example.App",), actions=actions,
                )

    def test_custom_scheme_v2_supports_safe_single_label_authority_and_empty_path(self) -> None:
        actions = {
            "activate": {
                "steps": [{"operation": "activate"}], "safety": "navigate", "retry": "safe_repeat",
            },
            "run-shortcut": {
                "steps": [{"operation": "open-url", "value": "shortcuts://run-shortcut?name={name}"}],
                "safety": "transient", "retry": "inspect_then_decide",
            },
        }
        base = {
            "aliases": [], "scheme": None, "host": None, "path": None,
            "paths": [], "canonical_commands": [], "parameters": [], "constraints": [],
        }
        value = {
            "$schema": "../../schemas/url-policy-v2.json", "schema": "ipad-agent.url-policy/v2",
            "version": 2, "integration_id": "shortcuts-test", "target_bundle": "com.apple.shortcuts",
            "max_url_bytes": 512,
            "commands": {
                "open": {**base, "action": "activate", "kind": "launch"},
                "run": {
                    **base, "action": "run-shortcut", "kind": "build",
                    "scheme": "shortcuts", "host": "run-shortcut", "path": "",
                    "parameters": [{
                        "name": "name", "query": "name", "type": "text", "required": True,
                        "positional": True, "repeatable": False,
                    }],
                },
            },
        }
        policy = load_url_policy(
            (json.dumps(value) + "\n").encode(), integration_id="shortcuts-test",
            bundle_ids=("com.apple.shortcuts",), actions=actions,
        )
        from ipad_agent.urlroutes import resolve_url_route
        route = resolve_url_route(policy, "run", ("Morning & Coffee",), {})
        self.assertEqual("shortcuts://run-shortcut?name=Morning%20%26%20Coffee", route.url)
        self.assertEqual("shortcuts://run-shortcut", route.url_shape)
        revalidate_validated_route(policy, ValidatedURLRoute.from_dict(route.to_dict()))

        http = copy.deepcopy(value)
        http["commands"]["run"].update({
            "scheme": "https", "host": "localhost", "path": "/run-shortcut",
        })
        http_actions = copy.deepcopy(actions)
        http_actions["run-shortcut"]["steps"][0]["value"] = "https://localhost/run-shortcut?name={name}"
        with self.assertRaisesRegex(URLPolicyError, "multi-label"):
            load_url_policy(
                (json.dumps(http) + "\n").encode(), integration_id="shortcuts-test",
                bundle_ids=("com.apple.shortcuts",), actions=http_actions,
            )
        forged = replace(route, url="shortcuts://user:secret@run-shortcut?name=x")
        with self.assertRaises(URLPolicyError):
            revalidate_validated_route(policy, forged)

    def test_v2_lab_plan_binds_canonical_route_and_encodes_navigation_injection_as_data(self) -> None:
        plan = plan_scenario(
            LAB_FIXTURE, "directions-direct", parameters={"destination": "x&start=0"},
        )
        instruction = plan.steps[0].instruction
        self.assertNotIn("value", instruction)
        record = instruction["validated_route"]
        self.assertEqual(
            "https://links.example.org/directions?destination=x%26start%3D0", record["url"],
        )
        self.assertEqual(
            [("destination", "x&start=0")], parse_qsl(urlsplit(record["url"]).query),
        )
        self.assertNotIn("start", dict(parse_qsl(urlsplit(record["url"]).query)))
        self.assertEqual(record["policy_sha256"], plan.metadata["url_policy_binding"]["sha256"])

        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_plan(
            plan, actor="test", request="exact route", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        changed_record = dict(record)
        changed_record["url"] = "https://links.example.org/directions?destination=x&start=0"
        changed_step = replace(
            plan.steps[0], instruction={"operation": "open-url", "validated_route": changed_record},
        )
        changed_plan = replace(plan, steps=(changed_step,))
        with self.assertRaisesRegex(PermissionError, "plan_digest"):
            authorization.verify(changed_plan)

        with tempfile.TemporaryDirectory() as temporary:
            evidence = validate_evidence(run_fake_scenario(
                plan, repository_root=temporary,
            ).evidence_path)
        self.assertEqual(record, evidence["plan"]["steps"][0]["instruction"]["validated_route"])

    def test_physical_v2_route_is_reconstructed_and_revalidated_before_exact_dispatch(self) -> None:
        plan = plan_scenario(
            LAB_FIXTURE, "search-direct", parameters={"query": "private fixture value"},
        )
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_plan(
            plan, actor="test", request="one exact route", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        executor = PhysicalExecutor(physical=True, authorization=authorization, plan=plan)
        registry = self.fixture_registry()
        launch = coredevice.LaunchResult(
            "org.example.LabFixture", "device", 0.01,
            plan.steps[0].instruction["validated_route"]["url"], False,
        )
        with mock.patch("ipad_agent.config.load_config", return_value=Config()), mock.patch(
            "ipad_agent.registry.load_registry", return_value=registry,
        ), mock.patch(
            "ipad_agent.urlroutes.revalidate_validated_route", wraps=revalidate_validated_route,
        ) as revalidate, mock.patch(
            "ipad_agent.lab.runner.open_validated_route_when_unlocked",
            return_value=coredevice.UnlockDispatchResult("dispatched", launch),
        ) as dispatch, mock.patch.object(executor, "_merge_coredevice_environment"):
            result = executor.execute(plan.steps[0], plan.bundle_id)
        self.assertTrue(result.ok)
        revalidate.assert_called_once_with(self.lab_policy, mock.ANY)
        dispatch.assert_called_once()
        routed = dispatch.call_args.args[0]
        self.assertEqual("org.example.LabFixture", routed.bundle_id)
        self.assertEqual(
            plan.steps[0].instruction["validated_route"]["url"], routed.url,
        )

    def test_maps_candidate_probe_returns_a_bound_plan_without_dispatch(self) -> None:
        with mock.patch("ipad_agent.config.load_config") as config, mock.patch(
            "ipad_agent.registry.load_registry"
        ) as registry, mock.patch.object(
            coredevice, "open_validated_route_when_unlocked"
        ) as dispatch:
            plan = maps_commands._plan_candidate(
                "navigate", "private place", start=0,
            )
        self.assertIsInstance(plan, ScenarioPlan)
        self.assertEqual("navigate-candidate", plan.scenario_id)
        self.assertEqual("maps", plan.integration_id)
        self.assertEqual(1, plan.max_attempts)
        self.assertEqual("navigate", plan.steps[0].instruction["validated_route"]["command"])
        config.assert_not_called()
        registry.assert_not_called()
        dispatch.assert_not_called()

    def test_lab_fake_explicit_pre_dispatch_rejection_is_certain(self) -> None:
        plan = plan_scenario(
            LAB_FIXTURE, "search-direct", parameters={"query": "private fixture value"},
        )
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_plan(
            plan, actor="test", request="one exact route", authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )
        executor = PhysicalExecutor(physical=True, authorization=authorization, plan=plan)
        registry = self.fixture_registry()
        pre_dispatch_rejection = IPadControlError(
            "fake executor rejected before dispatch", response_lost=False,
        )
        with mock.patch("ipad_agent.config.load_config", return_value=Config()), mock.patch(
            "ipad_agent.registry.load_registry", return_value=registry,
        ), mock.patch(
            "ipad_agent.lab.runner.open_validated_route_when_unlocked",
            side_effect=pre_dispatch_rejection,
        ), mock.patch.object(executor, "_merge_coredevice_environment"):
            result = executor.execute(plan.steps[0], plan.bundle_id)
        self.assertFalse(result.ok)
        self.assertFalse(result.uncertain)
        self.assertFalse(pre_dispatch_rejection.dispatched)
        self.assertEqual("response_received", result.phase.value)

    def test_lab_digest_binds_the_full_normalized_v2_policy(self) -> None:
        manifest = json.loads((ROOT / "integrations/apple_maps/integration.json").read_text())
        policy = json.loads((ROOT / "integrations/apple_maps/url-policy.json").read_text())
        manifest["_lab_url_policy"] = policy
        normalized = validate_manifest(manifest)
        self.assertEqual("/search", normalized["_lab_url_policy"]["commands"]["search"]["path"])
        before = manifest_digest(normalized)
        changed = copy.deepcopy(manifest)
        changed["_lab_url_policy"]["max_url_bytes"] = 2047
        after = manifest_digest(validate_manifest(changed))
        self.assertNotEqual(before, after)

    def test_v1_registry_and_release_admission_is_legacy_browser_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "integrations", root / "integrations")
            manifest = json.loads((root / "integrations/apple_maps/integration.json").read_text())
            open_actions = {
                action_id: ["https"] for action_id, action in manifest["actions"].items()
                if any(step["operation"] == "open-url" for step in action["steps"])
            }
            legacy = {
                "$schema": "../../schemas/url-policy-v1.json",
                "schema": "ipad-agent.url-policy/v1", "version": 1,
                "integration_id": "maps", "actions": open_actions,
            }
            (root / "integrations/apple_maps/url-policy.json").write_text(
                json.dumps(legacy) + "\n", encoding="utf-8",
            )
            with self.assertRaisesRegex(RegistryError, "reserved for legacy Safari and Brave"):
                IntegrationRegistry(root / "integrations/index.json")

            shutil.copytree(ROOT / "schemas", root / "schemas")
            candidates = {
                path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
            }
            issues = validate_manifests(root, candidates)
            self.assertTrue(any("reserved for legacy Safari and Brave" in issue for issue in issues))

    def test_disabled_brave_returns_a_failed_result_without_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"IPAD_AGENT_CONFIG": str(Path(temporary) / "missing.toml")}, clear=False,
        ), mock.patch("ipad_agent.core.commands._direct_open") as dispatch:
            result = ipadbrave("website", "https://example.com")
        self.assertFalse(result["ok"])
        self.assertIn("not enabled", result["error"])
        dispatch.assert_not_called()

    def test_disabled_addon_policy_stays_lazy_and_snapshot_binds_policy_bytes(self) -> None:
        original = Path.read_bytes
        opened: list[str] = []
        def recording(path: Path):
            opened.append(str(path))
            return original(path)
        with mock.patch.object(Path, "read_bytes", recording):
            load_registry()
        self.assertFalse(any("integrations/brave/url-policy.json" in path for path in opened))

        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            shutil.copytree(ROOT / "integrations", temp / "integrations")
            before = registry_snapshot(IntegrationRegistry(temp / "integrations/index.json"))
            policy_path = temp / "integrations/apple_maps/url-policy.json"
            policy_path.write_bytes(policy_path.read_bytes() + b" \n")
            after = registry_snapshot(IntegrationRegistry(temp / "integrations/index.json"))
        self.assertNotEqual(before["policy_sha256"]["maps"], after["policy_sha256"]["maps"])
        self.assertNotEqual(before["contract_sha256"], after["contract_sha256"])

    def test_public_candidate_gate_and_private_probe_never_dispatch(self) -> None:
        with mock.patch.object(coredevice, "open_validated_route_when_unlocked") as dispatch, mock.patch(
            "ipad_agent.config.load_config"
        ) as config, mock.patch("ipad_agent.registry.load_registry") as registry:
            invalid = ipadmaps("unknown", "x")
            candidate = ipadmaps("navigate", "x", start=0)
            plan = maps_commands._plan_candidate("navigate", "Warsaw", start=0)
        self.assertFalse(invalid["ok"])
        self.assertIn("unsupported command", invalid["error"])
        self.assertFalse(candidate["ok"])
        self.assertIn("candidate", candidate["error"])
        self.assertEqual("not_sent", candidate["_operation"]["phase"])
        self.assertIsInstance(plan, ScenarioPlan)
        self.assertEqual("navigate-candidate", plan.scenario_id)
        dispatch.assert_not_called()
        config.assert_not_called()
        registry.assert_not_called()

        rejected = maps_commands._plan_candidate(
            "navigate", "Warsaw", start=0, allow_explicit=True,
        )
        self.assertFalse(rejected["ok"])
        self.assertIn("not candidate authorization", rejected["error"])

    def test_shared_validated_route_open_forwards_terminate_flag(self) -> None:
        route = self.route("search", "Warsaw")
        config = Config()
        for terminate in (False, True):
            with self.subTest(terminate=terminate), mock.patch.object(
                coredevice, "open_validated_route_when_unlocked",
                return_value=coredevice.UnlockDispatchResult("locked", None),
            ) as helper:
                result = commands._validated_route_open(
                    route, config=config, registry=self.registry, terminate=terminate,
                )
            self.assertFalse(result["ok"])
            helper.assert_called_once_with(
                route, config=config, registry=self.registry, terminate=terminate,
            )

    def test_nonzero_transport_launch_is_uncertain_and_redacts_private_output(self) -> None:
        private = "17 Private Lane, Secret City"
        route = self.route("search", private)
        private_url = route.url
        private_device = "00008101-private-device-identifier"
        private_command = (
            f"xcrun devicectl device process launch --device {private_device} "
            f"--payload-url {private_url} com.apple.Maps"
        )
        completed = SimpleNamespace(
            returncode=1,
            stdout=f"command={private_command}",
            stderr=f"rejected payload={private_url} query={private}",
        )
        with mock.patch.object(coredevice, "_resolve_device", return_value=private_device), mock.patch.object(
            coredevice, "_wait_for_device_unlocked", return_value="unlocked",
        ), mock.patch.object(coredevice.subprocess, "run", return_value=completed) as run:
            result = commands._validated_route_open(
                route, config=Config(), registry=self.registry,
            )
        rendered = json.dumps(dict(result), ensure_ascii=False)
        self.assertEqual(1, run.call_count)
        self.assertFalse(result["ok"])
        self.assertTrue(result["uncertain"])
        self.assertEqual("response_lost", result["_operation"]["phase"])
        self.assertEqual("coredevice_response_lost", result["error_info"]["code"])
        for secret in (private, private_url, private_command, private_device, "rejected payload"):
            self.assertNotIn(secret, rendered)

        uncertain_error = IPadControlError(
            f"response disappeared for {private}", response_lost=True,
        )
        with mock.patch.object(
            coredevice, "open_validated_route_when_unlocked", side_effect=uncertain_error,
        ):
            uncertain = commands._validated_route_open(
                route, config=Config(), registry=self.registry,
            )
        self.assertTrue(uncertain["uncertain"])
        self.assertEqual("coredevice_response_lost", uncertain["error_info"]["code"])
        self.assertNotIn(private, json.dumps(dict(uncertain), ensure_ascii=False))

    def test_legacy_display_coredevice_failures_redact_private_urls(self) -> None:
        private = "https://maps.apple.com/directions?destination=Private%20Address"
        failure = IPadControlError(f"devicectl rejected --payload-url {private}")
        with mock.patch.object(api, "_show", side_effect=failure):
            result = api.show("maps", "Private Address")
        self.assertFalse(result["ok"])
        self.assertFalse(result["uncertain"])
        self.assertNotIn(private, result["error"])
        self.assertEqual("CoreDevice rejected the request before acceptance", result["error"])

    def test_pre_launch_failures_stay_certain(self) -> None:
        with mock.patch.object(coredevice.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                coredevice.open_ipad(
                    "", device="resolved-device", config=Config(), registry=self.registry,
                )
        run.assert_not_called()

        discovery_failure = SimpleNamespace(
            returncode=1, stdout="", stderr="private discovery diagnostics",
        )
        with mock.patch.object(
            coredevice.subprocess, "run", return_value=discovery_failure,
        ) as run:
            with self.assertRaises(IPadControlError) as raised:
                coredevice.open_ipad(
                    "Unresolved App", device="resolved-device",
                    config=Config(), registry=self.registry,
                )
        self.assertEqual(1, run.call_count)
        self.assertFalse(raised.exception.response_lost)
        self.assertFalse(raised.exception.dispatched)

    def test_launch_timeout_remains_response_lost_and_single_attempt(self) -> None:
        timeout = coredevice.subprocess.TimeoutExpired("private launch command", 15)
        with mock.patch.object(coredevice.subprocess, "run", side_effect=timeout) as run:
            with self.assertRaises(IPadControlError) as raised:
                coredevice.open_ipad(
                    "com.apple.Maps", device="resolved-device",
                    config=Config(), registry=self.registry,
                )
        self.assertEqual(1, run.call_count)
        self.assertTrue(raised.exception.response_lost)
        self.assertTrue(raised.exception.uncertain)
        self.assertTrue(raised.exception.dispatched)

    def test_launch_keyboard_interrupt_is_response_lost_redacted_and_not_retried(self) -> None:
        private = "/private/project/.runtime/coredevice/secret-device-and-route.txt"
        with mock.patch.object(
            coredevice.subprocess,
            "run",
            side_effect=KeyboardInterrupt(f"lost control near {private}"),
        ) as run:
            with self.assertRaises(IPadControlError) as raised:
                coredevice.open_ipad(
                    "com.apple.Maps", device="resolved-device",
                    config=Config(), registry=self.registry,
                )

        self.assertEqual(1, run.call_count)
        self.assertTrue(raised.exception.response_lost)
        self.assertTrue(raised.exception.uncertain)
        self.assertTrue(raised.exception.dispatched)
        self.assertEqual(
            "CoreDevice launch response was lost after dispatch",
            str(raised.exception),
        )
        self.assertNotIn(private, str(raised.exception))

        route = self.route("search", "Private Address")
        with mock.patch.object(
            coredevice,
            "open_validated_route_when_unlocked",
            side_effect=raised.exception,
        ) as dispatch:
            result = commands._validated_route_open(
                route, config=Config(), registry=self.registry,
            )
        rendered = json.dumps(dict(result), ensure_ascii=False)
        self.assertEqual(1, dispatch.call_count)
        self.assertFalse(result["ok"])
        self.assertTrue(result["uncertain"])
        self.assertEqual("response_lost", result["_operation"]["phase"])
        self.assertNotIn(private, rendered)

    def test_keyboard_interrupt_during_post_launch_check_is_response_lost_and_redacted(self) -> None:
        private = "/private/project/.runtime/coredevice/post-launch-secret.txt"
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(
            coredevice.subprocess, "run", return_value=completed
        ) as run, mock.patch.object(
            coredevice,
            "_device_locked",
            side_effect=KeyboardInterrupt(f"cancelled while reading {private}"),
        ):
            with self.assertRaises(IPadControlError) as raised:
                coredevice.open_ipad(
                    "com.apple.Maps", device="resolved-device",
                    config=Config(), registry=self.registry,
                )

        self.assertEqual(1, run.call_count)
        self.assertTrue(raised.exception.response_lost)
        self.assertTrue(raised.exception.dispatched)
        self.assertEqual(
            "CoreDevice launch response was lost after dispatch",
            str(raised.exception),
        )
        self.assertNotIn(private, str(raised.exception))

    def test_nonzero_launch_result_is_response_lost_without_output_details(self) -> None:
        private_url = "https://maps.apple.com/search?query=private"
        private_device = "00008101-private-device-identifier"
        private_command = (
            f"xcrun devicectl device process launch --device {private_device} "
            f"--payload-url {private_url} com.apple.Maps"
        )
        completed = SimpleNamespace(
            returncode=1,
            stdout=f"command={private_command}",
            stderr=f"payload={private_url}",
        )
        with mock.patch.object(coredevice.subprocess, "run", return_value=completed) as run:
            with self.assertRaises(IPadControlError) as raised:
                coredevice.open_ipad(
                    "com.apple.Maps", url=private_url, device=private_device,
                    config=Config(), registry=self.registry,
                )
        self.assertEqual(1, run.call_count)
        self.assertTrue(raised.exception.response_lost)
        self.assertTrue(raised.exception.uncertain)
        self.assertTrue(raised.exception.dispatched)
        rendered = str(raised.exception)
        for secret in (private_url, private_command, private_device):
            self.assertNotIn(secret, rendered)

    def test_post_dispatch_failures_are_response_lost_and_never_retried(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(coredevice.subprocess, "run", return_value=completed) as run, mock.patch.object(
            coredevice, "_device_locked", side_effect=OSError("temporary output failed"),
        ):
            with self.assertRaises(IPadControlError) as raised:
                coredevice.open_ipad(
                    "com.apple.Maps", device="resolved-device", config=Config(), registry=self.registry,
                )
        self.assertEqual(1, run.call_count)
        self.assertTrue(raised.exception.response_lost)
        self.assertTrue(raised.exception.uncertain)
        self.assertTrue(raised.exception.dispatched)

        route = self.route("search", "Warsaw")
        with mock.patch.object(
            coredevice, "open_validated_route_when_unlocked", side_effect=raised.exception,
        ) as dispatch:
            result = commands._validated_route_open(
                route, config=Config(), registry=self.registry,
            )
        self.assertEqual(1, dispatch.call_count)
        self.assertTrue(result["uncertain"])
        self.assertEqual("response_lost", result["_operation"]["phase"])

    def test_raw_runtime_url_opcode_is_rejected_before_transport(self) -> None:
        with mock.patch("ipad_agent.runtime._client_send") as transport:
            result = dispatch_client(
                {"op": "o", "app": "Maps", "url": "https://maps.apple.com/guides"},
                config=Config(), registry=self.registry,
            )
        self.assertFalse(result["ok"])
        self.assertEqual("not_sent", result["_operation"]["phase"])
        transport.assert_not_called()

    def test_coredevice_boundary_revalidates_and_dispatches_exact_bundle_once(self) -> None:
        route = self.route("search", "Warsaw")
        launch = coredevice.LaunchResult("com.apple.Maps", "resolved-device", 0.01, route.url, False)
        with mock.patch.object(coredevice, "_resolve_device", return_value="resolved-device") as resolve, mock.patch.object(
            coredevice, "_wait_for_device_unlocked", return_value="unlocked"
        ), mock.patch.object(coredevice, "open_ipad", return_value=launch) as open_ipad:
            outcome = coredevice.open_validated_route_when_unlocked(
                route, terminate=True,
                config=SimpleNamespace(device=None), registry=self.registry,
            )
        self.assertEqual("dispatched", outcome.status)
        resolve.assert_called_once()
        open_ipad.assert_called_once_with(
            "com.apple.Maps",
            url=route.url,
            device="resolved-device",
            terminate=True,
            timeout=15.0,
            config=mock.ANY,
            registry=self.registry,
        )

        exact = self.route("link", "https://maps.apple.com/search?query=C++")
        with mock.patch.object(coredevice, "_resolve_device", return_value="resolved-device"), mock.patch.object(
            coredevice, "_wait_for_device_unlocked", return_value="unlocked",
        ), mock.patch.object(coredevice, "open_ipad", return_value=launch) as open_exact:
            exact_outcome = coredevice.open_validated_route_when_unlocked(
                exact, config=SimpleNamespace(device=None), registry=self.registry,
            )
        self.assertEqual("dispatched", exact_outcome.status)
        open_exact.assert_called_once()
        self.assertIs(open_exact.call_args.kwargs["terminate"], False)

        forged = ValidatedURLRoute(
            route.integration_id, route.command, route.action_id, "com.apple.mobilesafari",
            route.url, route.policy_sha256, route.safety, route.retry, route.url_shape,
        )
        with mock.patch.object(coredevice, "_resolve_device") as resolve:
            with self.assertRaises(ValueError):
                coredevice.open_validated_route_when_unlocked(
                    forged, config=SimpleNamespace(device=None), registry=self.registry,
                )
        resolve.assert_not_called()

    def test_terminating_validated_route_uses_one_url_launch_subprocess(self) -> None:
        route = self.route("directions", "Gdańsk", "Warsaw")
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        config = SimpleNamespace(device="resolved-device")
        with mock.patch.object(
            coredevice, "_wait_for_device_unlocked", return_value="unlocked",
        ) as preflight, mock.patch.object(
            coredevice, "_device_locked", return_value=False,
        ), mock.patch.object(
            coredevice.subprocess, "run", return_value=completed,
        ) as run:
            outcome = coredevice.open_validated_route_when_unlocked(
                route, terminate=True, config=config, registry=self.registry,
            )
        self.assertEqual("dispatched", outcome.status)
        preflight.assert_called_once_with(
            "resolved-device", wait_timeout=10.0, poll_interval=0.25,
            lock_check_timeout=5.0,
        )
        run.assert_called_once_with(
            [
                "xcrun", "devicectl", "device", "process", "launch",
                "--device", "resolved-device", "--terminate-existing",
                "--payload-url", route.url, "com.apple.Maps",
            ],
            capture_output=True,
            text=True,
            timeout=15.0,
        )

    def test_non_maps_validated_route_defaults_to_nonterminating(self) -> None:
        plan = plan_scenario(
            LAB_FIXTURE, "search-direct", parameters={"query": "fixture value"},
        )
        route = ValidatedURLRoute.from_dict(
            plan.steps[0].instruction["validated_route"],
        )
        registry = self.fixture_registry()
        launch = coredevice.LaunchResult(
            route.bundle_id, "resolved-device", 0.01, route.url, False,
        )
        with mock.patch.object(
            coredevice, "_resolve_device", return_value="resolved-device",
        ), mock.patch.object(
            coredevice, "_wait_for_device_unlocked", return_value="unlocked",
        ), mock.patch.object(
            coredevice, "open_ipad", return_value=launch,
        ) as open_ipad:
            outcome = coredevice.open_validated_route_when_unlocked(
                route, config=SimpleNamespace(device=None), registry=registry,
            )
        self.assertEqual("dispatched", outcome.status)
        open_ipad.assert_called_once()
        self.assertIs(open_ipad.call_args.kwargs["terminate"], False)

    def test_validated_route_rejects_nonboolean_terminate_before_context_load(self) -> None:
        route = self.route("search", "Warsaw")
        with mock.patch.object(coredevice, "_control_context") as context:
            with self.assertRaisesRegex(TypeError, "terminate must be a bool"):
                coredevice.open_validated_route_when_unlocked(route, terminate=1)
        context.assert_not_called()


    def test_external_query_names_may_use_underscores_without_weakening_command_ids(self) -> None:
        google = self.registry.resolve("google-maps")
        route = self.registry.resolve_url_route(
            "google-maps", "search", ("Rome",), {"api": "1", "query_place_id": "ChIJu46S-ZZhLxMROG5lkwZ3D7k"},
        )
        self.assertIn("query_place_id=", route.url)
        with self.assertRaises((RegistryError, URLPolicyError, ValueError)):
            self.registry.resolve_url_route("google-maps", "search", ("Rome",), {"api": "1", "unknown_field": "x"})
        self.assertEqual("com.google.Maps", google.bundle_id)


if __name__ == "__main__":
    unittest.main()
