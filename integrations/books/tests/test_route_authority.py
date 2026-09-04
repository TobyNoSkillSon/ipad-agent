from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from integrations.books import commands

DIRECTORY = Path(__file__).resolve().parents[1]


class BooksRouteAuthorityTests(unittest.TestCase):
    def test_item_canonicalization_is_exact(self) -> None:
        self.assertEqual(commands._canonical_item(765135885), "ibooks://assetid/765135885")
        self.assertEqual(commands._canonical_item("765135885"), "ibooks://assetid/765135885")
        url = "https://books.apple.com/us/book/the-war-of-the-worlds/id765135885"
        self.assertEqual(commands._canonical_item(url), url)
        for value in (True, "0", "https://evil.example/us/book/a/id12345", "https://books.apple.com/us/book/a/id12345?x=1", "https://books.apple.com/us/search"):
            with self.assertRaises((TypeError, ValueError)):
                commands._canonical_item(value)

    def test_file_gate_is_epub_pdf_only(self) -> None:
        for value in ("/tmp/book.EPUB", Path("/tmp/document.PDF")):
            self.assertIs(commands._validated_books_file(value), value)
        for value in ("/tmp/image.png", "/tmp/archive.zip", "/tmp/book.mobi"):
            with self.assertRaises(ValueError):
                commands._validated_books_file(value)

    def test_canonical_asset_route_is_revalidated_without_weakening_input(self) -> None:
        canonical = "ibooks://assetid/765135885"
        self.assertEqual(commands._policy_url(canonical), canonical)
        with self.assertRaises(ValueError):
            commands._canonical_item(canonical)
        with mock.patch.object(commands.shared, "_direct_open") as direct:
            result = commands.books("item", canonical)
        self.assertFalse(result["ok"])
        direct.assert_not_called()
        for invalid in (
            "ibooks://assetid/012345",
            "ibooks://assetid/765135885?x=1",
            "ibooks://assetid//765135885",
            "IBOOKS://assetid/765135885",
        ):
            with self.assertRaises(ValueError):
                commands._policy_url(invalid)

    def test_numeric_and_string_asset_ids_dispatch_once_with_real_policy(self) -> None:
        for value in (765135885, "765135885"):
            with self.subTest(value=value), mock.patch.object(
                commands.shared, "_direct_open", return_value="accepted"
            ) as direct:
                self.assertEqual(commands.books("item", value), "accepted")
            direct.assert_called_once_with("Books", "ibooks://assetid/765135885")

    def test_evidence_is_profile_scoped_and_metadata_only(self) -> None:
        data = json.loads((DIRECTORY / "route-compatibility.json").read_text())
        profile = json.loads((DIRECTORY / data["profile"]).read_text())
        scope = {"product_type": "iPad17,1", "hardware_model": "J817AP", "os_build": "23G83"}
        self.assertEqual({key: profile[key] for key in scope}, scope)
        self.assertNotIn("device_id", json.dumps(data).casefold())
        self.assertEqual({row["command"]: row["availability"] for row in data["commands"]}, {"open": "proven", "drop": "candidate", "show": "proven", "item": "proven"})
        self.assertEqual({row["command"]: row["production"] for row in data["commands"]}, {"open": "admitted", "drop": "legacy-admitted", "show": "admitted", "item": "admitted"})
        workflows = (DIRECTORY / "WORKFLOWS.md").read_text()
        self.assertIn("`drop` remains candidate and `legacy-admitted`", workflows)
        self.assertIn("`show` is proven and admitted", workflows)


if __name__ == "__main__":
    unittest.main()
