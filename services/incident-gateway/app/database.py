from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

from .domain import Alert, notification_text


SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    mode TEXT NOT NULL CHECK (mode IN ('shadow', 'live')),
    mode_generation INTEGER NOT NULL,
    changed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
    mode_generation INTEGER NOT NULL,
    labels_json TEXT NOT NULL,
    annotations_json TEXT NOT NULL,
    starts_at TEXT NOT NULL DEFAULT '',
    ends_at TEXT NOT NULL DEFAULT '',
    opened_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    resolved_at REAL,
    down_sent_at REAL,
    recovery_sent_at REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS incidents_one_open_fingerprint
ON incidents(fingerprint) WHERE state = 'open';
CREATE INDEX IF NOT EXISTS incidents_fingerprint_recent
ON incidents(fingerprint, id DESC);

CREATE TABLE IF NOT EXISTS incident_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER REFERENCES incidents(id),
    fingerprint TEXT NOT NULL,
    transition TEXT NOT NULL CHECK (
        transition IN ('firing', 'resolved', 'orphan_resolved', 'mode_changed')
    ),
    event_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TRIGGER IF NOT EXISTS incident_events_no_update
BEFORE UPDATE ON incident_events
BEGIN
    SELECT RAISE(ABORT, 'incident_events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS incident_events_no_delete
BEFORE DELETE ON incident_events
BEGIN
    SELECT RAISE(ABORT, 'incident_events are immutable');
END;

CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL REFERENCES incidents(id),
    event_id INTEGER NOT NULL REFERENCES incident_events(id),
    kind TEXT NOT NULL CHECK (kind IN ('down', 'recovery')),
    state TEXT NOT NULL CHECK (
        state IN ('pending', 'sending', 'retry', 'sent', 'cancelled_mode_switch')
    ),
    mode_generation INTEGER NOT NULL,
    payload_html TEXT NOT NULL,
    payload_plain TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    lease_until REAL,
    last_error TEXT,
    telegram_message_id TEXT,
    created_at REAL NOT NULL,
    sent_at REAL,
    UNIQUE(incident_id, kind)
);

CREATE INDEX IF NOT EXISTS notification_outbox_due
ON notification_outbox(state, mode_generation, next_attempt_at, id);

