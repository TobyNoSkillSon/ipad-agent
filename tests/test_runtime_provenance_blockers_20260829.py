from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from ipad_agent import doctor, wda
from ipad_agent.__main__ import main
from ipad_agent.config import Config
from ipad_agent.runtime import Runtime


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "runtime_provenance_release_check", ROOT / "scripts" / "release_check.py"
)
assert SPEC is not None and SPEC.loader is not None
release_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_check)


class RuntimeProvenanceBlockers20260829Tests(unittest.TestCase):
    def _selection(self):
        return wda.WDASelection(
            "device", "udid", "18.0", "ABCDE12345", "io.example.wda",
            "/driver/WDA.xcodeproj", "digest", "Xcode 16", "fingerprint",
        )

    def test_runtime_uses_only_current_strongly_validated_verified_artifact(self):
        selection = self._selection()
        config = Config(
            team_id=selection.team_id,
            wda_bundle_id=selection.bundle_id,
            xctestrun="/owned/Build/Products/WDA.xctestrun",
        )
        runtime = Runtime(config=config, registry=Mock())
        session = Mock()
        context = MagicMock()
        context.__enter__.return_value = session
        artifact = {"xctestrun": config.xctestrun}
        with patch("ipad_agent.wda._discover_ipad", return_value={
            "identifier": selection.device_identifier,
            "udid": selection.device_udid,
            "version": selection.platform_version,
        }), patch("ipad_agent.wda.make_selection", return_value=selection), \
             patch("ipad_agent.wda.artifact_directory", return_value=Path("/owned")), \
             patch("ipad_agent.wda.validate_artifact", return_value=artifact) as validate, \
             patch("ipad_agent.wda.verified", return_value=True) as verified, \
             patch("ipad_agent.wda.short_session", return_value=context) as short_session:
            self.assertIs(session, runtime.ensure_session())
        validate.assert_called_once_with(Path("/owned"), selection=selection)
        verified.assert_called_once_with(selection)
        xctest_config = short_session.call_args.args[0]
        self.assertEqual("/owned/Build/Products", xctest_config.bootstrap_path)

    def test_runtime_fails_closed_without_setup_owned_selection(self):
        runtime = Runtime(config=Config(), registry=Mock())
        with patch("ipad_agent.wda._discover_ipad", return_value={
            "identifier": "device", "udid": "udid", "version": "18.0",
        }), patch("ipad_agent.wda.make_selection") as make_selection:
            with self.assertRaisesRegex(wda.XCTestControlError, "setup-owned"):
                runtime.ensure_session()
        make_selection.assert_not_called()

    def test_artifact_validation_rejects_missing_metadata_and_receipt_blocks(self):
        complete = {
            "schema": "ipad-agent.wda-artifact/v1", "owner": "ipad-agent",
            "fingerprint": "fingerprint", "source_project": "/driver/WDA.xcodeproj",
            "source_digest": "digest", "driver_version": "12.8.2", "xcode": "Xcode 16",
            "device_identifier": "device", "device_udid": "udid", "platform_version": "18.0",
            "team_id": "ABCDE12345", "bundle_id": "io.example.wda",
            "xctestrun": "/owned/WDA.xctestrun", "runner_app": "/owned/Runner.app",
            "signature": {"team_id": "ABCDE12345"}, "product": {"architectures": ["arm64"]},
            "runtime": {"team_id": "ABCDE12345"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fingerprint"
            root.mkdir()
            receipt = root / wda.ARTIFACT_FILE
            with patch.object(wda, "DERIVED_DATA_ROOT", Path(temporary)), \
                 patch("ipad_agent.wda.require_runtime_path", side_effect=lambda value: Path(value)), \
                 patch("ipad_agent.wda.private_read_text", side_effect=lambda value: Path(value).read_text()):
                for missing in ("source_project", "signature", "product", "runtime"):
                    with self.subTest(missing=missing):
                        payload = dict(complete)
                        payload.pop(missing)
                        receipt.write_text(json.dumps(payload))
                        with self.assertRaisesRegex(wda.XCTestControlError, "omits required metadata"):
                            wda.validate_artifact(root)

    def test_certificate_subject_ties_exact_identity_to_team(self):
        sha1 = "A" * 40
        listing = f"SHA-1 hash: {sha1}\n-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----\n"

        def run(command, **_kwargs):
            if command[:3] == ["security", "find-certificate", "-a"]:
                return 0, listing, ""
            if command[:2] == ["openssl", "x509"]:
                return 0, "subject=CN=Developer,OU=ABCDE12345,O=Example", ""
            return 127, "", "unexpected"

        with patch("ipad_agent.doctor._run", side_effect=run):
            self.assertEqual(
                {sha1: {"ABCDE12345": ["certificate_subject"]}},
                doctor._certificate_identity_teams({sha1}),
            )

    def test_runner_signature_requires_leaf_certificate_in_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "Runner.app"
            app.mkdir()
            (app / "embedded.mobileprovision").write_bytes(b"profile")
            provision = {
                "TeamIdentifier": ["ABCDE12345"],
                "ExpirationDate": datetime.now(timezone.utc) + timedelta(days=1),
                "DeveloperCertificates": [b"authorized certificate"],
                "Entitlements": {"application-identifier": "ABCDE12345.io.example.wda"},
            }

            def run(command, **_kwargs):
                if command[1:3] == ["--verify", "--strict"]:
                    return 0, "", ""
                if command[1:3] == ["-d", "--verbose=4"]:
                    return 0, "", "Identifier=io.example.wda.xctrunner\nTeamIdentifier=ABCDE12345\nAuthority=Apple Development"
                if command[:3] == ["security", "cms", "-D"]:
                    return 0, __import__("plistlib").dumps(provision).decode(), ""
                extraction = next((item for item in command if str(item).startswith("--extract-certificates=")), None)
                if extraction is not None:
                    prefix = Path(str(extraction).split("=", 1)[1])
                    Path(str(prefix) + "0").write_bytes(b"different certificate")
                    return 0, "", ""
                return 127, "", "unexpected"

            with patch("ipad_agent.wda._run_process", side_effect=run):
                with self.assertRaisesRegex(wda.XCTestControlError, "not authorized"):
                    wda._signature_metadata(app)

    def test_expired_profile_does_not_link_identity_to_team(self):
        sha1 = "A" * 40
        certificate = b"certificate"
        sha1 = __import__("hashlib").sha1(certificate).hexdigest().upper()
        profile = {
            "ExpirationDate": datetime.now(timezone.utc) - timedelta(seconds=1),
            "DeveloperCertificates": [certificate], "TeamIdentifier": ["ABCDE12345"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            profiles = home / "Library" / "MobileDevice" / "Provisioning Profiles"
            profiles.mkdir(parents=True)
            path = profiles / "expired.mobileprovision"
            path.write_text("fixture")
            with patch("ipad_agent.doctor.Path.home", return_value=home), \
                 patch("ipad_agent.doctor._run", return_value=(0, __import__("plistlib").dumps(profile).decode(), "")):
                self.assertEqual({}, doctor._provisioning_identity_teams({sha1}))

    def test_last_resort_doctor_report_validates_v2_schema(self):
        output = io.StringIO()
        with patch("ipad_agent.__main__.run_doctor", side_effect=RuntimeError("boom")), \
             patch("sys.stdout", output):
            code = main(["doctor", "--json"])
        report = json.loads(output.getvalue())
        schema = json.loads((ROOT / "schemas" / "doctor-v2.json").read_text())
        release_check.validate_schema(report, schema, name="last-resort doctor")
        self.assertEqual(20, code)
        self.assertEqual("needs_agent_action", report["state"])


if __name__ == "__main__":
    unittest.main()
