import unittest
from unittest import mock

from ipad_agent import doctor


class DoctorSystemBrowserDetectionTests(unittest.TestCase):
    def test_apps_probe_includes_system_apps(self):
        payload = {
            "result": {
                "apps": [
                    {"bundleIdentifier": "com.apple.mobilesafari", "name": "Safari"}
                ]
            }
        }
        with mock.patch.object(doctor, "_devicectl_payload", return_value=(0, payload, "")) as probe:
            code, apps, error = doctor._apps_probe("device-id")

        probe.assert_called_once_with(
            [
                "device",
                "info",
                "apps",
                "--device",
                "device-id",
                "--include-all-apps",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(apps, payload["result"]["apps"])
        self.assertEqual(error, "")

    def test_bundle_detection_remains_exact(self):
        apps = [
            {"bundleIdentifier": "com.apple.mobilesafari.preview"},
            {"bundleIdentifier": "COM.APPLE.MOBILESAFARI"},
        ]
        self.assertFalse(
            doctor._exact_bundle_installed(apps, "com.apple.mobilesafari")
        )
        apps.append({"bundleIdentifier": "com.apple.mobilesafari"})
        self.assertTrue(
            doctor._exact_bundle_installed(apps, "com.apple.mobilesafari")
        )


if __name__ == "__main__":
    unittest.main()
