from __future__ import annotations

import unittest
from integrations._skill_test_support import assert_public_wrapper_forwarding
from integrations.google_maps import commands


class GoogleMapsApplicationContractTests(unittest.TestCase):
    def test_public_wrapper_forwards(self) -> None:
        assert_public_wrapper_forwarding(self, public_name="ipadgooglemaps", package="google_maps", implementation="google_maps")

    def test_surface_is_full_word_and_explicit(self) -> None:
        self.assertEqual(commands.COMMANDS, ("open", "search", "show", "directions", "map", "street-view", "link", "navigate"))
        self.assertEqual(commands.__all__, ["google_maps"])
        self.assertNotIn("_plan_candidate", commands.__all__)


if __name__ == "__main__":
    unittest.main()
