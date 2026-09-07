from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.database import IncidentStore  # noqa: E402
from app.domain import parse_alertmanager_payload  # noqa: E402


def payload(status: str, fingerprint: str = "abc", starts_at: str = "2026-09-07T10:00:00Z") -> dict:
    return {
        "status": status,
        "alerts": [
            {
                "status": status,
                "fingerprint": fingerprint,
                "startsAt": starts_at,
                "endsAt": "2026-09-07T10:05:00Z" if status == "resolved" else "",
                "labels": {
                    "alertname": "ServiceDown",
                    "company": "greenleaf",
                    "alias": "cloud",
                    "stack": "erp",
                    "service": "frontend",
                    "severity": "critical",
                },
                "annotations": {"summary": "ERP is unavailable"},
            }
        ],
    }


class IncidentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "gateway.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _ingest(self, store: IncidentStore, body: dict, now: float):
        return store.ingest(parse_alertmanager_payload(body), received_at=now)

    def test_firing_transition_is_idempotent(self) -> None:
        store = IncidentStore(self.db_path, "live")
        first = self._ingest(store, payload("firing"), 100.0)
        repeated = self._ingest(store, payload("firing"), 101.0)

        self.assertEqual(first.opened, 1)
        self.assertEqual(first.notifications_queued, 1)
        self.assertEqual(repeated.repeated, 1)
        self.assertEqual(len(store.fetch_all("incidents")), 1)
        self.assertEqual(len(store.fetch_all("incident_events")), 1)
        outbox = store.fetch_all("notification_outbox")
        self.assertEqual([(row["kind"], row["state"]) for row in outbox], [("down", "pending")])

    def test_orphan_resolved_is_audit_only_and_idempotent(self) -> None:
        store = IncidentStore(self.db_path, "live")
        first = self._ingest(store, payload("resolved"), 100.0)
        repeated = self._ingest(store, payload("resolved"), 101.0)

        self.assertEqual(first.orphan_resolved, 1)
        self.assertEqual(repeated.repeated, 1)
        self.assertEqual(len(store.fetch_all("incidents")), 0)
        events = store.fetch_all("incident_events")
        self.assertEqual([row["transition"] for row in events], ["orphan_resolved"])
        self.assertEqual(store.fetch_all("notification_outbox"), [])
        metrics = store.metrics(worker_up=True, ready=True)
        self.assertIn("incident_gateway_orphan_resolved_total 1", metrics)

    def test_recovery_waits_for_actual_down_delivery(self) -> None:
        store = IncidentStore(self.db_path, "live")
        self._ingest(store, payload("firing"), 100.0)
        result = self._ingest(store, payload("resolved"), 101.0)
        self.assertEqual(result.resolved, 1)
        self.assertEqual(result.notifications_queued, 0)
        self.assertEqual(len(store.fetch_all("notification_outbox")), 1)

        down = store.claim_next(now=102.0)
        self.assertIsNotNone(down)
        self.assertEqual(down.kind, "down")
        store.mark_retry(down, "network", next_attempt_at=200.0)
        self.assertIsNone(store.claim_next(now=103.0))

        down = store.claim_next(now=200.0)
        self.assertEqual(down.kind, "down")
        store.mark_sent(down, "10", sent_at=201.0)
        self.assertEqual(len(store.fetch_all("notification_outbox")), 2)
        recovery = store.claim_next(now=201.0)
        self.assertIsNotNone(recovery)
        self.assertEqual(recovery.kind, "recovery")

    def test_resolved_transition_is_idempotent(self) -> None:
        store = IncidentStore(self.db_path, "live")
        self._ingest(store, payload("firing"), 100.0)
        self._ingest(store, payload("resolved"), 101.0)
        duplicate = self._ingest(store, payload("resolved"), 102.0)
        self.assertEqual(duplicate.repeated, 1)
        transitions = [row["transition"] for row in store.fetch_all("incident_events")]
        self.assertEqual(transitions, ["firing", "resolved"])
        self.assertEqual(len(store.fetch_all("notification_outbox")), 1)

    def test_resolve_after_down_sent_enqueues_recovery_immediately(self) -> None:
        store = IncidentStore(self.db_path, "live")
        self._ingest(store, payload("firing"), 100.0)
        down = store.claim_next(now=101.0)
        self.assertIsNotNone(down)
        store.mark_sent(down, "10", sent_at=102.0)

        resolved = self._ingest(store, payload("resolved"), 103.0)
        self.assertEqual(resolved.notifications_queued, 1)
        recovery = store.claim_next(now=104.0)
        self.assertIsNotNone(recovery)
        self.assertEqual(recovery.kind, "recovery")

    def test_delayed_firing_does_not_reopen_resolved_occurrence(self) -> None:
        store = IncidentStore(self.db_path, "shadow")
        self._ingest(store, payload("firing"), 100.0)
        self._ingest(store, payload("resolved"), 101.0)
        delayed = self._ingest(store, payload("firing"), 102.0)
        self.assertEqual(delayed.repeated, 1)
        self.assertEqual(len(store.fetch_all("incidents")), 1)

        fresh = payload("firing", starts_at="2026-09-07T11:00:00Z")
        reopened = self._ingest(store, fresh, 103.0)
        self.assertEqual(reopened.opened, 1)
        self.assertEqual(len(store.fetch_all("incidents")), 2)

    def test_late_resolve_for_old_occurrence_does_not_close_new_open_incident(self) -> None:
        store = IncidentStore(self.db_path, "shadow")
        old_firing = payload("firing", starts_at="2026-09-07T10:00:00Z")
        old_resolved = payload("resolved", starts_at="2026-09-07T10:00:00Z")
        new_firing = payload("firing", starts_at="2026-09-07T11:00:00Z")

        self._ingest(store, old_firing, 100.0)
        self._ingest(store, old_resolved, 101.0)
        self._ingest(store, new_firing, 102.0)
        late = self._ingest(store, old_resolved, 103.0)
        duplicate_late = self._ingest(store, old_resolved, 104.0)

        self.assertEqual(late.orphan_resolved, 1)
        self.assertEqual(duplicate_late.repeated, 1)
        incidents = store.fetch_all("incidents")
        self.assertEqual([row["state"] for row in incidents], ["resolved", "open"])
        self.assertEqual(incidents[-1]["starts_at"], "2026-09-07T11:00:00Z")
        transitions = [row["transition"] for row in store.fetch_all("incident_events")]
        self.assertEqual(transitions, ["firing", "resolved", "firing", "orphan_resolved"])
        self.assertEqual(store.fetch_all("notification_outbox"), [])

    def test_resolve_without_starts_at_may_close_open_incident(self) -> None:
        store = IncidentStore(self.db_path, "shadow")
        self._ingest(
            store,
            payload("firing", starts_at="2026-09-07T11:00:00Z"),
            100.0,
        )
        ends_only = payload("resolved", starts_at="")
        ends_only["alerts"][0]["endsAt"] = "2026-09-07T11:05:00Z"

        result = self._ingest(store, ends_only, 101.0)

        self.assertEqual(result.resolved, 1)
        self.assertEqual(store.fetch_all("incidents")[0]["state"], "resolved")

    def test_matching_ends_at_does_not_override_mismatched_starts_at(self) -> None:
        store = IncidentStore(self.db_path, "shadow")
        original = payload("firing", starts_at="2026-09-07T10:00:00Z")
        original_resolve = payload("resolved", starts_at="2026-09-07T10:00:00Z")
        self._ingest(store, original, 100.0)
        self._ingest(store, original_resolve, 101.0)

        different_occurrence = payload("resolved", starts_at="2026-09-07T11:00:00Z")
        # The equal endsAt cannot make unequal, present startsAt values equivalent.
        different_occurrence["alerts"][0]["endsAt"] = original_resolve["alerts"][0]["endsAt"]
        result = self._ingest(store, different_occurrence, 102.0)

        self.assertEqual(result.orphan_resolved, 1)
        self.assertEqual(result.repeated, 0)
        transitions = [row["transition"] for row in store.fetch_all("incident_events")]
        self.assertEqual(transitions, ["firing", "resolved", "orphan_resolved"])

    def test_mode_switch_cancels_stale_backlog(self) -> None:
        live = IncidentStore(self.db_path, "live")
        self._ingest(live, payload("firing"), 100.0)
        shadow = IncidentStore(self.db_path, "shadow")
        outbox = shadow.fetch_all("notification_outbox")
        self.assertEqual(outbox[0]["state"], "cancelled_mode_switch")

        live_again = IncidentStore(self.db_path, "live")
        self.assertIsNone(live_again.claim_next(now=1000.0))
        self._ingest(live_again, payload("resolved"), 1001.0)
        self.assertEqual(len(live_again.fetch_all("notification_outbox")), 1)

    def test_shadow_mode_never_enqueues(self) -> None:
        store = IncidentStore(self.db_path, "shadow")
        self._ingest(store, payload("firing"), 100.0)
        self._ingest(store, payload("resolved"), 101.0)
        self.assertEqual(store.fetch_all("notification_outbox"), [])

    def test_incident_events_are_immutable(self) -> None:
        store = IncidentStore(self.db_path, "shadow")
        self._ingest(store, payload("firing"), 100.0)
        connection = sqlite3.connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE incident_events SET transition = 'resolved' WHERE id = 1")
        finally:
            connection.close()

    def test_open_incident_metric_is_aggregated_and_uses_only_bounded_labels(self) -> None:
        store = IncidentStore(self.db_path, "shadow")
        first = payload("firing", fingerprint="first")
        second = payload("firing", fingerprint="second")
        for body in (first, second):
            body["alerts"][0]["labels"]["company"] = 'acme"\ncorp'
            body["alerts"][0]["labels"]["url"] = "https://secret.example/path"
            self._ingest(store, body, 100.0)

        metrics = store.metrics(worker_up=True, ready=True)
        sample = next(
            line for line in metrics.splitlines() if line.startswith("rs_monitoring_open_incident{")
        )
        self.assertEqual(
            sample,
            'rs_monitoring_open_incident{company="acme\\"\\ncorp",alias="cloud",'
            'stack="erp",service="frontend",severity="critical",state="open"} 2',
        )
        self.assertNotIn("fingerprint", sample)
        self.assertNotIn("incident_id=", sample)
        self.assertNotIn("url=", sample)
        self.assertNotIn("secret.example", sample)

        self._ingest(store, payload("resolved", fingerprint="first"), 101.0)
        updated_sample = next(
            line
            for line in store.metrics(worker_up=True, ready=True).splitlines()
            if line.startswith("rs_monitoring_open_incident{")
        )
        self.assertTrue(updated_sample.endswith('state="open"} 1'))


if __name__ == "__main__":
    unittest.main()
