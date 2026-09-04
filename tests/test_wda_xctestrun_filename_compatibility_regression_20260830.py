import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ipad_agent import wda


class WDAXctestrunFilenameCompatibilityRegression20260830Tests(unittest.TestCase):
    def _selection(self) -> wda.WDASelection:
        return wda.WDASelection(
            "device", "test-device-udid", "26.6.1", "ABCDE12345",
            "com.example.ipadagent.wda", "/driver/WebDriverAgent.xcodeproj",
            "source-digest", "Xcode 26.6 | Build version 17F113", "fingerprint",
        )

    @staticmethod
    def _private_mkdir(path):
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.chmod(0o700)
        return target

    @staticmethod
    def _private_write_bytes(path, data):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o600)
        return target

    def _artifact(self, source: Path, digest: str) -> dict:
        selection = self._selection()
        return {
            "fingerprint": selection.fingerprint,
            "device_identifier": selection.device_identifier,
            "device_udid": selection.device_udid,
            "platform_version": selection.platform_version,
            "team_id": selection.team_id,
            "bundle_id": selection.bundle_id,
            "source_project": selection.source_project,
            "source_digest": selection.source_digest,
            "xcode": selection.xcode,
            "xctestrun": str(source),
            "product": {"xctestrun_sha256": digest},
            "runtime": {"xctestrun": str(source)},
        }

    def _patch_filesystem(self, root: Path):
        return (
            patch("ipad_agent.wda.artifact_directory", return_value=root),
            patch("ipad_agent.wda.require_runtime_path", side_effect=lambda value: Path(value)),
            patch("ipad_agent.wda.private_write_bytes", side_effect=self._private_write_bytes),
        )

    def test_alias_is_hash_identical_and_stays_beside_signed_products(self):
        selection = self._selection()
        content = b"exact setup-owned xctestrun bytes"
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / selection.fingerprint
            products = root / "Build" / "Products"
            products.mkdir(parents=True)
            source = products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(content)
            artifact = self._artifact(source, digest)
            receipt_before = json.dumps(artifact, sort_keys=True)
            patches = self._patch_filesystem(root)
            with patches[0], patches[1], patches[2]:
                bootstrap = wda._materialize_xctestrun_alias(
                    selection, artifact, "26.5"
                )

            self.assertEqual(products, bootstrap)
            self.assertFalse((root / "RuntimeBootstrap").exists())
            self.assertEqual(receipt_before, json.dumps(artifact, sort_keys=True))
            self.assertEqual(content, source.read_bytes())
            aliases = [path for path in products.glob("test-device-udid_*.xctestrun")]
            self.assertEqual([products / "test-device-udid_26.5.xctestrun"], aliases)
            self.assertFalse(aliases[0].is_symlink())
            self.assertEqual(content, aliases[0].read_bytes())
            self.assertEqual(0o700, (root / "Build").stat().st_mode & 0o777)
            self.assertEqual(0o700, products.stat().st_mode & 0o777)

    def test_alias_repairs_owner_owned_xcode_directory_modes_only(self):
        selection = self._selection()
        content = b"canonical receipt-owned bytes"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / selection.fingerprint
            build = root / "Build"
            products = build / "Products"
            products.mkdir(parents=True)
            root.chmod(0o700)
            build.chmod(0o755)
            products.chmod(0o755)
            source = products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(content)
            source_mode = source.stat().st_mode & 0o777
            artifact = self._artifact(source, hashlib.sha256(content).hexdigest())
            receipt_before = json.dumps(artifact, sort_keys=True)
            patches = self._patch_filesystem(root)
            with patches[0], patches[1], patches[2]:
                wda._materialize_xctestrun_alias(selection, artifact, "26.5")

            self.assertEqual(0o700, build.stat().st_mode & 0o777)
            self.assertEqual(0o700, products.stat().st_mode & 0o777)
            self.assertEqual(0o700, root.stat().st_mode & 0o777)
            self.assertEqual(source_mode, source.stat().st_mode & 0o777)
            self.assertEqual(content, source.read_bytes())
            self.assertEqual(receipt_before, json.dumps(artifact, sort_keys=True))

    def test_alias_rejects_symlinked_products_without_chmodding_target(self):
        selection = self._selection()
        content = b"canonical"
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / selection.fingerprint
            build = root / "Build"
            outside_products = base / "outside-products"
            build.mkdir(parents=True)
            outside_products.mkdir()
            build.chmod(0o755)
            outside_products.chmod(0o755)
            (build / "Products").symlink_to(outside_products, target_is_directory=True)
            source = build / "Products" / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(content)
            artifact = self._artifact(source, hashlib.sha256(content).hexdigest())
            patches = self._patch_filesystem(root)
            with patches[0], patches[1], patches[2]:
                with self.assertRaisesRegex(
                    wda.XCTestControlError, "Build/Products ownership is unsafe"
                ) as raised:
                    wda._materialize_xctestrun_alias(selection, artifact, "26.5")

            self.assertEqual("wda_setup_required", raised.exception.code)
            self.assertEqual(0o755, build.stat().st_mode & 0o777)
            self.assertEqual(0o755, outside_products.stat().st_mode & 0o777)
            self.assertFalse(
                (outside_products / "test-device-udid_26.5.xctestrun").exists()
            )

    def test_alias_rejects_non_owned_products_before_mode_repair(self):
        selection = self._selection()
        content = b"canonical"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / selection.fingerprint
            build = root / "Build"
            products = build / "Products"
            products.mkdir(parents=True)
            build.chmod(0o755)
            products.chmod(0o755)
            source = products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(content)
            artifact = self._artifact(source, hashlib.sha256(content).hexdigest())
            patches = self._patch_filesystem(root)
            with patches[0], patches[1], patches[2], \
                 patch("ipad_agent.wda.os.geteuid", return_value=os.geteuid() + 1):
                with self.assertRaisesRegex(
                    wda.XCTestControlError, "not owned by the current user"
                ) as raised:
                    wda._materialize_xctestrun_alias(selection, artifact, "26.5")

            self.assertEqual("wda_setup_required", raised.exception.code)
            self.assertEqual(0o755, build.stat().st_mode & 0o777)
            self.assertEqual(0o755, products.stat().st_mode & 0o777)
            self.assertFalse((products / "test-device-udid_26.5.xctestrun").exists())

    def test_alias_rejects_products_outside_fingerprint_without_chmod(self):
        selection = self._selection()
        content = b"canonical"
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / selection.fingerprint
            (root / "Build" / "Products").mkdir(parents=True)
            outside_products = base / "outside" / "Products"
            outside_products.mkdir(parents=True)
            outside_products.chmod(0o755)
            source = outside_products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(content)
            artifact = self._artifact(source, hashlib.sha256(content).hexdigest())
            patches = self._patch_filesystem(root)
            with patches[0], patches[1], patches[2], \
                 patch(
                     "ipad_agent.wda._xctestrun_products",
                     return_value=(outside_products, source, content),
                 ):
                with self.assertRaisesRegex(
                    wda.XCTestControlError, "escapes the fingerprinted artifact"
                ) as raised:
                    wda._materialize_xctestrun_alias(selection, artifact, "26.5")

            self.assertEqual("wda_setup_required", raised.exception.code)
            self.assertEqual(0o755, outside_products.stat().st_mode & 0o777)
            self.assertFalse(
                (outside_products / "test-device-udid_26.5.xctestrun").exists()
            )

    def test_owned_products_config_is_kept_and_runtime_version_is_sdk_capped(self):
        selection = self._selection()
        content = b"exact setup-owned xctestrun bytes"
        with tempfile.TemporaryDirectory() as temporary:
            derived = Path(temporary)
            root = derived / selection.fingerprint
            products = root / "Build" / "Products"
            products.mkdir(parents=True)
            source = products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(content)
            artifact = self._artifact(source, hashlib.sha256(content).hexdigest())
            config = wda.XCTestConfig(
                selection.device_udid, selection.platform_version, selection.team_id,
                str(products), selection.bundle_id,
            )
            patches = self._patch_filesystem(root)
            with patch.object(wda, "DERIVED_DATA_ROOT", derived), \
                 patch("ipad_agent.wda.validate_artifact", return_value=artifact), \
                 patch("ipad_agent.wda._discover_iphoneos_sdk_version", return_value="26.5"), \
                 patches[0], patches[1], patches[2]:
                compatible = wda._config_with_runtime_compatibility(config)

            self.assertEqual(str(products), compatible.bootstrap_path)
            self.assertEqual("26.5", compatible.platform_version)
            self.assertEqual("26.6.1", config.platform_version)
            self.assertEqual("26.6.1", artifact["platform_version"])
            self.assertEqual(
                content,
                (products / "test-device-udid_26.5.xctestrun").read_bytes(),
            )

    def test_short_session_uses_sdk_cap_products_path_and_no_always_on_xcode_log(self):
        selection = self._selection()
        content = b"exact setup-owned xctestrun bytes"
        with tempfile.TemporaryDirectory() as temporary:
            derived = Path(temporary)
            root = derived / selection.fingerprint
            products = root / "Build" / "Products"
            products.mkdir(parents=True)
            source = products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(content)
            artifact = self._artifact(source, hashlib.sha256(content).hexdigest())
            config = wda.XCTestConfig(
                selection.device_udid, selection.platform_version, selection.team_id,
                str(products), selection.bundle_id,
            )
            session_requests = []

            def http_json(method, url, payload, timeout):
                if method == "POST" and url.endswith("/session"):
                    session_requests.append(payload)
                    return {"value": {"sessionId": "session-1"}}
                if method == "POST" and url.endswith("/appium/settings"):
                    return {"value": None}
                if method == "DELETE":
                    return {"value": None}
                raise AssertionError((method, url, payload))

            patches = self._patch_filesystem(root)
            with patch.object(wda, "DERIVED_DATA_ROOT", derived), \
                 patch("ipad_agent.wda.validate_artifact", return_value=artifact) as validate, \
                 patch("ipad_agent.wda._discover_iphoneos_sdk_version", return_value="26.5"), \
                 patch("ipad_agent.wda._discover_ipad", return_value={"udid": selection.device_udid}), \
                 patch("ipad_agent.wda.ensure_appium_server"), \
                 patch("ipad_agent.wda._http_json", side_effect=http_json), \
                 patch("ipad_agent.wda._prove_appium_endpoint", return_value=(1234, "nonce", "start", False)), \
                 patch("ipad_agent.wda._capture_owned_wda_descendants", return_value=[]), \
                 patch("ipad_agent.wda._terminate_wda_xcodebuild", return_value={
                     "complete": True, "captured_pids": [], "remaining_pids": [],
                 }), patches[0], patches[1], patches[2]:
                with wda.short_session(config):
                    pass

            validate.assert_called_once_with(root)
            capabilities = session_requests[0]["capabilities"]["alwaysMatch"]
            self.assertEqual("26.5", capabilities["appium:platformVersion"])
            self.assertEqual(str(products), capabilities["appium:bootstrapPath"])
            self.assertNotIn("appium:showXcodeLog", capabilities)
            self.assertEqual(content, source.read_bytes())

    def test_sdk_discovery_uses_xcrun_structure_and_rejects_bad_output(self):
        with patch("ipad_agent.wda._run_process", return_value=(0, "26.5", "")) as run:
            self.assertEqual("26.5", wda._discover_iphoneos_sdk_version(timeout=7.0))
        run.assert_called_once_with(
            ["xcrun", "--sdk", "iphoneos", "--show-sdk-version"], timeout=7.0
        )

        for invalid in ("", "26", "26.5 beta", "026.5", "26..5"):
            with self.subTest(invalid=invalid), \
                 patch("ipad_agent.wda._run_process", return_value=(0, invalid, "")):
                with self.assertRaisesRegex(wda.XCTestControlError, "invalid platform version") as raised:
                    wda._discover_iphoneos_sdk_version()
                self.assertEqual("wda_sdk_invalid", raised.exception.code)

    def test_runtime_version_fails_closed_for_incompatible_major_family(self):
        with self.assertRaisesRegex(wda.XCTestControlError, "incompatible major families") as raised:
            wda._runtime_platform_version("26.6.1", "25.5")
        self.assertEqual("wda_sdk_incompatible", raised.exception.code)

    def test_alias_rejects_xctestrun_outside_exact_products_directory(self):
        selection = self._selection()
        content = b"owned bytes"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / selection.fingerprint
            source = root / "Elsewhere" / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.parent.mkdir(parents=True)
            source.write_bytes(content)
            artifact = self._artifact(source, hashlib.sha256(content).hexdigest())
            patches = self._patch_filesystem(root)
            with patches[0], patches[1], patches[2]:
                with self.assertRaisesRegex(wda.XCTestControlError, "exact setup-owned"):
                    wda._materialize_xctestrun_alias(selection, artifact, "26.5")
            self.assertFalse((root / "Build").exists())

    def test_alias_rejects_hash_mismatch_before_materializing(self):
        selection = self._selection()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / selection.fingerprint
            products = root / "Build" / "Products"
            products.mkdir(parents=True)
            source = products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(b"changed bytes")
            artifact = self._artifact(source, "0" * 64)
            patches = self._patch_filesystem(root)
            with patches[0], patches[1], patches[2]:
                with self.assertRaisesRegex(wda.XCTestControlError, "hash mismatch"):
                    wda._materialize_xctestrun_alias(selection, artifact, "26.5")
            self.assertFalse((products / "test-device-udid_26.5.xctestrun").exists())

    def test_rebuild_cleans_generated_alias_and_selects_only_canonical_product(self):
        selection = self._selection()
        content = b"canonical"
        with tempfile.TemporaryDirectory() as temporary:
            derived = Path(temporary) / selection.fingerprint
            products = derived / "Build" / "Products"
            products.mkdir(parents=True)
            source = products / "WebDriverAgentRunner_iphoneos26.5-arm64.xctestrun"
            source.write_bytes(content)
            alias = products / "test-device-udid_26.5.xctestrun"
            alias.write_bytes(b"Appium-mutated")
            foreign = products / "another-device_26.5.xctestrun"
            foreign.write_bytes(b"foreign")
            app = products / "Debug-iphoneos" / "WebDriverAgentRunner-Runner.app"
            app.mkdir(parents=True)
            product = {"xctestrun_sha256": hashlib.sha256(content).hexdigest()}
            artifact = self._artifact(source, product["xctestrun_sha256"])
            signature = {
                "team_id": selection.team_id,
                "bundle_id": selection.bundle_id + ".xctrunner",
            }
            with patch("ipad_agent.wda.artifact_directory", return_value=derived), \
                 patch("ipad_agent.wda.require_runtime_path", side_effect=lambda value: Path(value)), \
                 patch("ipad_agent.wda.private_mkdir", side_effect=self._private_mkdir), \
                 patch("ipad_agent.wda._run_process", return_value=(0, "", "")), \
                 patch("ipad_agent.wda._signature_metadata", return_value=signature), \
                 patch("ipad_agent.wda._product_metadata", return_value=product), \
                 patch("ipad_agent.wda.private_write_text"), \
                 patch("ipad_agent.wda.validate_artifact", side_effect=[
                     wda.XCTestControlError("rebuild"), artifact,
                 ]):
                result = wda.build_for_testing(selection, apply=True)

            self.assertTrue(result["changed"])
            self.assertFalse(alias.exists())
            self.assertTrue(foreign.exists())
            self.assertEqual(str(source), result["artifact"]["xctestrun"])


if __name__ == "__main__":
    unittest.main()
