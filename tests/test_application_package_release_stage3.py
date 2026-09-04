from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import release_check


ROOT = Path(__file__).resolve().parents[1]


def candidate_relatives() -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for path in release_check.release_paths(ROOT)
    }


class ApplicationPackageReleaseStage3Tests(unittest.TestCase):
    def test_current_application_packages_pass_the_release_contract(self) -> None:
        self.assertEqual(
            release_check.validate_application_packages(ROOT, candidate_relatives()),
            [],
        )

    def test_package_exposes_only_the_use_ipad_gateway(self) -> None:
        package = release_check._strict_json(ROOT / "package.json")
        self.assertEqual(["./skills/use-ipad"], package["pi"]["skills"])
        gateway = ROOT / "skills/use-ipad/SKILL.md"
        fields = release_check._skill_frontmatter(gateway)
        self.assertEqual(release_check._GATEWAY_SKILL_FIELDS, fields)
        self.assertEqual(
            release_check._GATEWAY_SKILL_BODY,
            release_check._skill_body(gateway),
        )

    def test_app_local_tests_are_required_for_every_indexed_package(self) -> None:
        candidates = candidate_relatives()
        candidates = {
            path for path in candidates
            if not path.startswith("integrations/apple_maps/tests/test_")
        }
        issues = release_check.validate_application_packages(ROOT, candidates)
        self.assertTrue(any("app-local tests are missing" in issue for issue in issues))

    def test_workflows_are_required_for_every_indexed_package(self) -> None:
        candidates = candidate_relatives() - {"integrations/apple_maps/WORKFLOWS.md"}
        issues = release_check.validate_application_packages(ROOT, candidates)
        self.assertTrue(any("WORKFLOWS.md" in issue for issue in issues))

    def test_app_local_skills_are_kept_as_uninstalled_instructions(self) -> None:
        package = release_check._strict_json(ROOT / "package.json")
        declarations = set(package["pi"]["skills"])
        index = release_check._strict_json(ROOT / "integrations/index.json")
        for entry in index["integrations"]:
            directory = Path(entry["manifest"]).parent
            skill = ROOT / "integrations" / directory / "SKILL.md"
            self.assertTrue(skill.is_file())
            self.assertNotIn(f"./integrations/{directory.as_posix()}", declarations)

    def test_extra_installed_skill_declarations_are_rejected(self) -> None:
        actual = release_check._strict_json
        package = copy.deepcopy(actual(ROOT / "package.json"))
        package["pi"]["skills"].append("./integrations/apple_maps")

        def altered(path: Path):
            if path == ROOT / "package.json":
                return package
            return actual(path)

        with mock.patch.object(release_check, "_strict_json", side_effect=altered):
            issues = release_check.validate_application_packages(ROOT, candidate_relatives())
        self.assertTrue(any("only the use-ipad gateway skill" in issue for issue in issues))

    def test_ids_and_aliases_share_one_normalized_lookup_namespace(self) -> None:
        actual = release_check._strict_json
        original = actual(ROOT / "integrations/index.json")
        mutations = (
            ("alias collides with ID", "brave", ["brave", "brave browser", "google_maps"]),
            ("ID collides with alias", "apple-maps", ["apple-maps", "brave browser"]),
        )
        for label, integration_id, aliases in mutations:
            with self.subTest(label=label):
                index = copy.deepcopy(original)
                brave = next(
                    entry for entry in index["integrations"] if entry["id"] == "brave"
                )
                brave["id"] = integration_id
                brave["aliases"] = aliases

                def altered(path: Path, *, value: dict = index):
                    if path == ROOT / "integrations/index.json":
                        return value
                    return actual(path)

                with mock.patch.object(release_check, "_strict_json", side_effect=altered):
                    issues = release_check.validate_manifests(
                        ROOT, candidate_relatives()
                    )
                self.assertTrue(
                    any("normalized integration reference" in issue for issue in issues),
                    issues,
                )

    def test_manifest_aliases_cannot_define_a_second_lookup_namespace(self) -> None:
        actual = release_check._strict_json
        manifest_path = ROOT / "integrations/brave/integration.json"
        manifest = copy.deepcopy(actual(manifest_path))
        manifest["aliases"].append("unique manifest-only alias")

        def altered(path: Path):
            if path == manifest_path:
                return manifest
            return actual(path)

        with mock.patch.object(release_check, "_strict_json", side_effect=altered):
            issues = release_check.validate_manifests(ROOT, candidate_relatives())
        self.assertTrue(any("aliases must exactly match" in issue for issue in issues), issues)

    def test_duplicate_skill_names_are_rejected(self) -> None:
        actual = release_check._skill_frontmatter
        safari_name = actual(ROOT / "integrations/safari/SKILL.md")["name"]

        def duplicate(path: Path) -> dict[str, str]:
            fields = actual(path)
            if path.parent.name == "apple_maps":
                return {**fields, "name": safari_name}
            return fields

        with mock.patch.object(release_check, "_skill_frontmatter", side_effect=duplicate):
            issues = release_check.validate_application_packages(ROOT, candidate_relatives())
        self.assertTrue(any("duplicate skill name" in issue for issue in issues))

    def test_every_other_non_colocated_skill_is_rejected(self) -> None:
        extra = "skills/other/SKILL.md"
        candidates = candidate_relatives() | {extra}
        actual = release_check._skill_frontmatter

        def extra_skill(path: Path) -> dict[str, str]:
            if path == ROOT / extra:
                return {"name": "ipad-other", "description": "Other skill"}
            return actual(path)

        with mock.patch.object(release_check, "_skill_frontmatter", side_effect=extra_skill):
            issues = release_check.validate_application_packages(ROOT, candidates)
        self.assertTrue(any("non-colocated" in issue for issue in issues))

    def test_gateway_body_rejects_eager_loading_or_copying_all_app_skills(self) -> None:
        eager_body = """
# Use the iPad

Read every `integrations/*/SKILL.md` now and copy all instructions into this gateway.
"""
        with mock.patch.object(release_check, "_skill_body", return_value=eager_body):
            issues = release_check.validate_application_packages(
                ROOT, candidate_relatives()
            )
        self.assertTrue(any("gateway skill body is not canonical" in issue for issue in issues))

    def test_gateway_frontmatter_is_fixed(self) -> None:
        actual = release_check._skill_frontmatter

        def changed(path: Path) -> dict[str, str]:
            fields = actual(path)
            if path == ROOT / release_check._GATEWAY_SKILL_PATH:
                return {**fields, "description": "Changed description"}
            return fields

        with mock.patch.object(release_check, "_skill_frontmatter", side_effect=changed):
            issues = release_check.validate_application_packages(ROOT, candidate_relatives())
        self.assertTrue(any("gateway skill frontmatter is not canonical" in issue for issue in issues))

    def test_alternate_skill_source_and_npm_dependencies_are_rejected(self) -> None:
        actual = release_check._strict_json
        for mutation, expected in (
            ({"skills": ["./alternate"]}, "must use only pi.skills"),
            ({"dependencies": {"example": "1.0.0"}}, "npm dependency sections"),
        ):
            with self.subTest(expected=expected):
                package = copy.deepcopy(actual(ROOT / "package.json"))
                package.update(mutation)

                def altered(path: Path, *, value: dict = package):
                    if path == ROOT / "package.json":
                        return value
                    return actual(path)

                with mock.patch.object(release_check, "_strict_json", side_effect=altered):
                    issues = release_check.validate_application_packages(
                        ROOT, candidate_relatives()
                    )
                self.assertTrue(any(expected in issue for issue in issues))

    def test_skill_frontmatter_is_flat_and_model_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "SKILL.md"
            skill.write_text(
                "---\nname: use-example\ndescription: Example skill\n"
                "disable-model-invocation: true\n---\n"
            )
            with self.assertRaisesRegex(
                release_check.CheckFailure, "requires only name and description"
            ):
                release_check._skill_frontmatter(skill)


if __name__ == "__main__":
    unittest.main()
