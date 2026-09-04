from decimal import Decimal
import importlib
import sys
import unittest
from unittest.mock import Mock, patch

import ipad_agent
from ipad_agent import runtime as runtime_module
from ipad_agent import observer


PRIVATE_PATH = "/project/.runtime/artifacts/ipad-latest.png"


class FakeRuntime:
    def __init__(self, events, *, screenshot_error=None, teardown_error=None, heat_error=None):
        self.events = events
        self.screenshot_error = screenshot_error
        self.teardown_error = teardown_error
        self.heat_error = heat_error
        self.screenshot_calls = 0
        self.teardown_calls = 0

    def ensure_session(self):
        self.events.append("heat")
        if self.heat_error is not None:
            raise self.heat_error
        return object()

    def screenshot(self):
        self.screenshot_calls += 1
        self.events.append("screenshot")
        if self.screenshot_error is not None:
            raise self.screenshot_error
        return PRIVATE_PATH

    def teardown(self):
        self.teardown_calls += 1
        self.events.append("teardown")
        if self.teardown_error is not None:
            raise self.teardown_error


class ObserverTests(unittest.TestCase):
    def test_import_does_not_construct_runtime(self):
        original = sys.modules["ipad_agent.observer"]
        try:
            sys.modules.pop("ipad_agent.observer")
            with patch.object(runtime_module, "Runtime") as runtime:
                imported = importlib.import_module("ipad_agent.observer")
            runtime.assert_not_called()
            self.assertTrue(callable(imported.screenshot_after))
        finally:
            sys.modules["ipad_agent.observer"] = original
            ipad_agent.observer = original

    def test_orders_one_action_and_one_capture_between_heat_and_teardown(self):
        events = []
        runtime = FakeRuntime(events)
        action_result = {"ok": False, "uncertain": True}
        action_calls = 0

        def action():
            nonlocal action_calls
            action_calls += 1
            events.append("action")
            return action_result

        def sleep(seconds):
            events.append(("sleep", seconds))

        with patch.object(observer, "Runtime", return_value=runtime) as runtime_factory, \
             patch.object(observer.time, "sleep", side_effect=sleep) as sleeper:
            result = observer.screenshot_after(action, settle_seconds=1.75)

        runtime_factory.assert_called_once_with()
        sleeper.assert_called_once_with(1.75)
        self.assertEqual(
            ["heat", "action", ("sleep", 1.75), "screenshot", "teardown"],
            events,
        )
        self.assertEqual(1, action_calls)
        self.assertEqual(1, runtime.screenshot_calls)
        self.assertEqual(1, runtime.teardown_calls)
        self.assertIs(result.action_result, action_result)
        self.assertEqual(PRIVATE_PATH, result.screenshot_path)
        self.assertEqual(1.75, result.settle_seconds)
        self.assertEqual("returned", result.action_status)
        self.assertEqual("captured", result.capture_status)
        self.assertEqual("complete", result.teardown_status)
        self.assertEqual((), result.failures)
        with self.assertRaises(AttributeError):
            result.capture_status = "changed"

    def test_default_settle_seconds_is_five(self):
        events = []
        runtime = FakeRuntime(events)

        def action():
            events.append("action")

        with patch.object(observer, "Runtime", return_value=runtime), \
             patch.object(observer.time, "sleep", side_effect=lambda seconds: events.append(("sleep", seconds))) as sleeper:
            result = observer.screenshot_after(action)

        sleeper.assert_called_once_with(5.0)
        self.assertEqual(5.0, result.settle_seconds)
        self.assertEqual(
            ["heat", "action", ("sleep", 5.0), "screenshot", "teardown"],
            events,
        )
        self.assertEqual(PRIVATE_PATH, result.screenshot_path)
        self.assertEqual(1, runtime.screenshot_calls)
        self.assertEqual(1, runtime.teardown_calls)

    def test_validation_precedes_runtime_construction(self):
        invalid_actions = [None, 42, lambda required: required]
        invalid_settle = [True, False, "1.5", None, 1 + 0j, float("nan"), float("inf"), -float("inf"), 0.249, 10.001]

        with patch.object(observer, "Runtime") as runtime:
            for action in invalid_actions:
                with self.subTest(action=action), self.assertRaises(TypeError):
                    observer.screenshot_after(action)
            for seconds in invalid_settle:
                expected = TypeError if isinstance(seconds, (bool, str, complex)) or seconds is None else ValueError
                with self.subTest(settle_seconds=seconds), self.assertRaises(expected):
                    observer.screenshot_after(lambda: None, settle_seconds=seconds)
        runtime.assert_not_called()

    def test_settle_boundaries_are_accepted(self):
        observed = []
        for seconds in (Decimal("0.25"), 10.0):
            events = []
            runtime = FakeRuntime(events)
            with patch.object(observer, "Runtime", return_value=runtime), \
                 patch.object(observer.time, "sleep") as sleeper:
                result = observer.screenshot_after(lambda: None, settle_seconds=seconds)
            sleeper.assert_called_once_with(float(seconds))
            observed.append(result.settle_seconds)
        self.assertEqual([0.25, 10.0], observed)

    def test_action_exception_is_redacted_preserves_uncertainty_and_cleans_up(self):
        class ActionLost(RuntimeError):
            uncertain = True
            dispatched = True

        events = []
        runtime = FakeRuntime(events)
        action_calls = 0

        def action():
            nonlocal action_calls
            action_calls += 1
            events.append("action")
            raise ActionLost("private device output must not escape")

        with patch.object(observer, "Runtime", return_value=runtime), \
             patch.object(observer.time, "sleep") as sleeper:
            result = observer.screenshot_after(action)

        self.assertEqual(["heat", "action", "teardown"], events)
        self.assertEqual(1, action_calls)
        self.assertEqual(0, runtime.screenshot_calls)
        self.assertEqual(1, runtime.teardown_calls)
        sleeper.assert_not_called()
        self.assertEqual("raised", result.action_status)
        self.assertEqual("not_attempted", result.capture_status)
        self.assertEqual("complete", result.teardown_status)
        self.assertEqual("action", result.failures[0].stage)
        self.assertEqual("ActionLost", result.failures[0].error_type)
        self.assertTrue(result.failures[0].uncertain)
        self.assertTrue(result.failures[0].dispatched)
        self.assertNotIn("private device output", repr(result))

    def test_screenshot_failure_is_not_retried_and_tears_down(self):
        events = []
        runtime = FakeRuntime(events, screenshot_error=RuntimeError("private screenshot failure"))
        action_result = {"ok": True}

        def action():
            events.append("action")
            return action_result

        with patch.object(observer, "Runtime", return_value=runtime), \
             patch.object(observer.time, "sleep", side_effect=lambda seconds: events.append("sleep")):
            result = observer.screenshot_after(action)

        self.assertEqual(["heat", "action", "sleep", "screenshot", "teardown"], events)
        self.assertEqual(1, runtime.screenshot_calls)
        self.assertEqual(1, runtime.teardown_calls)
        self.assertIs(result.action_result, action_result)
        self.assertIsNone(result.screenshot_path)
        self.assertEqual("failed", result.capture_status)
        self.assertEqual("complete", result.teardown_status)
        self.assertEqual(["capture"], [failure.stage for failure in result.failures])
        self.assertNotIn("private screenshot failure", repr(result))

    def test_teardown_failure_is_visible_without_replaying_action_or_capture(self):
        events = []
        runtime = FakeRuntime(events, teardown_error=RuntimeError("private teardown detail"))
        action_calls = 0

        def action():
            nonlocal action_calls
            action_calls += 1
            events.append("action")
            return {"ok": True}

        with patch.object(observer, "Runtime", return_value=runtime), \
             patch.object(observer.time, "sleep", side_effect=lambda seconds: events.append("sleep")):
            result = observer.screenshot_after(action)

        self.assertEqual(["heat", "action", "sleep", "screenshot", "teardown"], events)
        self.assertEqual(1, action_calls)
        self.assertEqual(1, runtime.screenshot_calls)
        self.assertEqual(1, runtime.teardown_calls)
        self.assertEqual("captured", result.capture_status)
        self.assertEqual(PRIVATE_PATH, result.screenshot_path)
        self.assertEqual("failed", result.teardown_status)
        self.assertEqual(["teardown"], [failure.stage for failure in result.failures])
        self.assertNotIn("private teardown detail", repr(result))

    def test_capture_and_teardown_failures_are_both_reported_once(self):
        events = []
        runtime = FakeRuntime(
            events,
            screenshot_error=RuntimeError("capture detail"),
            teardown_error=RuntimeError("teardown detail"),
        )

        def action():
            events.append("action")
            return {"ok": False, "uncertain": True}

        with patch.object(observer, "Runtime", return_value=runtime), \
             patch.object(observer.time, "sleep", side_effect=lambda seconds: events.append("sleep")):
            result = observer.screenshot_after(action)

        self.assertEqual(["capture", "teardown"], [failure.stage for failure in result.failures])
        self.assertEqual("failed", result.capture_status)
        self.assertEqual("failed", result.teardown_status)
        self.assertEqual(1, runtime.screenshot_calls)
        self.assertEqual(1, runtime.teardown_calls)

    def test_heat_failure_does_not_invoke_action_and_still_tears_down_once(self):
        events = []
        runtime = FakeRuntime(events, heat_error=RuntimeError("not verified"))
        action = Mock()

        with patch.object(observer, "Runtime", return_value=runtime), \
             patch.object(observer.time, "sleep") as sleeper:
            result = observer.screenshot_after(action)

        self.assertEqual(["heat", "teardown"], events)
        action.assert_not_called()
        sleeper.assert_not_called()
        self.assertEqual(0, runtime.screenshot_calls)
        self.assertEqual(1, runtime.teardown_calls)
        self.assertEqual("not_invoked", result.action_status)
        self.assertEqual("not_attempted", result.capture_status)
        self.assertEqual("complete", result.teardown_status)
        self.assertEqual(["heat"], [failure.stage for failure in result.failures])


if __name__ == "__main__":
    unittest.main()
