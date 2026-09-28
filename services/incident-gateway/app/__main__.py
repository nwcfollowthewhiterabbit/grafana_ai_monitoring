from __future__ import annotations

import logging
from pathlib import Path
import signal
import threading

from .config import ConfigError, Settings
from .database import IncidentStore
from .http_server import create_server
from .service import GatewayService
from .telegram import TelegramClient
from .worker import OutboxWorker


def main() -> int:
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        logging.getLogger(__name__).error("configuration error: %s", exc)
        return 2
    if settings.database_path != ":memory:":
        Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    store = IncidentStore(settings.database_path, settings.mode)
    telegram = TelegramClient(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
        settings.telegram_message_thread_id,
        settings.telegram_timeout_seconds,
    )
    worker = OutboxWorker(store, telegram, settings)
    service = GatewayService(settings, store, worker)
    server = create_server(settings.bind, settings.port, service)
    server.timeout = 0.5
    stopping = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logging.getLogger(__name__).info("received signal %s; stopping", signum)
        stopping.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    worker.start()
    logging.getLogger(__name__).info(
        "incident gateway listening on %s:%s mode=%s",
        settings.bind,
        server.server_port,
        settings.mode,
    )
    try:
        while not stopping.is_set():
            server.handle_request()
    finally:
        server.server_close()
        worker.stop(timeout=max(15.0, settings.telegram_timeout_seconds + 5.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
