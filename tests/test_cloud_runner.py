import unittest
from datetime import datetime, timedelta, timezone

from cloud_runner import balance_band, decide_action, in_cooldown


class CloudDecisionTests(unittest.TestCase):
    def test_above_threshold_only_monitors(self):
        self.assertEqual(decide_action(751, 750, "ENABLED", True, False), "MONITORING")

    def test_exact_threshold_only_monitors(self):
        self.assertEqual(decide_action(750, 750, "ENABLED", True, False), "MONITORING")

    def test_balance_band_does_not_expose_amount(self):
        self.assertEqual(balance_band(749, 750), "BELOW_THRESHOLD")
        self.assertEqual(balance_band(750, 750), "AT_THRESHOLD")
        self.assertEqual(balance_band(751, 750), "ABOVE_THRESHOLD")

    def test_missing_or_ambiguous_control_never_clicks(self):
        self.assertEqual(
            decide_action(600, 750, "UNKNOWN", True, False),
            "WAITING_FOR_REFILL_CONTROL",
        )

    def test_dry_run_never_clicks(self):
        self.assertEqual(decide_action(600, 750, "ENABLED", False, False), "READY_TO_BOOK")

    def test_execute_allows_one_click(self):
        self.assertEqual(decide_action(600, 750, "ENABLED", True, False), "BOOK")

    def test_cooldown_blocks_repeat(self):
        now = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
        self.assertTrue(in_cooldown(now - timedelta(minutes=10), now, 30))
        self.assertEqual(decide_action(600, 750, "ENABLED", True, True), "COOLDOWN")


if __name__ == "__main__":
    unittest.main()
