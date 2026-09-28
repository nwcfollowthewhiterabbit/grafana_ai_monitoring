from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import Alert, notification_text  # noqa: E402


def alert(summary: str = "Expected component stopped") -> Alert:
    return Alert(
        fingerprint="example", status="resolved",
        labels={"company": "Acme", "alias": "host", "stack": "erp", "service": "backend"},
        annotations={"summary": summary}, starts_at="", ends_at="", raw={},
    )


class NotificationTextTests(unittest.TestCase):
    def test_resolution_reports_signal_clearance_without_claiming_verified_recovery(self):
        html_text, plain_text = notification_text(alert(), "recovery", 42)
        self.assertTrue(html_text.startswith("<b>ALERT RESOLVED</b>"))
        self.assertTrue(plain_text.startswith("ALERT RESOLVED\n"))
        for text in (html_text, plain_text):
            self.assertIn("Service recovery is not independently verified", text)
            self.assertIn("Previous alert: Expected component stopped", text)
            self.assertNotIn("OK RECOVERY", text)
            self.assertIn("42", text)
        self.assertIn("Incident: 42", plain_text)

    def test_down_message_is_unchanged(self):
        html_text, plain_text = notification_text(alert(), "down", 42)
        self.assertTrue(html_text.startswith("<b>DOWN</b>\nExpected component stopped"))
        self.assertTrue(plain_text.startswith("ALERT DOWN\nExpected component stopped"))
        self.assertNotIn("Previous alert:", plain_text)
        self.assertNotIn("independently verified", plain_text)

    def test_resolution_escapes_previous_alert_and_identity_values(self):
        sample = alert("<b>stopped & missing</b>")
        sample.labels["company"] = "<Acme & Co>"
        html_text, plain_text = notification_text(sample, "recovery", 7)
        self.assertIn("Previous alert: &lt;b&gt;stopped &amp; missing&lt;/b&gt;", html_text)
        self.assertIn("&lt;Acme &amp; Co&gt;", html_text)
        self.assertIn("Previous alert: <b>stopped & missing</b>", plain_text)

    def test_long_annotations_cannot_truncate_the_resolution_qualification(self):
        html_text, plain_text = notification_text(alert("x" * 8000), "recovery", 42)
        for text in (html_text, plain_text):
            self.assertLessEqual(len(text), 4000)
            self.assertIn("Service recovery is not independently verified", text)


if __name__ == "__main__":
    unittest.main()
