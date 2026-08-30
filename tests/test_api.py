import unittest

from ipad_agent.api import IPadResult


class ResultTests(unittest.TestCase):
    def test_success_is_compact_and_mapping_is_retained(self):
        result = IPadResult({"ok": True, "route": "now", "revision": "abc", "timings_ms": {"total": 42}})
        self.assertEqual("shown", repr(result))
        self.assertEqual("abc", result["revision"])

    def test_locked_launch_is_distinct(self):
        result = IPadResult({"ok": True, "route": "coredevice", "locked": True})
        self.assertEqual("locked", repr(result))

    def test_lost_mutation_forbids_retry(self):
        result = IPadResult({"ok": False, "error": "daemon request outcome is unknown: timed out"})
        self.assertEqual("uncertain: daemon request outcome is unknown: timed out; do not retry", repr(result))


if __name__ == "__main__":
    unittest.main()