PRAGMA user_version = 1;
"""


@dataclass(frozen=True)
class IngestResult:
    opened: int = 0
    resolved: int = 0
    repeated: int = 0
    orphan_resolved: int = 0
    notifications_queued: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "opened": self.opened,
            "resolved": self.resolved,
            "repeated": self.repeated,
            "orphan_resolved": self.orphan_resolved,
            "notifications_queued": self.notifications_queued,
        }


@dataclass(frozen=True)
class OutboxItem:
    id: int
    incident_id: int
    kind: str
    payload_html: str
    payload_plain: str
    attempts: int


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class IncidentStore:
    def __init__(self, path: str, mode: str):
        if mode not in {"shadow", "live"}:
            raise ValueError("mode must be shadow or live")
        self.path = path
        self.mode = mode
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
        self._activate_mode(mode)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _activate_mode(self, mode: str) -> None:
        now = time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT mode, mode_generation FROM gateway_state WHERE singleton = 1"
            ).fetchone()
            if row is None:
                generation = 1
                connection.execute(
                    "INSERT INTO gateway_state(singleton, mode, mode_generation, changed_at) "
                    "VALUES (1, ?, ?, ?)",
                    (mode, generation, now),
                )
            elif row["mode"] != mode:
                generation = int(row["mode_generation"]) + 1
                connection.execute(
                    "UPDATE notification_outbox SET state = 'cancelled_mode_switch', "
                    "lease_until = NULL, last_error = 'cancelled on gateway mode switch' "
                    "WHERE state IN ('pending', 'retry', 'sending')"
                )
                connection.execute(
                    "UPDATE gateway_state SET mode = ?, mode_generation = ?, changed_at = ? "
                    "WHERE singleton = 1",
                    (mode, generation, now),
                )
                payload = {"from": row["mode"], "to": mode, "generation": generation}
                connection.execute(
                    "INSERT INTO incident_events(incident_id, fingerprint, transition, event_key, "
                    "payload_json, created_at) VALUES (NULL, '__gateway__', 'mode_changed', ?, ?, ?)",
                    (f"mode:{generation}", _json(payload), now),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _same_occurrence(row: sqlite3.Row, alert: Alert) -> bool:
        stored_starts_at = str(row["starts_at"] or "")
        stored_ends_at = str(row["ends_at"] or "")
        if stored_starts_at and alert.starts_at:
            return stored_starts_at == alert.starts_at
        if stored_ends_at and alert.ends_at:
            return stored_ends_at == alert.ends_at
        return True

    @staticmethod
    def _event_payload(alert: Alert) -> str:
        return _json(
            {
                "fingerprint": alert.fingerprint,
                "status": alert.status,
                "labels": alert.labels,
                "annotations": alert.annotations,
                "startsAt": alert.starts_at,
                "endsAt": alert.ends_at,
                "alert": alert.raw,
            }
        )

    def ingest(self, alerts: Iterable[Alert], received_at: float | None = None) -> IngestResult:
        now = received_at if received_at is not None else time.time()
        counts = {key: 0 for key in IngestResult().__dict__}
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                "SELECT mode, mode_generation FROM gateway_state WHERE singleton = 1"
            ).fetchone()
            if state is None:
                raise RuntimeError("gateway state is not initialized")
            mode = str(state["mode"])
            generation = int(state["mode_generation"])
            for alert in alerts:
                if alert.status == "firing":
                    self._ingest_firing(connection, alert, now, mode, generation, counts)
                else:
                    self._ingest_resolved(connection, alert, now, mode, generation, counts)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return IngestResult(**counts)

    def _ingest_firing(
        self,
        connection: sqlite3.Connection,
        alert: Alert,
        now: float,
        mode: str,
        generation: int,
        counts: dict[str, int],
    ) -> None:
        incident = connection.execute(
            "SELECT * FROM incidents WHERE fingerprint = ? AND state = 'open'",
            (alert.fingerprint,),
        ).fetchone()
        if incident is not None:
            connection.execute(
                "UPDATE incidents SET last_seen_at = ?, labels_json = ?, annotations_json = ? "
                "WHERE id = ?",
                (now, _json(alert.labels), _json(alert.annotations), incident["id"]),
            )
            counts["repeated"] += 1
            return

        latest = connection.execute(
            "SELECT * FROM incidents WHERE fingerprint = ? ORDER BY id DESC LIMIT 1",
            (alert.fingerprint,),
        ).fetchone()
        if (
            latest is not None
            and latest["state"] == "resolved"
            and alert.starts_at
            and latest["starts_at"] == alert.starts_at
        ):
            # A delayed Alertmanager retry must not reopen a completed occurrence.
            counts["repeated"] += 1
            return

        cursor = connection.execute(
            "INSERT INTO incidents(fingerprint, state, mode_generation, labels_json, "
            "annotations_json, starts_at, ends_at, opened_at, last_seen_at) "
            "VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?)",
            (
                alert.fingerprint,
                generation,
                _json(alert.labels),
                _json(alert.annotations),
                alert.starts_at,
                alert.ends_at,
                now,
                now,
            ),
        )
        incident_id = int(cursor.lastrowid)
        event = connection.execute(
            "INSERT INTO incident_events(incident_id, fingerprint, transition, event_key, "
            "payload_json, created_at) VALUES (?, ?, 'firing', ?, ?, ?)",
            (
                incident_id,
                alert.fingerprint,
                f"incident:{incident_id}:firing",
                self._event_payload(alert),
                now,
            ),
        )
        counts["opened"] += 1
        if mode == "live":
            html_text, plain_text = notification_text(alert, "down", incident_id)
            connection.execute(
                "INSERT INTO notification_outbox(incident_id, event_id, kind, state, "
                "mode_generation, payload_html, payload_plain, next_attempt_at, created_at) "
                "VALUES (?, ?, 'down', 'pending', ?, ?, ?, ?, ?)",
                (
                    incident_id,
                    int(event.lastrowid),
                    generation,
                    html_text,
                    plain_text,
                    now,
                    now,
                ),
            )
            counts["notifications_queued"] += 1

    def _ingest_resolved(
        self,
        connection: sqlite3.Connection,
        alert: Alert,
        now: float,
        mode: str,
        generation: int,
        counts: dict[str, int],
    ) -> None:
        incident = connection.execute(
            "SELECT * FROM incidents WHERE fingerprint = ? AND state = 'open'",
            (alert.fingerprint,),
        ).fetchone()
        if (
            incident is not None
            and incident["starts_at"]
            and alert.starts_at
            and incident["starts_at"] != alert.starts_at
        ):
            self._record_orphan_resolved(connection, alert, now, counts)
            return
        if incident is None:
            latest = connection.execute(
                "SELECT * FROM incidents WHERE fingerprint = ? ORDER BY id DESC LIMIT 1",
                (alert.fingerprint,),
            ).fetchone()
            if (
                latest is not None
                and latest["state"] == "resolved"
                and self._same_occurrence(latest, alert)
            ):
                counts["repeated"] += 1
                return
            self._record_orphan_resolved(connection, alert, now, counts)
            return

        incident_id = int(incident["id"])
        connection.execute(
            "UPDATE incidents SET state = 'resolved', resolved_at = ?, last_seen_at = ?, "
            "ends_at = ?, labels_json = ?, annotations_json = ? WHERE id = ?",
            (
                now,
                now,
                alert.ends_at,
                _json(alert.labels),
                _json(alert.annotations),
                incident_id,
            ),
        )
        event = connection.execute(
            "INSERT INTO incident_events(incident_id, fingerprint, transition, event_key, "
            "payload_json, created_at) VALUES (?, ?, 'resolved', ?, ?, ?)",
            (
                incident_id,
                alert.fingerprint,
                f"incident:{incident_id}:resolved",
                self._event_payload(alert),
                now,
            ),
        )
        counts["resolved"] += 1

        if mode == "live" and int(incident["mode_generation"]) == generation:
            queued = self._enqueue_recovery_if_eligible(
                connection, incident_id, generation, now, resolved_event_id=int(event.lastrowid)
            )
            if queued:
                counts["notifications_queued"] += 1

    def _record_orphan_resolved(
        self,
        connection: sqlite3.Connection,
        alert: Alert,
        now: float,
        counts: dict[str, int],
    ) -> None:
        occurrence = hashlib.sha256(
            f"{alert.fingerprint}\0{alert.starts_at}\0{alert.ends_at}".encode("utf-8")
        ).hexdigest()
        cursor = connection.execute(
            "INSERT OR IGNORE INTO incident_events(incident_id, fingerprint, transition, "
            "event_key, payload_json, created_at) VALUES (NULL, ?, 'orphan_resolved', ?, ?, ?)",
            (
                alert.fingerprint,
                f"orphan:{occurrence}",
                self._event_payload(alert),
                now,
            ),
        )
        if cursor.rowcount:
            counts["orphan_resolved"] += 1
        else:
            counts["repeated"] += 1

    def _enqueue_recovery_if_eligible(
        self,
        connection: sqlite3.Connection,
        incident_id: int,
        generation: int,
        now: float,
        resolved_event_id: int | None = None,
    ) -> bool:
        gateway = connection.execute(
            "SELECT mode, mode_generation FROM gateway_state WHERE singleton = 1"
        ).fetchone()
        incident = connection.execute(
            "SELECT * FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        down = connection.execute(
            "SELECT state FROM notification_outbox WHERE incident_id = ? AND kind = 'down'",
            (incident_id,),
        ).fetchone()
        if (
            gateway is None
            or gateway["mode"] != "live"
            or int(gateway["mode_generation"]) != generation
            or incident is None
            or incident["state"] != "resolved"
            or int(incident["mode_generation"]) != generation
            or down is None
            or down["state"] != "sent"
        ):
            return False
        existing = connection.execute(
            "SELECT 1 FROM notification_outbox WHERE incident_id = ? AND kind = 'recovery'",
            (incident_id,),
        ).fetchone()
        if existing is not None:
            return False
        event = connection.execute(
            "SELECT id, payload_json FROM incident_events WHERE id = ? AND transition = 'resolved'"
            if resolved_event_id is not None
            else "SELECT id, payload_json FROM incident_events WHERE incident_id = ? "
            "AND transition = 'resolved' ORDER BY id DESC LIMIT 1",
            (resolved_event_id if resolved_event_id is not None else incident_id,),
        ).fetchone()
        if event is None:
            return False
        payload = json.loads(event["payload_json"])
        alert = Alert(
            fingerprint=str(payload.get("fingerprint") or incident["fingerprint"]),
            status="resolved",
            labels={str(k): str(v) for k, v in (payload.get("labels") or {}).items()},
            annotations={str(k): str(v) for k, v in (payload.get("annotations") or {}).items()},
            starts_at=str(payload.get("startsAt") or ""),
            ends_at=str(payload.get("endsAt") or ""),
            raw=payload.get("alert") if isinstance(payload.get("alert"), dict) else {},
        )
        html_text, plain_text = notification_text(alert, "recovery", incident_id)
        connection.execute(
            "INSERT INTO notification_outbox(incident_id, event_id, kind, state, "
            "mode_generation, payload_html, payload_plain, next_attempt_at, created_at) "
            "VALUES (?, ?, 'recovery', 'pending', ?, ?, ?, ?, ?)",
            (
                incident_id,
                int(event["id"]),
                generation,
                html_text,
                plain_text,
                now,
                now,
            ),
        )
        return True

    def claim_next(self, now: float | None = None, lease_seconds: int = 60) -> OutboxItem | None:
        timestamp = now if now is not None else time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            mode = connection.execute(
                "SELECT mode, mode_generation FROM gateway_state WHERE singleton = 1"
            ).fetchone()
            if mode is None or mode["mode"] != "live":
                connection.commit()
                return None
            generation = int(mode["mode_generation"])
            connection.execute(
                "UPDATE notification_outbox SET state = 'retry', lease_until = NULL, "
                "next_attempt_at = ? WHERE state = 'sending' AND lease_until <= ? "
                "AND mode_generation = ?",
                (timestamp, timestamp, generation),
            )
            item = connection.execute(
                "SELECT o.* FROM notification_outbox o "
                "WHERE o.state IN ('pending', 'retry') AND o.mode_generation = ? "
                "AND o.next_attempt_at <= ? AND (o.kind = 'down' OR EXISTS ("
                "SELECT 1 FROM notification_outbox d WHERE d.incident_id = o.incident_id "
                "AND d.kind = 'down' AND d.state = 'sent')) "
                "ORDER BY o.created_at, CASE o.kind WHEN 'down' THEN 0 ELSE 1 END, o.id LIMIT 1",
                (generation, timestamp),
            ).fetchone()
            if item is None:
                connection.commit()
                return None
            attempts = int(item["attempts"]) + 1
            updated = connection.execute(
                "UPDATE notification_outbox SET state = 'sending', attempts = ?, lease_until = ? "
                "WHERE id = ? AND state IN ('pending', 'retry')",
                (attempts, timestamp + lease_seconds, item["id"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
            return OutboxItem(
                id=int(item["id"]),
                incident_id=int(item["incident_id"]),
                kind=str(item["kind"]),
                payload_html=str(item["payload_html"]),
                payload_plain=str(item["payload_plain"]),
                attempts=attempts,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_sent(self, item: OutboxItem, message_id: str | None, sent_at: float | None = None) -> bool:
        now = sent_at if sent_at is not None else time.time()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE notification_outbox SET state = 'sent', sent_at = ?, lease_until = NULL, "
                "last_error = NULL, telegram_message_id = ? WHERE id = ? AND state = 'sending'",
                (now, message_id, item.id),
            )
            if updated.rowcount:
                column = "down_sent_at" if item.kind == "down" else "recovery_sent_at"
                connection.execute(
                    f"UPDATE incidents SET {column} = ? WHERE id = ?", (now, item.incident_id)
                )
                if item.kind == "down":
                    generation = connection.execute(
                        "SELECT mode_generation FROM notification_outbox WHERE id = ?", (item.id,)
                    ).fetchone()["mode_generation"]
                    self._enqueue_recovery_if_eligible(
                        connection, item.incident_id, int(generation), now
                    )
            connection.commit()
            return updated.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_retry(self, item: OutboxItem, error: str, next_attempt_at: float) -> bool:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE notification_outbox SET state = 'retry', next_attempt_at = ?, "
                "lease_until = NULL, last_error = ? WHERE id = ? AND state = 'sending'",
                (next_attempt_at, error[:500], item.id),
            )
            connection.commit()
            return updated.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def health(self) -> tuple[bool, str]:
        try:
            with self._connect() as connection:
                result = connection.execute("SELECT mode FROM gateway_state WHERE singleton = 1").fetchone()
            if result is None or result["mode"] != self.mode:
                return False, "mode_state_mismatch"
            return True, "ok"
        except sqlite3.Error as exc:
            return False, type(exc).__name__

    def metrics(self, worker_up: bool, ready: bool) -> str:
        with self._connect() as connection:
            mode = connection.execute(
                "SELECT mode, mode_generation FROM gateway_state WHERE singleton = 1"
            ).fetchone()
            incidents = connection.execute(
                "SELECT state, COUNT(*) AS count FROM incidents GROUP BY state"
            ).fetchall()
            open_incidents = connection.execute(
                "SELECT labels_json FROM incidents WHERE state = 'open'"
            ).fetchall()
            events = connection.execute(
                "SELECT transition, COUNT(*) AS count FROM incident_events GROUP BY transition"
            ).fetchall()
            outbox = connection.execute(
                "SELECT kind, state, COUNT(*) AS count FROM notification_outbox GROUP BY kind, state"
            ).fetchall()
            attempts = connection.execute(
                "SELECT COALESCE(SUM(attempts), 0) AS count FROM notification_outbox"
            ).fetchone()["count"]
        mode_name = str(mode["mode"]) if mode else "unknown"
        generation = int(mode["mode_generation"]) if mode else 0
        lines = [
            "# HELP incident_gateway_up Process health.",
            "# TYPE incident_gateway_up gauge",
            "incident_gateway_up 1",
            "# HELP incident_gateway_ready Readiness including database, worker, and live credentials.",
            "# TYPE incident_gateway_ready gauge",
            f"incident_gateway_ready {1 if ready else 0}",
            "# HELP incident_gateway_worker_up Outbox worker health (shadow mode is considered healthy).",
            "# TYPE incident_gateway_worker_up gauge",
            f"incident_gateway_worker_up {1 if worker_up else 0}",
            "# HELP incident_gateway_mode_info Active delivery mode.",
            "# TYPE incident_gateway_mode_info gauge",
            f'incident_gateway_mode_info{{mode="{mode_name}"}} 1',
            "# HELP incident_gateway_mode_generation Delivery epoch; changes cancel stale backlog.",
            "# TYPE incident_gateway_mode_generation gauge",
            f"incident_gateway_mode_generation {generation}",
            "# HELP incident_gateway_incidents Incident records by lifecycle state.",
            "# TYPE incident_gateway_incidents gauge",
        ]
        incident_counts = {str(row["state"]): int(row["count"]) for row in incidents}
        for state in ("open", "resolved"):
            lines.append(f'incident_gateway_incidents{{state="{state}"}} {incident_counts.get(state, 0)}')
        open_incident_counts: dict[tuple[str, str, str, str, str], int] = {}
        hierarchy_labels = ("company", "alias", "stack", "service", "severity")
        for row in open_incidents:
            labels = json.loads(row["labels_json"])
            key = tuple(str(labels.get(name) or "unknown") for name in hierarchy_labels)
            open_incident_counts[key] = open_incident_counts.get(key, 0) + 1
        lines.extend(
            [
                "# HELP rs_monitoring_open_incident Open incidents aggregated by the bounded service hierarchy.",
                "# TYPE rs_monitoring_open_incident gauge",
            ]
        )
        for key, count in sorted(open_incident_counts.items()):
            metric_labels = ",".join(
                f'{name}="{_metric_label(value)}"'
                for name, value in zip(hierarchy_labels, key)
            )
            lines.append(
                f'rs_monitoring_open_incident{{{metric_labels},state="open"}} {count}'
            )
        lines.extend(
            [
                "# HELP incident_gateway_events_total Immutable lifecycle events.",
                "# TYPE incident_gateway_events_total counter",
            ]
        )
        event_counts = {str(row["transition"]): int(row["count"]) for row in events}
        for transition in ("firing", "resolved", "orphan_resolved", "mode_changed"):
            lines.append(
                f'incident_gateway_events_total{{transition="{transition}"}} '
                f"{event_counts.get(transition, 0)}"
            )
        lines.extend(
            [
                "# HELP incident_gateway_orphan_resolved_total Resolved transitions without an open incident.",
                "# TYPE incident_gateway_orphan_resolved_total counter",
                f"incident_gateway_orphan_resolved_total {event_counts.get('orphan_resolved', 0)}",
                "# HELP incident_gateway_outbox_messages Durable notifications by kind and state.",
                "# TYPE incident_gateway_outbox_messages gauge",
            ]
        )
        for row in outbox:
            lines.append(
                f'incident_gateway_outbox_messages{{kind="{row["kind"]}",state="{row["state"]}"}} '
                f'{int(row["count"])}'
            )
        lines.extend(
            [
                "# HELP rs_monitoring_incident_notification_outbox Durable incident notifications by kind and state.",
                "# TYPE rs_monitoring_incident_notification_outbox gauge",
            ]
        )
        for row in outbox:
            lines.append(
                f'rs_monitoring_incident_notification_outbox{{kind="{row["kind"]}",state="{row["state"]}"}} '
                f'{int(row["count"])}'
            )
        lines.extend(
            [
                "# HELP incident_gateway_telegram_attempts_total Durable Telegram send attempts.",
                "# TYPE incident_gateway_telegram_attempts_total counter",
                f"incident_gateway_telegram_attempts_total {int(attempts)}",
            ]
        )
        return "\n".join(lines) + "\n"

    def fetch_all(self, table: str) -> list[sqlite3.Row]:
        if table not in {"gateway_state", "incidents", "incident_events", "notification_outbox"}:
            raise ValueError("unsupported table")
        with self._connect() as connection:
            return connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
