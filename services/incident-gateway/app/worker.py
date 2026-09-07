from __future__ import annotations

import logging
import threading
import time

from .config import Settings
from .database import IncidentStore
from .telegram import TelegramClient


logger = logging.getLogger(__name__)


class OutboxWorker:
    def __init__(self, store: IncidentStore, telegram: TelegramClient, settings: Settings):
        self.store = store
        self.telegram = telegram
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.settings.mode != "live" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="notification-outbox", daemon=False)
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    @property
    def healthy(self) -> bool:
        if self.settings.mode == "shadow":
            return True
        return bool(self._thread and self._thread.is_alive())

    def _retry_delay(self, attempts: int, retry_after: float | None) -> float:
        if retry_after is not None:
            # Telegram's explicit flood-control delay is a minimum, not a hint.
            return max(retry_after, self.settings.retry_base_seconds)
        exponent = max(0, min(attempts - 1, 20))
        return min(self.settings.retry_base_seconds * (2**exponent), self.settings.retry_max_seconds)

    def run_once(self, now: float | None = None) -> bool:
        timestamp = now if now is not None else time.time()
        item = self.store.claim_next(timestamp, self.settings.outbox_lease_seconds)
        if item is None:
            return False
        try:
            result = self.telegram.send_message(item.payload_html, item.payload_plain)
        except Exception as exc:  # defensive: an outbox item must never be lost
            error = type(exc).__name__
            delay = self._retry_delay(item.attempts, None)
            self.store.mark_retry(item, error, timestamp + delay)
            logger.warning("telegram send raised; incident=%s kind=%s", item.incident_id, item.kind)
            return True
        if result.ok:
            self.store.mark_sent(item, result.message_id, timestamp)
            return True
        delay = self._retry_delay(item.attempts, result.retry_after)
        self.store.mark_retry(item, result.error or "telegram_send_failed", timestamp + delay)
        logger.warning(
            "telegram send failed; incident=%s kind=%s retry_in=%.1fs",
            item.incident_id,
            item.kind,
            delay,
        )
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                logger.exception("outbox worker iteration failed")
                worked = False
            if not worked:
                self._stop.wait(self.settings.worker_poll_seconds)
