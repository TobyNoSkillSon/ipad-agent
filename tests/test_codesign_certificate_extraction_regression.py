import hashlib
import plistlib
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ipad_agent import wda


class CodesignExtractionRegressionTests(unittest.TestCase):
    def test_extract_certificates_prefix_is_attached_to_option(self):
        leaf_bytes = b"test leaf certificate"
        profile = {
            "TeamIdentifier": ["TEAM123"],
            "ExpirationDate": datetime(2099, 1, 1, tzinfo=timezone.utc),
            "DeveloperCertificates": [leaf_bytes],
            "Entitlements": {"application-identifier": "TEAM123.io.example.wda"},
            "UUID": "EXAMPLE",
            "Name": "Test profile",
        }
        profile_xml = plistlib.dumps(profile, fmt=plistlib.FMT_XML).decode()
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "Runner.app"
            app.mkdir()
            (app / "embedded.mobileprovision").write_bytes(b"profile")
            observed = []

            def fake_run(argv, timeout):
                observed.append(list(argv))
                if argv[:2] == ["codesign", "--verify"]:
                    return 0, "", ""
                if argv[:2] == ["codesign", "-d"] and any(str(item).startswith("--extract-certificates=") for item in argv):
                    option = next(str(item) for item in argv if str(item).startswith("--extract-certificates="))
                    Path(option.split("=", 1)[1] + "0").write_bytes(leaf_bytes)
                    return 0, "", ""
                if argv[:2] == ["codesign", "-d"]:
                    return 0, "", "Identifier=io.example.wda.xctrunner\nTeamIdentifier=TEAM123\nAuthority=Apple Development"
                if argv[:3] == ["security", "cms", "-D"]:
                    return 0, profile_xml, ""
                raise AssertionError(argv)

            with patch("ipad_agent.wda._run_process", side_effect=fake_run):
                result = wda._signature_metadata(app)
            self.assertEqual(hashlib.sha1(leaf_bytes).hexdigest().upper(), result["certificate_sha1"])
            extraction = [argv for argv in observed if any("extract-certificates" in str(item) for item in argv)]
            self.assertEqual(1, len(extraction))
            self.assertTrue(any(str(item).startswith("--extract-certificates=") for item in extraction[0]))
            self.assertEqual(4, len(extraction[0]))


if __name__ == "__main__":
    unittest.main()
