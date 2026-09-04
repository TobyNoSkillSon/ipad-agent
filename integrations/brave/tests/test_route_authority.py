from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from integrations.brave import commands

DIRECTORY = Path(__file__).resolve().parents[1]
SCOPE = {"product_type": "iPad17,1", "hardware_model": "J817AP", "os_build": "23G83"}


class BraveRouteAuthorityTests(unittest.TestCase):
    def test_exact_availability_is_pinned(self) -> None:
        routes = commands._load_compatibility()
        self.assertEqual({k: v["availability"] for k, v in routes.items()}, {
            "website": "proven", "youtube": "candidate", "search": "proven",
            "private-website": "candidate", "ipfs": "incompatible", "ipns": "incompatible",
        })
        self.assertEqual(routes["search"]["production"], "admitted")
        for name in ("ipfs", "ipns"):
            failure = next(e for e in routes[name]["evidence"] if e["kind"] == "observer-screenshot-fail")
            self.assertEqual(failure["proof_scope"], SCOPE)
            self.assertEqual(failure["result"], "prior-route-remained-visible")

    def test_search_encoding_is_canonical(self) -> None:
        self.assertEqual(commands._build_search("a+b & c"), "brave://search?q=a%2Bb%20%26%20c")
        for value in ("", "   ", "bad\nquery"):
            with self.assertRaises((TypeError, ValueError)):
                commands._build_search(value)

    def test_production_search_dispatches_once(self) -> None:
        sentinel = object()
        with mock.patch.object(commands, "_custom_policy_url", return_value="validated") as policy, mock.patch.object(commands.shared, "_direct_open", return_value=sentinel) as direct:
            self.assertIs(commands.brave("search", "raw query"), sentinel)
        policy.assert_called_once_with("open-search", "brave://search?q=raw%20query")
        direct.assert_called_once_with("Brave", "validated")

    def test_candidate_and_incompatible_routes_fail_before_runtime(self) -> None:
        for route, value in (("private-website", "https://example.com"), ("ipfs", "ipfs://bafybeiemxf5abjwjbikoz4mc3a3dla6ual3jsgpdr4cjr3oz3evfyavhwq"), ("ipns", "ipns://docs.ipfs.tech")):
            with self.subTest(route=route), mock.patch.object(commands, "_custom_policy_url") as policy, mock.patch.object(commands.shared, "_direct_open") as direct:
                result = commands.brave(route, value)
            self.assertFalse(result["ok"])
            policy.assert_not_called()
            direct.assert_not_called()

    def test_manifest_and_policy_bind_only_declared_routes(self) -> None:
        manifest = json.loads((DIRECTORY / "integration.json").read_text())
        policy = json.loads((DIRECTORY / "url-policy.json").read_text())
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(set(policy["actions"]), {"open-url", "open-search", "open-private-website", "open-ipfs", "open-ipns"})
        self.assertNotIn('ipadbrave("open-text"', (DIRECTORY / "SKILL.md").read_text())

    def test_prose_matches_current_route_authority(self) -> None:
        manifest = json.loads((DIRECTORY / "integration.json").read_text())
        prose = " ".join(manifest["safety"]["prohibited"] + [manifest["privacy"]["notes"]])
        self.assertNotIn("dispatching search", prose.casefold())
        self.assertIn("website and search are proven and admitted", prose)
        self.assertIn("private website is candidate-gated", prose)
        self.assertIn("IPFS and IPNS are incompatible", prose)

        workflows = (DIRECTORY / "WORKFLOWS.md").read_text()
        candidate_matrix = workflows.split("## Candidate test matrix", 1)[1].split("## Excluded routes", 1)[0]
        self.assertNotIn("| `search` |", candidate_matrix)
        self.assertNotIn("| `ipfs` |", candidate_matrix)
        self.assertNotIn("| `ipns` |", candidate_matrix)
        self.assertIn("| `private-website` |", candidate_matrix)


if __name__ == "__main__":
    unittest.main()
