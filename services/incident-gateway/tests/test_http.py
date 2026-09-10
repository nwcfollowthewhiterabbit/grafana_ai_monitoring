from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import Settings  # noqa: E402
from app.database import IncidentStore  # noqa: E402
from app.http_server import create_server  # noqa: E402
from app.service import GatewayService  # noqa: E402
from app.telegram import TelegramClient  # noqa: E402
from app.worker import OutboxWorker  # noqa: E402
from test_gateway import payload  # noqa: E402


class HTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            bind="127.0.0.1",
            port=1,
            database_path=str(Path(self.temp_dir.name) / "gateway.db"),
            mode="shadow",
            webhook_token="secret",
        )
        self.store = IncidentStore(self.settings.database_path, self.settings.mode)
        telegram = TelegramClient(None, None)
        self.worker = OutboxWorker(self.store, telegram, self.settings)
        self.service = GatewayService(self.settings, self.store, self.worker)
        self.server = create_server("127.0.0.1", 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp_dir.cleanup()

    def _get(self, path: str):
        with urllib.request.urlopen(f"{self.base}{path}", timeout=2) as response:
            return response.status, response.read().decode("utf-8")

    def test_health_ready_and_metrics(self) -> None:
        self.assertEqual(self._get("/healthz")[0], 200)
        self.assertEqual(self._get("/readyz")[0], 200)
        status, metrics = self._get("/metrics")
        self.assertEqual(status, 200)
        self.assertIn("incident_gateway_up 1", metrics)

    def test_webhook_returns_only_after_committed_ingest(self) -> None:
        body = json.dumps(payload("firing")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}/api/v1/alerts",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret",
            },
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 202)
        # The handler cannot emit 202 until the transaction has committed.
        self.assertEqual(len(self.store.fetch_all("incidents")), 1)
        self.assertEqual(len(self.store.fetch_all("incident_events")), 1)

    def test_webhook_rejects_bad_token_without_audit_write(self) -> None:
        body = json.dumps(payload("firing")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}/api/v1/alerts",
            data=body,
            method="POST",
            headers={"Authorization": "Bearer wrong"},
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(raised.exception.code, 401)
        self.assertEqual(self.store.fetch_all("incidents"), [])

    def test_live_readiness_requires_delivery_configuration(self) -> None:
        live_path = str(Path(self.temp_dir.name) / "live.db")
        settings = Settings(database_path=live_path, mode="live")
        store = IncidentStore(live_path, "live")
        worker = OutboxWorker(store, TelegramClient(None, None), settings)
        service = GatewayService(settings, store, worker)
        ready, details = service.readiness()
        self.assertFalse(ready)
        self.assertFalse(details["telegram_configured"])


if __name__ == "__main__":
    unittest.main()
