import json
import unittest

from ipad_agent.operations import (
    BatchResult,
    OperationAuthority,
    OperationError,
    OperationPhase,
    OperationResult,
    OperationSpec,
    RetryClass,
    SafetyClass,
    dumps_message,
    loads_message,
)


class OperationContractTests(unittest.TestCase):
    def operation(self, operation_id="read", safety=SafetyClass.OBSERVE, **options):
        return OperationSpec(operation_id, operation_id, safety, **options)

    def test_dispatch_phases_make_response_loss_structurally_uncertain(self):
        operation = self.operation()
        not_sent = OperationResult.not_sent(operation)
        sent = OperationResult.sent(operation)
        lost = OperationResult.response_lost(
            operation,
            OperationError("transport_closed", "a message with no magic timeout wording"),
        )

        self.assertEqual(OperationPhase.NOT_SENT, not_sent.phase)
        self.assertFalse(not_sent.dispatched)
        self.assertEqual(OperationPhase.SENT, sent.phase)
        self.assertTrue(sent.dispatched)
        self.assertFalse(sent.uncertain)
        self.assertEqual(OperationPhase.RESPONSE_LOST, lost.phase)
        self.assertTrue(lost.dispatched)
        self.assertTrue(lost.uncertain)
        self.assertIsNone(lost.ok)
        self.assertTrue(lost.to_plain_result()["uncertain"])

    def test_sensitive_operations_require_complete_explicit_authority(self):
        for safety in (SafetyClass.PERSISTENT, SafetyClass.PROTECTED):
            with self.subTest(safety=safety):
                with self.assertRaisesRegex(ValueError, "explicit authority"):
                    self.operation(safety=safety)

        with self.assertRaisesRegex(ValueError, "granted_by"):
            OperationAuthority("grant-1", "", "change wallpaper", "2026-03-09T12:00:00Z")

        authority = OperationAuthority(
            "grant-1", "user", "change wallpaper", "2026-03-09T12:00:00Z"
        )
        persistent = self.operation(
            "wallpaper", SafetyClass.PERSISTENT, authority=authority
        )
        protected = self.operation(
            "confirm", SafetyClass.PROTECTED, authority=authority
        )
        self.assertEqual(RetryClass.INSPECT_THEN_DECIDE, persistent.retry_class)
        self.assertEqual(RetryClass.NEVER_AUTOMATED, protected.retry_class)
        with self.assertRaisesRegex(ValueError, "never_automated"):
            self.operation(
                "bad-confirm",
                SafetyClass.PROTECTED,
                authority=authority,
                retry_class=RetryClass.INSPECT_THEN_DECIDE,
            )

    def test_retry_defaults_cover_every_safety_class(self):
        authority = OperationAuthority("g", "user", "exact action", "now")
        expected = {
            SafetyClass.OBSERVE: RetryClass.SAFE_REPEAT,
            SafetyClass.NAVIGATE: RetryClass.SAFE_REPEAT,
            SafetyClass.TRANSIENT: RetryClass.INSPECT_THEN_DECIDE,
            SafetyClass.PERSISTENT: RetryClass.INSPECT_THEN_DECIDE,
            SafetyClass.PROTECTED: RetryClass.NEVER_AUTOMATED,
        }
        for index, (safety, retry) in enumerate(expected.items()):
            options = {"authority": authority} if safety in {
                SafetyClass.PERSISTENT,
                SafetyClass.PROTECTED,
            } else {}
            operation = self.operation(f"op-{index}", safety, **options)
            self.assertEqual(retry, operation.retry_class)

    def test_plain_projection_retains_result_and_contract_metadata(self):
        operation = OperationSpec(
            "observe-1",
            "read screen",
            SafetyClass.OBSERVE,
            metadata={"request_id": "r1"},
        )
        result = OperationResult.succeeded(operation, {"text": "hello", "ok": "payload"})
        plain = result.to_plain_result()

        self.assertEqual("hello", plain["text"])
        self.assertTrue(plain["ok"])
        self.assertEqual("response_received", plain["_operation"]["phase"])
        self.assertEqual("observe", plain["_operation"]["safety_class"])
        self.assertEqual("safe_repeat", plain["_operation"]["retry_class"])
        self.assertFalse(plain["_operation"]["uncertain"])

    def test_batch_aggregation_preserves_counts_uncertainty_and_strictest_retry(self):
        observed = self.operation("observe", SafetyClass.OBSERVE)
        transient = self.operation("tap", SafetyClass.TRANSIENT)
        batch = BatchResult.aggregate(
            "batch-1",
            [
                OperationResult.succeeded(observed, {"visible": True}),
                OperationResult.response_lost(transient),
            ],
        )

        self.assertFalse(batch.ok)
        self.assertTrue(batch.complete)
        self.assertTrue(batch.uncertain)
        self.assertEqual(2, batch.counts["total"])
        self.assertEqual(1, batch.counts["succeeded"])
        self.assertEqual(1, batch.counts["uncertain"])
        self.assertEqual(1, batch.phase_counts["response_lost"])
        self.assertEqual(RetryClass.INSPECT_THEN_DECIDE, batch.retry_class)
        projected = batch.to_plain_result()
        self.assertTrue(projected["uncertain"])
        self.assertEqual("batch-1", projected["_operation"]["batch_id"])

    def test_daemon_message_and_evidence_serialization_round_trip(self):
        authority = OperationAuthority("grant", "user", "save exact file", "now")
        operation = self.operation(
            "save",
            SafetyClass.PERSISTENT,
            authority=authority,
            metadata={"unicode": "zażółć"},
        )
        batch = BatchResult.aggregate(
            "batch-json",
            [OperationResult.failed(operation, OperationError("device_rejected", "not accepted"))],
        )

        payload = dumps_message(batch)
        self.assertEqual(batch, loads_message(payload))
        self.assertEqual("batch_result", json.loads(payload)["kind"])
        evidence = batch.to_evidence(include_responses=False)
        self.assertEqual("ipad_agent.operation/v1", evidence["schema"])
        self.assertEqual("grant", evidence["batch"]["results"][0]["operation"]["authority"]["authority_id"])

    def test_invalid_phase_combinations_are_rejected(self):
        operation = self.operation()
        with self.assertRaisesRegex(ValueError, "boolean ok"):
            OperationResult(operation, OperationPhase.RESPONSE_RECEIVED)
        with self.assertRaisesRegex(ValueError, "ok=None"):
            OperationResult(operation, OperationPhase.RESPONSE_LOST, ok=False)
        with self.assertRaisesRegex(ValueError, "structured error"):
            OperationResult(operation, OperationPhase.RESPONSE_RECEIVED, ok=False)


if __name__ == "__main__":
    unittest.main()
