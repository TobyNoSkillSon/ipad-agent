from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from integrations.appstore import commands

DIRECTORY = Path(__file__).resolve().parents[1]


class AppStoreRouteAuthorityTests(unittest.TestCase):
    def test_canonical_product_inputs(self) -> None:
        self.assertEqual(commands._product_url(361309726), "https://apps.apple.com/app/id361309726")
        self.assertEqual(commands._product_url("id361309726"), "https://apps.apple.com/app/id361309726")
        for url in ("https://apps.apple.com/app/pages/id361309726", "https://apps.apple.com/pl/app/pages/id361309726"):
            self.assertEqual(commands._product_url(url), url)
        for bad in (True, 0, "https://apps.apple.com/app/pages", "http://apps.apple.com/app/id361309726", "https://apps.apple.com/app/id361309726?x=1", "https://evil.example/app/id361309726"):
            with self.assertRaises((TypeError, ValueError)):
                commands._product_url(bad)

    def test_show_dispatches_once_after_revalidation(self) -> None:
        with mock.patch.object(commands.shared, "_direct_open", return_value="accepted") as direct:
            self.assertEqual(commands.app_store("show", 361309726), "accepted")
        direct.assert_called_once_with("App Store", "https://apps.apple.com/app/id361309726")

    def test_manifest_and_profile_are_direct_and_metadata_only(self) -> None:
        manifest = json.loads((DIRECTORY / "integration.json").read_text())
        self.assertEqual(manifest["selectors"], {})
        self.assertEqual(set(manifest["actions"]), {"activate"})
        evidence = json.loads((DIRECTORY / "route-compatibility.json").read_text())
        profile = json.loads((DIRECTORY / evidence["profile"]).read_text())
        scope = {"product_type": "iPad17,1", "hardware_model": "J817AP", "os_build": "23G83"}
        self.assertEqual({key: profile[key] for key in scope}, scope)
        self.assertEqual({row["command"]: row["availability"] for row in evidence["commands"]}, {"open": "proven", "show": "proven"})
        self.assertNotIn("device_id", json.dumps(evidence).casefold())


if __name__ == "__main__":
    unittest.main()
