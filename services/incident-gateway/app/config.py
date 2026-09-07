from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


class ConfigError(ValueError):
    pass


def _secret(name: str) -> str | None:
    value = os.environ.get(name)
    file_name = os.environ.get(f"{name}_FILE")
    if value and file_name:
        raise ConfigError(f"set only one of {name} and {name}_FILE")
    if file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"cannot read {name}_FILE: {type(exc).__name__}") from exc
    return value.strip() if value and value.strip() else None


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    bind: str = "0.0.0.0"
    port: int = 8080
    database_path: str = "/var/lib/incident-gateway/incidents.db"
    mode: str = "shadow"
    webhook_path: str = "/api/v1/alerts"
    webhook_token: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_message_thread_id: int | None = None
    telegram_timeout_seconds: float = 10.0
    worker_poll_seconds: float = 1.0
    outbox_lease_seconds: int = 60
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 900.0
    max_request_bytes: int = 1_048_576

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.environ.get("GATEWAY_MODE", "shadow").strip().lower()
        if mode not in {"shadow", "live"}:
            raise ConfigError("GATEWAY_MODE must be shadow or live")
        webhook_path = os.environ.get("WEBHOOK_PATH", "/api/v1/alerts").strip()
        if not webhook_path.startswith("/") or "?" in webhook_path or "#" in webhook_path:
            raise ConfigError("WEBHOOK_PATH must be an absolute path without query or fragment")
        thread_raw = _secret("TELEGRAM_MESSAGE_THREAD_ID")
        try:
            thread_id = int(thread_raw) if thread_raw else None
        except ValueError as exc:
            raise ConfigError("TELEGRAM_MESSAGE_THREAD_ID must be an integer") from exc

        return cls(
            bind=os.environ.get("GATEWAY_BIND", "0.0.0.0"),
            port=_integer("GATEWAY_PORT", 8080, 1, 65535),
            database_path=os.environ.get(
                "GATEWAY_DATABASE_PATH", "/var/lib/incident-gateway/incidents.db"
            ),
            mode=mode,
            webhook_path=webhook_path,
            webhook_token=_secret("ALERT_WEBHOOK_TOKEN"),
            telegram_bot_token=_secret("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_secret("TELEGRAM_CHAT_ID"),
            telegram_message_thread_id=thread_id,
            telegram_timeout_seconds=_number("TELEGRAM_TIMEOUT_SECONDS", 10.0, 0.2, 120.0),
            worker_poll_seconds=_number("WORKER_POLL_SECONDS", 1.0, 0.05, 60.0),
            outbox_lease_seconds=_integer("OUTBOX_LEASE_SECONDS", 60, 5, 3600),
            retry_base_seconds=_number("RETRY_BASE_SECONDS", 2.0, 0.1, 3600.0),
            retry_max_seconds=_number("RETRY_MAX_SECONDS", 900.0, 1.0, 86400.0),
            max_request_bytes=_integer("MAX_REQUEST_BYTES", 1_048_576, 1024, 16_777_216),
        )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)
