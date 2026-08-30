import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_check", ROOT / "scripts" / "release_check.py"
)
assert SPEC is not None and SPEC.loader is not None
release_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_check)


class ReleaseSecurityAutomationTests(unittest.TestCase):
    def test_repository_release_candidate_passes(self):
        self.assertEqual([], release_check.check_release(ROOT))

    def test_generic_security_documentation_and_placeholders_do_not_match(self):
        text = """Release notes may discuss tokens, config.toml, logs, and WebDriverAgent.
A generic path such as /Users/example/project is documentation, not private state.
device_id = "00000000-0000000000000000"
team_id = "ABCDE12345"
secret = "placeholder-value"
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "guide.md"
            path.write_text(text, encoding="utf-8")
            self.assertEqual([], release_check.content_issues(path, "guide.md"))

    def test_private_identifiers_and_secret_like_fixtures_match(self):
        cases = {
            "private path": "build = '/Us" + "ers/alice/Library/private/output'",
            "username": 'user' + 'name = "ali' + 'ce.local"',
            "team": 'team_id = "Z9Y8' + 'X7W6V5"',
            "device": 'device_id = "00008030-' + '001C195E0E91802E"',
            "legacy device": 'udid = "5f4dcc3b5aa765d61d8327' + 'deb882cf992a93871d"',
            "token": 'access_token = "mF9xQ2vR7nL4' + 'pT8sK3dW6zY1"',
            "github token": "value = gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        }
        with tempfile.TemporaryDirectory() as temporary:
            for label, text in cases.items():
                with self.subTest(label=label):
                    path = Path(temporary) / f"{label}.txt"
                    path.write_text(text, encoding="utf-8")
                    self.assertTrue(release_check.content_issues(path, f"tests/fixtures/{path.name}"))

    def test_secret_scanning_covers_unknown_text_extensions_without_sha_false_positive(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "export.custom"
            path.write_text(
                "commit = " + "0123456789abcdef" * 2 + "01234567\n"
                + 'client_secret = "N7vQ2xL9pR4' + 'sT8wK6mZ3"\n',
                encoding="utf-8",
            )
            issues = release_check.content_issues(path, "export.custom")
            self.assertEqual(1, len(issues), issues)
            self.assertIn("secret-like", issues[0])

    def test_forbidden_release_paths_cover_local_and_generated_state(self):
        forbidden = (
            ".runtime/server.sock",
            "ipad_agent/__pycache__/api.pyc",
            "debug/session.log",
            "config.toml",
            "build/WebDriverAgentRunner.xctestrun",
            "node_modules/package/index.js",
            "logs/session.txt",
            "DerivedData/WDA/Build/App.app/Info.plist",
            "local/WebDriverAgentRunner.app/Info.plist",
        )
        for value in forbidden:
            with self.subTest(path=value):
                self.assertIsNotNone(release_check._forbidden_path_reason(value))
        self.assertIsNone(release_check._forbidden_path_reason("README.md"))
        self.assertIsNone(release_check._forbidden_path_reason("ipad_agent/runtime.py"))
        self.assertIsNone(release_check._forbidden_path_reason("config.example.toml"))

    def test_symlink_socket_and_unsafe_executable_are_rejected(self):
        with self._repository_copy() as copy:
            (copy / "unsafe-link").symlink_to("README.md")
            executable = copy / "tests" / "fixture.txt"
            executable.write_text("ordinary fixture", encoding="utf-8")
            executable.chmod(0o755)
            subprocess.run(
                ["git", "-C", str(copy), "add", "tests/fixture.txt"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            executable.chmod(0o644)  # The staged release mode must still be rejected.
            sock = socket.socket(socket.AF_UNIX)
            try:
                sock.bind(str(copy / "fixture.sock"))
                issues = release_check.check_release(copy)
            finally:
                sock.close()
            joined = "\n".join(issues)
            self.assertIn("symlink is not release-safe", joined)
            self.assertIn("socket is not release-safe", joined)
            self.assertIn("unsafe executable bit", joined)

    def test_unindexed_and_invalid_manifests_are_rejected(self):
        with self._repository_copy() as copy:
            rogue = copy / "addons" / "rogue" / "integration.json"
            rogue.parent.mkdir()
            shutil.copyfile(copy / "addons" / "brave" / "integration.json", rogue)
            issues = release_check.check_release(copy)
            self.assertIn("unindexed integration manifest", "\n".join(issues))
        with self._repository_copy() as copy:
            manifest = copy / "integrations" / "maps" / "integration.json"
            manifest.write_text('{"not": "a manifest"}', encoding="utf-8")
            issues = release_check.check_release(copy)
            self.assertTrue(any("missing required field" in issue for issue in issues), issues)

    def test_invalid_schema_keyword_is_rejected(self):
        with self._repository_copy() as copy:
            schema_path = copy / "schemas" / "integration-v1.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["unexpectedKeyword"] = True
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            issues = release_check.check_release(copy)
            self.assertIn("unsupported schema keyword", "\n".join(issues))

    def test_doctor_shape_accepts_action_required_and_matches_process_exit(self):
        report = {
            "schema": "ipad-agent.doctor/v1",
            "ready": False,
            "exit_code": 10,
            "checks": [{
                "id": "device.paired",
                "status": "action_required",
                "message": "Pair a device",
                "evidence": None,
                "human_action": "Trust This Computer.",
                "remediation": None,
            }],
            "next": ["device.paired"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "doctor.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            release_check.validate_doctor_report(path, ROOT, 10)
            with self.assertRaises(release_check.CheckFailure):
                release_check.validate_doctor_report(path, ROOT, 20)

    def test_current_doctor_v2_shape_and_state_are_validated(self):
        report = {
            "schema": "ipad-agent.doctor/v2",
            "state": "needs_agent_action",
            "ready": False,
            "exit_code": 20,
            "selected": {},
            "checks": [{
                "id": "host.python",
                "status": "fail",
                "message": "Python is unavailable",
                "stage": "host",
                "evidence": None,
                "human_action": None,
                "remediation": "Use Python 3.11 or newer.",
            }],
            "next": ["host.python"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "doctor.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            release_check.validate_doctor_report(path, ROOT, 20)
            report["state"] = "blocked"
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(release_check.CheckFailure):
                release_check.validate_doctor_report(path, ROOT, 20)

    def test_doctor_v2_validation_matches_capability_scoped_blockers(self):
        def check(identifier, status, stage):
            return {
                "id": identifier,
                "status": status,
                "message": identifier,
                "stage": stage,
                "evidence": None,
                "human_action": None,
                "remediation": None,
            }

        reports = [
            ({
                "schema": "ipad-agent.doctor/v2",
                "state": "needs_agent_action",
                "ready": False,
                "exit_code": 20,
                "selected": {},
                "checks": [
                    check("host.python", "fail", "host"),
                    check("airdrop.policy", "fail", "host"),
                ],
                "next": ["host.python"],
            }, 20),
            ({
                "schema": "ipad-agent.doctor/v2",
                "state": "ready",
                "ready": True,
                "exit_code": 0,
                "selected": {},
                "checks": [check("airdrop.policy", "fail", "host")],
                "next": [],
            }, 0),
            ({
                "schema": "ipad-agent.doctor/v2",
                "state": "action_required",
                "ready": False,
                "exit_code": 10,
                "selected": {},
                "checks": [
                    check("device.unlocked", "action_required", "device"),
                    check("wda.build", "fail", "wda"),
                ],
                "next": ["device.unlocked"],
            }, 10),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "doctor.json"
            for report, process_exit in reports:
                path.write_text(json.dumps(report), encoding="utf-8")
                release_check.validate_doctor_report(path, ROOT, process_exit)

            report, process_exit = reports[0]
            report = json.loads(json.dumps(report))
            report["next"] = ["host.python", "airdrop.policy"]
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(release_check.CheckFailure):
                release_check.validate_doctor_report(path, ROOT, process_exit)

    def test_ci_is_macos_repository_native_and_offline_by_default(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: macos-latest", workflow)
        self.assertIn('IPAD_AGENT_RUN_LIVE_TESTS: "0"', workflow)
        self.assertIn("python3 scripts/release_check.py", workflow)
        self.assertIn("from ipad_agent import ipadc, ipadpreview, ipadbooks, ipadfiles, ipadsettings, ipadclock, ipadappstore, ipadbrave, ipadsafari, ipadmaps", workflow)
        self.assertIn("python3 -m unittest discover", workflow)
        self.assertIn("python3 -m compileall", workflow)
        self.assertNotRegex(workflow, r"(?m)^\s*(?:run:\s*)?(?:pip|python3? -m pip) install\b")

    def _repository_copy(self):
        stack = tempfile.TemporaryDirectory()
        target = Path(stack.name) / "repo"
        shutil.copytree(
            ROOT,
            target,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        subprocess.run(
            ["git", "-C", str(target), "init", "-q"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        class RepositoryContext:
            def __enter__(self):
                return target

            def __exit__(self, exc_type, exc, traceback):
                stack.cleanup()

        return RepositoryContext()


if __name__ == "__main__":
    unittest.main()
