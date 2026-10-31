import unittest
from datetime import datetime, timedelta, timezone

from cloud_runner import (
    balance_band,
    decide_action,
    in_cooldown,
    is_confirmation_action_text,
    is_delayed_confirmation,
    is_refill_label,
    is_safe_free_refill_modal_text,
    is_safe_confirmation_text,
)


class CloudDecisionTests(unittest.TestCase):
    def test_above_threshold_only_monitors(self):
        self.assertEqual(decide_action(751, 750, "MISSING", True, False), "MONITORING")

    def test_exact_threshold_only_monitors(self):
        self.assertEqual(decide_action(750, 750, "MISSING", True, False), "MONITORING")

    def test_enabled_refill_control_never_overrides_balance(self):
        self.assertEqual(
            decide_action(751, 750, "ENABLED", True, False),
            "MONITORING",
        )

    def test_exact_threshold_never_books_even_with_enabled_control(self):
        self.assertEqual(
            decide_action(750, 750, "ENABLED", True, False),
            "MONITORING",
        )

    def test_balance_band_does_not_expose_amount(self):
        self.assertEqual(balance_band(749, 750), "BELOW_THRESHOLD")
        self.assertEqual(balance_band(750, 750), "AT_THRESHOLD")
        self.assertEqual(balance_band(751, 750), "ABOVE_THRESHOLD")

    def test_current_bare_one_gb_label_is_recognized(self):
        self.assertTrue(is_refill_label("1 GB"))
        self.assertTrue(is_refill_label("+ 1 GB"))
        self.assertTrue(is_refill_label("1 GB kostenlos nachbuchen"))
        self.assertFalse(is_refill_label("Noch 1 GB von 100 GB"))

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

    def test_confirmation_requires_booking_and_confirmation_words(self):
        self.assertTrue(is_safe_confirmation_text("Buchung bestätigen"))
        self.assertFalse(is_safe_confirmation_text("Bestätigen"))
        self.assertFalse(is_safe_confirmation_text("Jetzt buchen"))
        self.assertFalse(is_safe_confirmation_text("Weiter"))

    def test_free_refill_modal_requires_free_one_gb_offer(self):
        self.assertTrue(
            is_safe_free_refill_modal_text("1 GB kostenlos aktivieren")
        )
        self.assertFalse(is_safe_free_refill_modal_text("1 GB bestätigen"))
        self.assertFalse(
            is_safe_free_refill_modal_text("1 GB kostenpflichtig buchen")
        )

    def test_confirmation_action_excludes_cancel_controls(self):
        self.assertTrue(is_confirmation_action_text("Bestätigen"))
        self.assertTrue(is_confirmation_action_text("Jetzt aktivieren"))
        self.assertFalse(is_confirmation_action_text("Abbrechen"))
        self.assertFalse(is_confirmation_action_text("Weiter"))

    def test_delayed_confirmation_requires_recent_unconfirmed_click(self):
        self.assertTrue(
            is_delayed_confirmation(900, 900, "CLICKED_UNCONFIRMED", True)
        )
        self.assertFalse(
            is_delayed_confirmation(899, 900, "CLICKED_UNCONFIRMED", True)
        )
        self.assertFalse(is_delayed_confirmation(900, 900, "CONFIRMED", True))
        self.assertFalse(
            is_delayed_confirmation(900, 900, "CLICKED_UNCONFIRMED", False)
        )

    def test_delayed_confirmation_accepts_recent_otp_challenge(self):
        self.assertTrue(is_delayed_confirmation(900, 900, "OTP_REQUIRED", True))
        self.assertFalse(is_delayed_confirmation(899, 900, "OTP_REQUIRED", True))


if __name__ == "__main__":
    unittest.main()
