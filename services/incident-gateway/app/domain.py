from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
from typing import Any


class PayloadError(ValueError):
    pass


@dataclass(frozen=True)
class Alert:
    fingerprint: str
    status: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: str
    ends_at: str
    raw: dict[str, Any]


def _string_map(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PayloadError(f"{field} must be an object")
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _fingerprint(alert: dict[str, Any], labels: dict[str, str]) -> str:
    supplied = str(alert.get("fingerprint") or "").strip()
    if supplied and len(supplied) <= 512:
        return supplied
    stable = json.dumps(labels, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if supplied:
        stable = supplied
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def parse_alertmanager_payload(payload: Any) -> list[Alert]:
    if not isinstance(payload, dict):
        raise PayloadError("payload must be an object")
    raw_alerts = payload.get("alerts")
    if not isinstance(raw_alerts, list) or not raw_alerts:
        raise PayloadError("alerts must be a non-empty array")
    default_status = str(payload.get("status") or "").strip().lower()
    alerts: list[Alert] = []
    for index, raw in enumerate(raw_alerts):
        if not isinstance(raw, dict):
            raise PayloadError(f"alerts[{index}] must be an object")
        status = str(raw.get("status") or default_status).strip().lower()
        if status in {"firing", "alerting", "active"}:
            status = "firing"
        elif status in {"resolved", "ok", "normal"}:
            status = "resolved"
        else:
            raise PayloadError(f"alerts[{index}].status is not firing or resolved")
        labels = _string_map(raw.get("labels"), f"alerts[{index}].labels")
        annotations = _string_map(raw.get("annotations"), f"alerts[{index}].annotations")
        alerts.append(
            Alert(
                fingerprint=_fingerprint(raw, labels),
                status=status,
                labels=labels,
                annotations=annotations,
                starts_at=str(raw.get("startsAt") or ""),
                ends_at=str(raw.get("endsAt") or ""),
                raw=raw,
            )
        )
    return alerts


def _first(mapping: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return default


def notification_text(alert: Alert, kind: str, incident_id: int) -> tuple[str, str]:
    labels = alert.labels
    annotations = alert.annotations
    title = "DOWN" if kind == "down" else "RECOVERY"
    marker = "ALERT" if kind == "down" else "OK"
    summary = _first(
        annotations,
        "summary",
        "description",
        default=_first(labels, "alertname", default="Monitoring incident"),
    )
    fields = [
        ("Company", _first(labels, "company", "workspace", "tenant")),
        ("Server", _first(labels, "server", "alias", "node", "host", "instance")),
        ("Application", _first(labels, "application", "app", "stack", "job")),
        ("Component", _first(labels, "component", "service", "container")),
        ("Severity", _first(labels, "severity", "priority")),
    ]
    plain_lines = [f"{marker} {title}", summary]
    html_lines = [f"<b>{title}</b>", html.escape(summary)]
    for label, value in fields:
        if value:
            plain_lines.append(f"{label}: {value}")
            html_lines.append(f"<b>{html.escape(label)}:</b> {html.escape(value)}")
    plain_lines.append(f"Incident: {incident_id}")
    html_lines.append(f"<b>Incident:</b> {incident_id}")
    return "\n".join(html_lines)[:4000], "\n".join(plain_lines)[:4000]
