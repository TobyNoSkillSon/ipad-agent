from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest import mock

from integrations.google_maps import commands
from ipad_agent.core.registry import load_registry
from ipad_agent.lab import PhysicalAuthorization, ScenarioPlan, run_fake_scenario

DIRECTORY = Path(__file__).resolve().parents[1]


class GoogleMapsRouteAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_registry(enabled_addons=())

    def route(self, command, args, options):
        return self.registry.resolve_url_route("google-maps", command, args, options).url

    def test_documented_routes_are_canonical(self) -> None:
        self.assertEqual(self.route("search", ("a+b & c",), {"api": "1"}), "https://www.google.com/maps/search/?query=a%2Bb%20%26%20c&api=1")
        self.assertEqual(self.route("directions", ("Gdańsk",), {"api": "1", "origin": "Warsaw", "travelmode": "driving"}), "https://www.google.com/maps/dir/?destination=Gda%C5%84sk&api=1&origin=Warsaw&travelmode=driving")
        self.assertEqual(self.route("map", ((48.85837, 2.29448),), {"api": "1", "map_action": "map", "zoom": 16}), "https://www.google.com/maps/@?center=48.85837,2.29448&api=1&map_action=map&zoom=16")
        self.assertEqual(self.route("street-view", ((48.85837, 2.29448),), {"api": "1", "map_action": "pano", "fov": 75}), "https://www.google.com/maps/@?viewpoint=48.85837,2.29448&api=1&map_action=pano&fov=75")

    def test_waypoints_are_bounded_and_encoded_once(self) -> None:
        args, options = commands._route_arguments("directions", ("Gdańsk",), {"waypoints": ["Łódź", "Toruń"], "waypoint_place_ids": ["ChIJ1", "ChIJ2"]})
        self.assertEqual(options["waypoints"], "Łódź|Toruń")
        self.assertIn("waypoints=%C5%81%C3%B3d%C5%BA%7CToru%C5%84", self.route("directions", args, options))
        with self.assertRaises(ValueError):
            commands._route_arguments("directions", ("x",), {"waypoints": ["a", "b"], "waypoint_place_ids": ["one"]})
        with self.assertRaises(ValueError):
            commands._route_arguments("directions", ("x",), {"waypoints": ["a", "b", "c", "d"]})

    def test_link_rejects_navigation_and_unknown_routes(self) -> None:
        good = "https://www.google.com/maps/search/?query=Rome&api=1"
        self.assertEqual(self.route("link", (good,), {}), good)
        for bad in ("https://www.google.com/maps/dir/?destination=Rome&api=1&dir_action=navigate", "https://evil.example/maps/search/?query=Rome&api=1", "https://www.google.com/maps/place/Rome"):
            with self.assertRaises(ValueError):
                self.route("link", (bad,), {})

    def test_production_admits_proven_and_gates_navigation(self) -> None:
        with mock.patch.object(commands.shared, "_direct_open", return_value="accepted") as direct:
            self.assertEqual(commands.google_maps("open"), "accepted")
        direct.assert_called_once_with("Google Maps")
        with mock.patch.object(commands, "_dispatch", return_value="accepted") as dispatch:
            self.assertEqual(commands.google_maps("search", "Rome"), "accepted")
        dispatch.assert_called_once()
        with mock.patch.object(commands, "_dispatch") as dispatch:
            result = commands.google_maps("navigate", "Rome")
        self.assertFalse(result["ok"])
        dispatch.assert_not_called()

    def test_candidate_probe_returns_bound_plan_and_never_dispatches(self) -> None:
        with mock.patch.object(commands, "_dispatch") as dispatch, mock.patch.object(
            commands.shared, "_direct_open"
        ) as direct, mock.patch("ipad_agent.core.config.load_config") as load_config:
            plan = commands._plan_candidate(
                "navigate", "Rome", origin="Florence", travelmode="driving"
            )
        self.assertIsInstance(plan, ScenarioPlan)
        self.assertEqual(plan.scenario_id, "navigate-candidate")
        self.assertEqual(plan.max_attempts, 1)
        self.assertEqual(len(plan.steps), 1)
        route = plan.steps[0].instruction["validated_route"]
        self.assertEqual(route["command"], "navigate")
        self.assertIn("destination=Rome", route["url"])
        self.assertIn("dir_action=navigate", route["url"])
        self.assertEqual(plan.steps[0].operation.retry_class.value, "inspect_then_decide")
        fake = run_fake_scenario(plan, record=False)
        self.assertTrue(fake.ok)
        self.assertEqual([1], [len(attempts) for attempts in fake.attempts])
        dispatch.assert_not_called()
        direct.assert_not_called()
        load_config.assert_not_called()

        confirmation = "starting navigation requires exact explicit user intent"
        now = datetime.now(timezone.utc)
        authorization = PhysicalAuthorization.for_plan(
            plan,
            actor="test reviewer",
            request="run this displayed navigation plan once",
            authorized_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
            confirmations=(confirmation,),
        )
        authorization.verify(plan, at=now + timedelta(seconds=1))

    def test_candidate_probe_rejects_boolean_non_candidate_and_invalid_inputs(self) -> None:
        cases = (
            ("navigate", ("Rome",), {"allow_explicit": True}),
            ("navigate", (), {}),
            ("search", ("Rome",), {}),
            ("open", (), {}),
        )
        for command, args, options in cases:
            with self.subTest(command=command), mock.patch.object(
                commands, "_dispatch"
            ) as dispatch, mock.patch.object(commands.shared, "_direct_open") as direct:
                result = commands._plan_candidate(command, *args, **options)
            self.assertFalse(result["ok"])
            dispatch.assert_not_called()
            direct.assert_not_called()

    def test_profile_is_non_unique(self) -> None:
        data = json.loads((DIRECTORY / "route-compatibility.json").read_text())
        profile = json.loads((DIRECTORY / data["profile"]).read_text())
        self.assertEqual((profile["product_type"], profile["hardware_model"], profile["os_build"]), ("iPad17,1", "J817AP", "23G83"))
        self.assertNotIn("device_id", json.dumps(data).casefold())


if __name__ == "__main__":
    unittest.main()
