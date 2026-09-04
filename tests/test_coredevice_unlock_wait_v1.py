import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch, sentinel

from ipad_agent.transports import coredevice
from ipad_agent.coredevice import (
    IPadControlError,
    LaunchResult,
    _device_locked,
    _resolve_installed_app,
    _single_connected_ipad,
    dispatch_when_unlocked,
    open_ipad_when_unlocked,
    wait_for_ipad_unlocked,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class CoreDeviceUnlockWaitTests(unittest.TestCase):
    def setUp(self):
        identifiers = (
            "configured-device", "device-1", "exact-device", "private-device",
            "resolved-device", "selected-device",
        )
        self._candidate_patch = patch(
            "ipad_agent.coredevice._paired_physical_ipads",
            return_value=[(value, {value}) for value in identifiers],
        )
        self._candidate_patch.start()
        self.addCleanup(self._stop_candidate_patch)

    def _stop_candidate_patch(self):
        if self._candidate_patch is not None:
            self._candidate_patch.stop()
            self._candidate_patch = None

    def test_device_discovery_admits_only_paired_physical_ipads(self):
        self._stop_candidate_patch()
        devices = [
            {"identifier": "sim", "hardwareProperties": {"deviceType": "iPad", "reality": "simulator", "udid": "sim-udid"}, "connectionProperties": {"pairingState": "paired"}},
            {"identifier": "phone", "hardwareProperties": {"deviceType": "iPhone", "reality": "physical", "udid": "phone-udid"}, "connectionProperties": {"pairingState": "paired"}},
            {"identifier": "unpaired", "hardwareProperties": {"deviceType": "iPad", "reality": "physical", "udid": "unpaired-udid"}, "connectionProperties": {"pairingState": "unpaired"}},
            {"identifier": "ipad", "hardwareProperties": {"deviceType": "iPad", "reality": "physical", "udid": "ipad-udid"}, "connectionProperties": {"pairingState": "paired"}},
        ]

        def run(command, **_kwargs):
            output = Path(command[command.index("--json-output") + 1])
            output.write_text(__import__("json").dumps({"result": {"devices": devices}}))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(coredevice.subprocess, "run", side_effect=run):
            self.assertEqual([("ipad", {"ipad", "ipad-udid"})], coredevice._paired_physical_ipads(1.0))
            self.assertEqual(
                "ipad",
                coredevice._resolve_device(None, SimpleNamespace(device="ipad-udid"), 1.0),
            )
        with patch.object(coredevice, "_paired_physical_ipads", return_value=[]):
            with self.assertRaisesRegex(IPadControlError, "paired physical"):
                coredevice._resolve_device("sim", SimpleNamespace(device=None), 1.0)

    def test_public_wait_resolves_configured_device_without_dispatch(self):
        clock = _Clock()
        config = SimpleNamespace(device=" configured-device ")
        with patch(
            "ipad_agent.coredevice._device_locked", side_effect=[True, False]
        ) as locked, patch(
            "ipad_agent.coredevice._single_connected_ipad"
        ) as discover, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            state = wait_for_ipad_unlocked(
                config=config,
                wait_timeout=0.5,
                poll_interval=0.1,
                lock_check_timeout=0.2,
            )

        self.assertEqual("unlocked", state)
        self.assertEqual(
            [call("configured-device", 0.2), call("configured-device", 0.2)],
            locked.call_args_list,
        )
        self.assertEqual([0.1], clock.sleeps)
        discover.assert_not_called()

    def test_public_wait_discovers_once_and_reports_locked(self):
        clock = _Clock()
        config = SimpleNamespace(device=None)
        with patch(
            "ipad_agent.coredevice._single_connected_ipad", return_value="discovered-device"
        ) as discover, patch(
            "ipad_agent.coredevice._device_locked", return_value=True
        ) as locked, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            state = wait_for_ipad_unlocked(
                config=config, wait_timeout=0.2, poll_interval=0.1
            )

        self.assertEqual("locked", state)
        discover.assert_called_once_with(0.2)
        self.assertEqual(2, locked.call_count)

    def test_public_wait_retries_repeated_unknown_until_deadline(self):
        clock = _Clock()
        config = SimpleNamespace(device="device-1")
        with patch(
            "ipad_agent.coredevice._device_locked", return_value=None
        ) as locked, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            state = wait_for_ipad_unlocked(
                config=config,
                wait_timeout=0.2,
                poll_interval=0.1,
                lock_check_timeout=0.2,
            )

        self.assertEqual("unknown", state)
        self.assertEqual(
            [call("device-1", 0.2), call("device-1", 0.1)],
            locked.call_args_list,
        )
        self.assertEqual([0.1, 0.1], clock.sleeps)

    def test_lock_probe_uses_minimum_devicectl_timeout_but_keeps_caller_bound(self):
        def complete(command, **kwargs):
            output_path = command[command.index("--json-output") + 1]
            Path(output_path).write_text(
                '{"result": {"passcodeRequired": false}}'
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        for caller_timeout in (3.0, 0.2):
            with self.subTest(caller_timeout=caller_timeout), patch(
                "ipad_agent.coredevice.subprocess.run", side_effect=complete
            ) as run:
                locked = _device_locked("device-1", caller_timeout)

                self.assertFalse(locked)
                command = run.call_args.args[0]
                output_path = command[command.index("--json-output") + 1]
                run.assert_called_once_with(
                    [
                        "xcrun", "devicectl", "device", "info", "lockState",
                        "--device", "device-1", "--json-output", output_path,
                        "--quiet", "--timeout", "5",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=caller_timeout,
                )

    def test_discovery_failures_never_expose_raw_process_output(self):
        self._stop_candidate_patch()
        resolvers = (
            ("app", lambda: _resolve_installed_app("Notes", "private-device", 3.0)),
            ("device", lambda: _single_connected_ipad(3.0)),
        )
        for label, resolver in resolvers:
            for stream in ("stdout", "stderr"):
                secret = f"private-{label}-{stream}-diagnostic /private/path"
                completed = SimpleNamespace(
                    returncode=1,
                    stdout=secret if stream == "stdout" else "",
                    stderr=secret if stream == "stderr" else "",
                )
                with self.subTest(resolver=label, stream=stream), patch(
                    "ipad_agent.coredevice.subprocess.run", return_value=completed
                ):
                    with self.assertRaises(IPadControlError) as raised:
                        resolver()

                rendered = str(raised.exception)
                self.assertIn(f"CoreDevice {label} discovery failed", rendered)
                self.assertNotIn(secret, rendered)
                self.assertNotIn("/private/path", rendered)
                self.assertFalse(raised.exception.response_lost)
                self.assertFalse(raised.exception.dispatched)

    def test_preflight_dispatches_once_when_already_unlocked(self):
        dispatch = Mock(return_value="sent")
        with patch("ipad_agent.coredevice._device_locked", return_value=False) as locked, \
             patch("ipad_agent.coredevice.time.sleep") as sleep:
            result = dispatch_when_unlocked(" device-1 ", dispatch)

        self.assertEqual("dispatched", result.status)
        self.assertTrue(result.dispatched)
        self.assertEqual("sent", result.value)
        locked.assert_called_once_with("device-1", 5.0)
        dispatch.assert_called_once_with()
        sleep.assert_not_called()

    def test_default_preflight_allows_slow_probe_and_ten_second_unlock_window(self):
        clock = _Clock()
        dispatch = Mock(return_value="sent")
        probe_calls = []

        def delayed_probe(device_id, timeout):
            probe_calls.append(call(device_id, timeout))
            if len(probe_calls) == 1:
                if timeout <= 1.2:
                    clock.now += timeout
                    return None
                clock.now += 1.2
            return clock.now < 9.0

        with patch(
            "ipad_agent.coredevice._device_locked", side_effect=delayed_probe
        ), patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = dispatch_when_unlocked("device-1", dispatch)

        self.assertEqual("dispatched", result.status)
        self.assertEqual("sent", result.value)
        self.assertEqual(call("device-1", 5.0), probe_calls[0])
        self.assertGreaterEqual(clock.now, 9.0)
        self.assertLess(clock.now, 10.0)
        dispatch.assert_called_once_with()

    def test_locked_device_is_polled_and_dispatch_waits_for_unlock(self):
        clock = _Clock()
        dispatch = Mock(return_value={"accepted": True})
        with patch(
            "ipad_agent.coredevice._device_locked", side_effect=[True, True, False]
        ) as locked, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = dispatch_when_unlocked(
                "device-1", dispatch, wait_timeout=1.0, poll_interval=0.2
            )

        self.assertEqual("dispatched", result.status)
        self.assertEqual({"accepted": True}, result.value)
        self.assertEqual(3, locked.call_count)
        self.assertEqual([0.2, 0.2], clock.sleeps)
        dispatch.assert_called_once_with()

    def test_timeout_returns_locked_without_dispatch(self):
        clock = _Clock()
        dispatch = Mock()
        with patch("ipad_agent.coredevice._device_locked", return_value=True), patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = dispatch_when_unlocked(
                "device-1", dispatch, wait_timeout=0.2, poll_interval=0.1
            )

        self.assertEqual("locked", result.status)
        self.assertFalse(result.dispatched)
        self.assertIsNone(result.value)
        self.assertEqual([0.1, 0.1], clock.sleeps)
        dispatch.assert_not_called()

    def test_unknown_then_locked_returns_locked_at_deadline(self):
        clock = _Clock()
        dispatch = Mock()
        with patch(
            "ipad_agent.coredevice._device_locked", side_effect=[None, True]
        ) as locked, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = dispatch_when_unlocked(
                "device-1",
                dispatch,
                wait_timeout=0.2,
                poll_interval=0.1,
                lock_check_timeout=0.2,
            )

        self.assertEqual("locked", result.status)
        self.assertEqual(2, locked.call_count)
        self.assertEqual([0.1, 0.1], clock.sleeps)
        dispatch.assert_not_called()

    def test_unknown_then_unlocked_dispatches_once(self):
        clock = _Clock()
        dispatch = Mock(return_value="sent")
        with patch(
            "ipad_agent.coredevice._device_locked", side_effect=[None, False]
        ) as locked, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = dispatch_when_unlocked(
                "device-1",
                dispatch,
                wait_timeout=0.2,
                poll_interval=0.1,
                lock_check_timeout=0.2,
            )

        self.assertEqual("dispatched", result.status)
        self.assertEqual("sent", result.value)
        self.assertEqual(2, locked.call_count)
        self.assertEqual([0.1], clock.sleeps)
        dispatch.assert_called_once_with()

    def test_repeated_unknown_returns_unknown_without_dispatch(self):
        clock = _Clock()
        dispatch = Mock()
        with patch(
            "ipad_agent.coredevice._device_locked", return_value=None
        ) as locked, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = dispatch_when_unlocked(
                "device-1",
                dispatch,
                wait_timeout=0.2,
                poll_interval=0.1,
                lock_check_timeout=0.2,
            )

        self.assertEqual("unknown", result.status)
        self.assertEqual(2, locked.call_count)
        self.assertEqual([0.1, 0.1], clock.sleeps)
        dispatch.assert_not_called()

    def test_locked_observation_takes_precedence_over_later_unknown(self):
        clock = _Clock()
        dispatch = Mock()
        with patch(
            "ipad_agent.coredevice._device_locked", side_effect=[True, None]
        ) as locked, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = dispatch_when_unlocked(
                "device-1",
                dispatch,
                wait_timeout=0.2,
                poll_interval=0.1,
                lock_check_timeout=0.2,
            )

        self.assertEqual("locked", result.status)
        self.assertEqual(2, locked.call_count)
        self.assertEqual([0.1, 0.1], clock.sleeps)
        dispatch.assert_not_called()

    def test_dispatch_failure_is_propagated_without_retry(self):
        dispatch = Mock(side_effect=[RuntimeError("response lost"), "must not retry"])
        with patch("ipad_agent.coredevice._device_locked", return_value=False) as locked:
            with self.assertRaisesRegex(RuntimeError, "response lost"):
                dispatch_when_unlocked("device-1", dispatch)

        locked.assert_called_once()
        dispatch.assert_has_calls([call()])
        self.assertEqual(1, dispatch.call_count)

    def test_semantic_helper_resolves_exact_device_and_forwards_one_launch(self):
        config = SimpleNamespace(device="configured-device")
        launch = LaunchResult("com.example.app", "exact-device", 0.01, None, False)
        with patch(
            "ipad_agent.coredevice._device_locked", return_value=False
        ) as locked, patch(
            "ipad_agent.coredevice._single_connected_ipad"
        ) as discover, patch(
            "ipad_agent.coredevice.open_ipad", return_value=launch
        ) as open_ipad:
            result = open_ipad_when_unlocked(
                "com.example.app",
                device=" exact-device ",
                terminate=True,
                timeout=9.0,
                config=config,
                registry=sentinel.registry,
            )

        self.assertEqual("dispatched", result.status)
        self.assertIs(launch, result.value)
        locked.assert_called_once_with("exact-device", 5.0)
        discover.assert_not_called()
        open_ipad.assert_called_once_with(
            "com.example.app",
            url=None,
            device="exact-device",
            terminate=True,
            timeout=9.0,
            config=config,
            registry=sentinel.registry,
        )

    def test_semantic_helper_polls_configured_device_before_launch(self):
        clock = _Clock()
        config = SimpleNamespace(device=" configured-device ")
        launch = LaunchResult("com.example.app", "configured-device", 0.01, None, False)
        with patch(
            "ipad_agent.coredevice._device_locked", side_effect=[True, False]
        ) as locked, patch(
            "ipad_agent.coredevice._single_connected_ipad"
        ) as discover, patch(
            "ipad_agent.coredevice.open_ipad", return_value=launch
        ) as open_ipad, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = open_ipad_when_unlocked(
                "com.example.app",
                url="https://example.test/path",
                wait_timeout=0.5,
                poll_interval=0.1,
                lock_check_timeout=0.2,
                config=config,
                registry=sentinel.registry,
            )

        self.assertEqual("dispatched", result.status)
        self.assertEqual(2, locked.call_count)
        self.assertEqual([0.1], clock.sleeps)
        discover.assert_not_called()
        open_ipad.assert_called_once_with(
            "com.example.app",
            url="https://example.test/path",
            device="configured-device",
            terminate=False,
            timeout=15.0,
            config=config,
            registry=sentinel.registry,
        )

    def test_semantic_helper_discovers_once_then_reuses_device_for_launch(self):
        config = SimpleNamespace(device=None)
        launch = LaunchResult("com.example.app", "discovered-device", 0.01, None, False)
        with patch(
            "ipad_agent.coredevice._single_connected_ipad",
            return_value="discovered-device",
        ) as discover, patch(
            "ipad_agent.coredevice._device_locked", return_value=False
        ) as locked, patch(
            "ipad_agent.coredevice.open_ipad", return_value=launch
        ) as open_ipad:
            result = open_ipad_when_unlocked(
                "com.example.app",
                timeout=7.0,
                config=config,
                registry=sentinel.registry,
            )

        self.assertEqual("dispatched", result.status)
        self.assertIs(launch, result.value)
        discover.assert_called_once_with(7.0)
        locked.assert_called_once_with("discovered-device", 5.0)
        open_ipad.assert_called_once_with(
            "com.example.app",
            url=None,
            device="discovered-device",
            terminate=False,
            timeout=7.0,
            config=config,
            registry=sentinel.registry,
        )

    def test_semantic_helper_returns_unknown_without_launch(self):
        clock = _Clock()
        config = SimpleNamespace(device="device-1")
        with patch(
            "ipad_agent.coredevice._device_locked", return_value=None
        ), patch(
            "ipad_agent.coredevice.open_ipad"
        ) as open_ipad, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = open_ipad_when_unlocked(
                "com.example.app",
                wait_timeout=0.2,
                poll_interval=0.1,
                config=config,
                registry=sentinel.registry,
            )

        self.assertEqual("unknown", result.status)
        self.assertIsNone(result.value)
        open_ipad.assert_not_called()

    def test_semantic_helper_returns_locked_after_grace_without_launch(self):
        clock = _Clock()
        config = SimpleNamespace(device="device-1")
        with patch(
            "ipad_agent.coredevice._device_locked", return_value=True
        ), patch(
            "ipad_agent.coredevice.open_ipad"
        ) as open_ipad, patch(
            "ipad_agent.coredevice.time.monotonic", side_effect=clock.monotonic
        ), patch("ipad_agent.coredevice.time.sleep", side_effect=clock.sleep):
            result = open_ipad_when_unlocked(
                "com.example.app",
                wait_timeout=0.2,
                poll_interval=0.1,
                config=config,
                registry=sentinel.registry,
            )

        self.assertEqual("locked", result.status)
        self.assertIsNone(result.value)
        open_ipad.assert_not_called()

    def test_semantic_helper_never_retries_a_sent_launch(self):
        config = SimpleNamespace(device="device-1")
        error = IPadControlError("response lost", response_lost=True)
        with patch(
            "ipad_agent.coredevice._device_locked", return_value=False
        ), patch(
            "ipad_agent.coredevice.open_ipad",
            side_effect=[error, sentinel.must_not_retry],
        ) as open_ipad:
            with self.assertRaisesRegex(IPadControlError, "response lost"):
                open_ipad_when_unlocked(
                    "com.example.app",
                    config=config,
                    registry=sentinel.registry,
                )

        self.assertTrue(error.uncertain)
        self.assertEqual(1, open_ipad.call_count)


if __name__ == "__main__":
    unittest.main()
