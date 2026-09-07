from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import Settings  # noqa: E402
from app.database import IncidentStore  # noqa: E402
from app.domain import parse_alertmanager_payload  # noqa: E402
from app.telegram import SendResult, TelegramClient  # noqa: E402
from app.worker import OutboxWorker  # noqa: E402
from test_gateway import payload  # noqa: E402


class FakeTelegram:
    def __init__(self, results: list[SendResult]):
        self.results = results
        self.calls: list[tuple[str, str]] = []

    def send_message(self, html_text: str, plain_text: str) -> SendResult:
        self.calls.append((html_text, plain_text))
        return self.results.pop(0)


class FakeResponse:
    def __init__(self, body: dict, status: int = 200):
        self.body = json.dumps(body).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self.body


class WorkerTests(unittest.TestCase):
    def test_retry_after_is_honored_then_down_precedes_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = IncidentStore(str(Path(directory) / "gateway.db"), "live")
            store.ingest(parse_alertmanager_payload(payload("firing")), received_at=100.0)
            store.ingest(parse_alertmanager_payload(payload("resolved")), received_at=101.0)
            fake = FakeTelegram(
                [
                    SendResult(ok=False, error="Too Many Requests", retry_after=30.0),
                    SendResult(ok=True, message_id="11"),
                    SendResult(ok=True, message_id="12"),
                ]
            )
            settings = Settings(
                database_path=store.path,
                mode="live",
                telegram_bot_token="token",
                telegram_chat_id="chat",
            )
            worker = OutboxWorker(store, fake, settings)

            self.assertTrue(worker.run_once(now=102.0))
            self.assertFalse(worker.run_once(now=120.0))
            self.assertTrue(worker.run_once(now=132.0))
            self.assertTrue(worker.run_once(now=133.0))
            self.assertIn("DOWN", fake.calls[0][0])
            self.assertIn("DOWN", fake.calls[1][0])
            self.assertIn("RECOVERY", fake.calls[2][0])
            states = [(row["kind"], row["state"]) for row in store.fetch_all("notification_outbox")]
            self.assertEqual(states, [("down", "sent"), ("recovery", "sent")])


class TelegramTests(unittest.TestCase):
    def test_api_ok_false_is_failure(self) -> None:
        response = FakeResponse({"ok": False, "description": "chat not found"})
        with patch("urllib.request.urlopen", return_value=response):
            result = TelegramClient("token", "chat").send_message("<b>x</b>", "x")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "chat not found")

    def test_429_retry_after_is_parsed_without_plain_retry(self) -> None:
        body = json.dumps(
            {
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 7},
            }
        ).encode("utf-8")
        error = urllib.error.HTTPError(
            "https://api.telegram.invalid/sendMessage", 429, "Too Many Requests", {}, BytesIO(body)
        )
        with patch("urllib.request.urlopen", side_effect=error) as mocked:
            result = TelegramClient("token", "chat").send_message("<b>x</b>", "x")
        self.assertFalse(result.ok)
        self.assertEqual(result.retry_after, 7.0)
        self.assertEqual(mocked.call_count, 1)

    def test_html_parse_error_falls_back_to_plain(self) -> None:
        first = FakeResponse({"ok": False, "description": "Bad Request: can't parse entities"}, 400)
        second = FakeResponse({"ok": True, "result": {"message_id": 44}}, 200)
        with patch("urllib.request.urlopen", side_effect=[first, second]) as mocked:
            result = TelegramClient("token", "chat").send_message("<b>x", "x")
        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, "44")
        first_payload = json.loads(mocked.call_args_list[0].args[0].data.decode("utf-8"))
        second_payload = json.loads(mocked.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertEqual(first_payload["parse_mode"], "HTML")
        self.assertNotIn("parse_mode", second_payload)
        self.assertTrue(mocked.call_args_list[0].args[0].full_url.endswith("/sendMessage"))
        self.assertTrue(mocked.call_args_list[1].args[0].full_url.endswith("/sendMessage"))


if __name__ == "__main__":
    unittest.main()
