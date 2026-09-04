from __future__ import annotations

import unittest

from integrations._skill_test_support import (
    assert_command_surface,
    assert_public_wrapper_forwarding,
    assert_skill_alignment,
)


PACKAGE = "settings"
PUBLIC = "ipadsettings"
IMPLEMENTATION = "settings"
COMMANDS = (
    "open",
    "general",
    "about",
    "wifi",
    "bluetooth",
    "battery",
    "accessibility",
    "show",
)


class SettingsApplicationContractTests(unittest.TestCase):
    def test_public_wrapper_forwards_to_application_adapter(self) -> None:
        assert_public_wrapper_forwarding(
            self, public_name=PUBLIC, package=PACKAGE, implementation=IMPLEMENTATION
        )

    def test_current_command_surface_is_explicit(self) -> None:
        assert_command_surface(self, package=PACKAGE, expected=COMMANDS)

    def test_skill_examples_match_the_command_surface(self) -> None:
        assert_skill_alignment(
            self, package=PACKAGE, public_name=PUBLIC, expected=COMMANDS
        )


if __name__ == "__main__":
    unittest.main()
