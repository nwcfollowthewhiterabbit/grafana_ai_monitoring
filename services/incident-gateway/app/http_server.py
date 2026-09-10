from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from typing import Any
from urllib.parse import urlsplit

from .domain import PayloadError
from .service import GatewayService


logger = logging.getLogger(__name__)


class GatewayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(bind: str, port: int, service: GatewayService) -> GatewayHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "RabbitIncidentGateway/0.1"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            logger.info("http %s", format % args)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_metrics(self, body_text: str) -> None:
            body = body_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthz":
                self._send_json(200, {"status": "ok"})
                return
            if path == "/readyz":
                ready, payload = service.readiness()
                self._send_json(200 if ready else 503, payload)
                return
            if path == "/metrics":
                try:
                    self._send_metrics(service.metrics())
                except Exception:
                    logger.exception("metrics generation failed")
                    self._send_json(500, {"error": "metrics_unavailable"})
                return
            self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path != service.settings.webhook_path:
                self._send_json(404, {"error": "not_found"})
                return
            if not service.authorized(
                self.headers.get("Authorization"), self.headers.get("X-Alertmanager-Token")
            ):
                self._send_json(401, {"error": "unauthorized"})
                return
            length_header = self.headers.get("Content-Length")
            try:
                length = int(length_header or "0")
            except ValueError:
                self._send_json(400, {"error": "invalid_content_length"})
                return
            if length <= 0:
                self._send_json(400, {"error": "empty_body"})
                return
            if length > service.settings.max_request_bytes:
                self._send_json(413, {"error": "payload_too_large"})
                return
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                result = service.ingest(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "invalid_json"})
                return
            except PayloadError as exc:
                self._send_json(422, {"error": str(exc)})
                return
            except Exception:
                logger.exception("durable alert ingestion failed")
                self._send_json(500, {"error": "ingestion_failed"})
                return
            # The store committed the complete webhook transaction before this response.
            self._send_json(202, {"status": "accepted", **result})

    return GatewayHTTPServer((bind, port), Handler)
