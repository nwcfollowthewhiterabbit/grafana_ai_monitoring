from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import urllib.error
import urllib.request


@dataclass(frozen=True)
class SendResult:
    ok: bool
    message_id: str | None = None
    error: str = ""
    retry_after: float | None = None
    status_code: int | None = None


class TelegramClient:
    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        message_thread_id: int | None = None,
        timeout_seconds: float = 10.0,
    ):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._message_thread_id = message_thread_id
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def send_message(self, html_text: str, plain_text: str) -> SendResult:
        if not self.configured:
            return SendResult(ok=False, error="telegram_not_configured")
        result = self._send(html_text, parse_mode="HTML")
        if result.ok or result.retry_after is not None:
            return result
        if result.status_code == 400 and self._is_parse_error(result.error):
            return self._send(plain_text, parse_mode=None)
        return result

    @staticmethod
    def _is_parse_error(error: str) -> bool:
        lowered = error.lower()
        return any(
            marker in lowered
            for marker in ("parse entities", "can't parse", "cant parse", "unsupported start tag")
        )

    def _send(self, text: str, parse_mode: str | None) -> SendResult:
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text[:4000],
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if self._message_thread_id is not None:
            payload["message_thread_id"] = self._message_thread_id
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "rabbit-incident-gateway/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                status_code = int(response.getcode())
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            response_body = exc.read()
            return self._decode(response_body, exc.code)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return SendResult(ok=False, error=type(exc).__name__)
        return self._decode(response_body, status_code)

    @staticmethod
    def _decode(body: bytes, status_code: int) -> SendResult:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return SendResult(ok=False, error="telegram_invalid_json", status_code=status_code)
        if not isinstance(data, dict):
            return SendResult(ok=False, error="telegram_invalid_response", status_code=status_code)
        retry_after = None
        parameters = data.get("parameters")
        if isinstance(parameters, dict) and parameters.get("retry_after") is not None:
            try:
                retry_after = max(0.0, float(parameters["retry_after"]))
            except (TypeError, ValueError):
                retry_after = None
        if not 200 <= status_code < 300 or data.get("ok") is not True:
            description = str(data.get("description") or f"telegram_http_{status_code}")[:300]
            return SendResult(
                ok=False,
                error=description,
                retry_after=retry_after,
                status_code=status_code,
            )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        message_id = result.get("message_id")
        return SendResult(
            ok=True,
            message_id=str(message_id) if message_id is not None else None,
            status_code=status_code,
        )
