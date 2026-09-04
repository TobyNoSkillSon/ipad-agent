import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from ipad_agent.lab import scaffold_integration


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "remaining_static_contract_release_check", ROOT / "scripts" / "release_check.py"
)
release_check = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(release_check)


class RemainingStaticContractTests(unittest.TestCase):
    def test_addon_scaffold_index_entry_matches_strict_schema_without_mutating_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index_path = root / "integrations" / "index.json"
            index_path.parent.mkdir(parents=True)
            original_index = b'{"sentinel":"unchanged"}\n'
            index_path.write_bytes(original_index)

            result = scaffold_integration(
                "sample-app",
                name="Sample App",
                bundle_ids=["com.example.sample"],
                repository_root=root,
            )

            self.assertFalse(result["applied"])
            self.assertFalse(result["changed"])
            self.assertFalse(Path(result["target"]).exists())
            self.assertEqual(original_index, index_path.read_bytes())
            self.assertEqual(
                {
                    "id": "sample-app",
                    "kind": "addon",
                    "manifest": "sample-app/integration.json",
                    "category": "application",
                    "aliases": ["sample-app"],
                    "bundle_ids": ["com.example.sample"],
                },
                result["index_entry"],
            )

            schema = json.loads(
                (ROOT / "schemas" / "integrations-index-v1.json").read_text(encoding="utf-8")
            )
            document = {
                "$schema": "../schemas/integrations-index-v1.json",
                "schema": "ipad-agent.integrations-index/v1",
                "version": 1,
                "integrations": [result["index_entry"]],
            }
            release_check.validate_schema(document, schema, name="scaffold index preview")

    def test_step_seconds_schema_rejects_nonpositive_and_over_limit_values(self):
        schema = json.loads(
            (ROOT / "schemas" / "integration-v1.json").read_text(encoding="utf-8")
        )
        seconds_schema = schema["$defs"]["step"]["properties"]["seconds"]

        for value in (1e-12, 1, 120):
            with self.subTest(accepted=value):
                release_check.validate_schema(value, seconds_schema, name="step.seconds")

        for value in (-1, 0, 120.000001):
            with self.subTest(rejected=value):
                with self.assertRaises(release_check.CheckFailure):
                    release_check.validate_schema(value, seconds_schema, name="step.seconds")


if __name__ == "__main__":
    unittest.main()
