import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ipad_agent import airdrop, doctor, setup
from ipad_agent.config import Config


class AirDropMaintenanceReadinessTests(unittest.TestCase):
    def _fixed_helper_tree(self, root: Path) -> tuple[Path, Path, Path]:
        source = root / "AirDropShare.swift"
        script = root / "build.sh"
        helper = root / ".runtime" / "native" / "airdrop-share"
        helper.parent.mkdir(parents=True)
        source.write_text("source")
        script.write_text("build")
        helper.write_text("binary")
        helper.chmod(0o700)
        newer = max(source.stat().st_mtime_ns, script.stat().st_mtime_ns) + 1_000_000
        os.utime(helper, ns=(newer, newer))
        return source, script, helper

    def test_doctor_reports_only_logical_airdrop_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, script, helper = self._fixed_helper_tree(Path(temporary).resolve())
            config = Config(
                airdrop_allowed_roots=["/private/transfer-root"],
                airdrop_allowed_extensions=[".private-extension"],
                airdrop_max_bytes=987654,
            )
            checks = []
            with patch.object(airdrop, "HELPER_SOURCE", source), \
                 patch.object(airdrop, "HELPER_BUILD_SCRIPT", script), \
                 patch.object(airdrop, "HELPER_BINARY", helper), \
                 patch("ipad_agent.doctor._run", return_value=(0, "Swift version 6.0", "")):
                doctor._airdrop_checks(config, checks, xcode_ok=True)

        report = doctor.public_report(doctor._report(checks, {}))
        values = {item["id"]: item for item in report["checks"]}
        self.assertEqual("pass", values["host.swift"]["status"])
        self.assertEqual({"buildable": True}, values["host.swift"]["evidence"])
        self.assertEqual({"configured": True}, values["airdrop.policy"]["evidence"])
        self.assertEqual({"ready": True}, values["airdrop.helper"]["evidence"])
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("/private/transfer-root", rendered)
        self.assertNotIn(".private-extension", rendered)
        self.assertNotIn("987654", rendered)
        self.assertNotIn(str(helper), rendered)

    def test_unconfigured_policy_is_transfer_scoped_agent_work(self):
        checks = [
            doctor.Check("host.swift", "pass", "ready"),
            doctor.Check(
                "airdrop.policy", "fail", "not configured",
                remediation="Configure the policy explicitly.",
            ),
            doctor.Check("airdrop.helper", "pass", "ready"),
        ]
        rich = doctor._report(checks, {})
        self.assertTrue(rich["ready"])
        self.assertEqual("ready", rich["state"])
        self.assertEqual([], rich["next"])

        result = setup._setup_report(True, "host", [], [], rich, None)
        policy_action = next(
            item for item in result["actions"] if item.get("check") == "airdrop.policy"
        )
        self.assertEqual("agent_action", policy_action["kind"])
        self.assertTrue(result["ready"])
        self.assertEqual("ready", result["state"])

    def test_optional_transfer_work_does_not_override_a_human_device_gate(self):
        checks = [
            doctor.Check(
                "device.unlocked", "action_required", "locked", "device",
                human_action="Unlock the iPad yourself.",
            ),
            doctor.Check(
                "airdrop.policy", "fail", "not configured",
                remediation="Configure the policy explicitly.",
            ),
        ]
        rich = doctor._report(checks, {})
        result = setup._setup_report(True, "host", [], [], rich, None)
        self.assertEqual("action_required", result["state"])
        self.assertEqual(10, result["exit_code"])

    def test_dormant_wda_failures_do_not_block_core_readiness(self):
        checks = [
            doctor.Check("host.macos", "pass", "ready"),
            doctor.Check("host.python", "pass", "ready"),
            doctor.Check("host.xcode", "pass", "ready"),
            doctor.Check("host.devicectl", "pass", "ready"),
            doctor.Check("device.paired", "pass", "ready", "device"),
            doctor.Check("device.unlocked", "pass", "ready", "device"),
            doctor.Check("device.browser", "pass", "ready", "device"),
            doctor.Check("host.node", "fail", "optional WDA tool missing"),
            doctor.Check("automation.appium", "fail", "optional WDA tool missing"),
            doctor.Check("signing.identity", "action_required", "optional signing missing", "signing"),
            doctor.Check("device.developer_mode", "action_required", "optional developer mode off", "device"),
        ]
        report = doctor._report(checks, {})
        self.assertTrue(report["ready"])
        self.assertEqual("ready", report["state"])
        self.assertEqual([], report["next"])

    def test_blocked_wda_setup_operation_never_reports_ready(self):
        doctor_report = doctor._report(
            [doctor.Check("host.macos", "pass", "ready")], {}
        )
        result = setup._setup_report(
            True, "wda", [],
            [{"phase": "wda", "ok": False, "changed": False, "blocked_by": ["automation.appium"]}],
            doctor_report, None,
        )
        self.assertFalse(result["ready"])
        self.assertEqual("needs_agent_action", result["state"])
        self.assertEqual(20, result["exit_code"])

    def test_host_setup_plans_or_builds_only_the_owned_helper(self):
        report = {
            "checks": [
                {"id": "host.swift", "status": "pass"},
                {"id": "airdrop.policy", "status": "fail"},
                {"id": "airdrop.helper", "status": "fail"},
            ]
        }
        with patch("ipad_agent.setup.airdrop.build_helper") as build:
            planned = setup._maintain_airdrop_helper(report, apply=False)
            build.assert_not_called()
            applied = setup._maintain_airdrop_helper(report, apply=True)
            build.assert_called_once_with()

        self.assertEqual("build_project_owned_airdrop_helper", planned["planned"])
        self.assertFalse(planned["changed"])
        self.assertEqual("airdrop_helper", applied["component"])
        self.assertTrue(applied["changed"])
        self.assertNotIn("policy", applied)
        self.assertNotIn("roots", applied)
        self.assertNotIn("extensions", applied)
        self.assertNotIn("max_bytes", applied)

    def test_host_apply_integrates_helper_build_without_configuring_policy(self):
        before = {
            "schema": "ipad-agent.doctor/v2", "state": "ready", "ready": True,
            "exit_code": 0, "selected": {}, "next": [],
            "checks": [
                {"id": "host.swift", "status": "pass", "message": "buildable", "stage": "host", "evidence": {"buildable": True}, "human_action": None, "remediation": None},
                {"id": "airdrop.policy", "status": "fail", "message": "not configured", "stage": "host", "evidence": {"configured": False}, "human_action": None, "remediation": "Configure explicitly."},
                {"id": "airdrop.helper", "status": "fail", "message": "not ready", "stage": "host", "evidence": {"ready": False}, "human_action": None, "remediation": "Run host setup."},
            ],
        }
        after = {
            **before,
            "checks": [
                before["checks"][0], before["checks"][1],
                {**before["checks"][2], "status": "pass", "message": "ready", "evidence": {"ready": True}, "remediation": None},
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "config.toml"
            config_path.write_text("existing explicit config")
            with patch.object(setup, "DEFAULT_CONFIG_PATH", config_path), \
                 patch("ipad_agent.setup.run_doctor", side_effect=[before, before, after]), \
                 patch("ipad_agent.setup.bootstrap_automation", return_value={"ok": True, "changed": []}), \
                 patch("ipad_agent.setup.airdrop.build_helper") as build:
                result = setup.run_setup(apply=True, phase="host")

        build.assert_called_once_with()
        self.assertIn("airdrop_helper", result["changed"])
        self.assertEqual("ready", result["state"])
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn("allowed_roots", rendered)
        self.assertNotIn("allowed_extensions", rendered)
        self.assertNotIn("max_bytes", rendered)


if __name__ == "__main__":
    unittest.main()
