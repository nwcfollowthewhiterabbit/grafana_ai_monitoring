from __future__ import annotations

import hmac
from typing import Any

from .config import Settings
from .database import IncidentStore
from .domain import parse_alertmanager_payload
from .worker import OutboxWorker


class GatewayService:
    def __init__(self, settings: Settings, store: IncidentStore, worker: OutboxWorker):
        self.settings = settings
        self.store = store
        self.worker = worker

    def authorized(self, authorization: str | None, header_token: str | None) -> bool:
        expected = self.settings.webhook_token
        if not expected:
            return True
        bearer = ""
        if authorization and authorization.startswith("Bearer "):
            bearer = authorization[7:]
        return hmac.compare_digest(bearer, expected) or hmac.compare_digest(
            header_token or "", expected
        )

    def ingest(self, payload: Any) -> dict[str, int]:
        alerts = parse_alertmanager_payload(payload)
        return self.store.ingest(alerts).as_dict()

    def readiness(self) -> tuple[bool, dict[str, Any]]:
        database_ok, database_reason = self.store.health()
        telegram_ok = self.settings.mode == "shadow" or self.settings.telegram_configured
        worker_ok = self.worker.healthy
        ready = database_ok and telegram_ok and worker_ok
        return ready, {
            "status": "ready" if ready else "not_ready",
            "mode": self.settings.mode,
            "database": database_reason,
            "telegram_configured": self.settings.telegram_configured,
            "worker": "up" if worker_ok else "down",
        }

    def metrics(self) -> str:
        ready, _ = self.readiness()
        return self.store.metrics(worker_up=self.worker.healthy, ready=ready)
