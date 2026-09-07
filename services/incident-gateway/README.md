# Incident Gateway

Small stdlib-only Alertmanager-to-Telegram gateway with an explicit incident
lifecycle. SQLite is the source of truth; an HTTP success is returned only after
the complete webhook transaction commits.

## Guarantees

- One open incident per Alertmanager fingerprint.
- Repeated `firing`/`resolved` transitions are idempotent.
- A resolved alert without an open incident is an immutable
  `orphan_resolved` audit event and never becomes a Telegram message.
- A Recovery outbox row is created only after the matching DOWN item is actually
  marked `sent`. If Telegram is unavailable, DOWN keeps retrying; the resolved
  event waits durably and Recovery is enqueued in the DOWN success transaction.
- Telegram is outbound-only and the sole Bot API method used is `sendMessage`.
- Mode changes cancel every unsent outbox row. Shadow history cannot be replayed
  accidentally after enabling live delivery.
- Immutable event rows are protected against SQL `UPDATE` and `DELETE` by
  triggers. Notification delivery is durable and at-least-once.

## Configuration

The safe default is `GATEWAY_MODE=shadow`.

| Variable | Default |
| --- | --- |
| `GATEWAY_BIND` / `GATEWAY_PORT` | `0.0.0.0` / `8080` |
| `GATEWAY_DATABASE_PATH` | `/var/lib/incident-gateway/incidents.db` |
| `GATEWAY_MODE` | `shadow` (`shadow` or `live`) |
| `WEBHOOK_PATH` | `/api/v1/alerts` |
| `ALERT_WEBHOOK_TOKEN` | unset; optional bearer/header protection |
| `TELEGRAM_BOT_TOKEN` | required for live readiness |
| `TELEGRAM_CHAT_ID` | required for live readiness |
| `TELEGRAM_MESSAGE_THREAD_ID` | unset |
| `RETRY_BASE_SECONDS` / `RETRY_MAX_SECONDS` | `2` / `900` |

`ALERT_WEBHOOK_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and
`TELEGRAM_MESSAGE_THREAD_ID` also support the conventional `_FILE` suffix. Set
either the direct value or the file, never both. Secrets are never returned by
health endpoints or written to logs.

Alertmanager webhook authentication accepts either:

```text
Authorization: Bearer <ALERT_WEBHOOK_TOKEN>
X-Alertmanager-Token: <ALERT_WEBHOOK_TOKEN>
```

## Endpoints

- `POST /api/v1/alerts` — Alertmanager webhook, returns `202` after commit.
- `GET /healthz` — process liveness.
- `GET /readyz` — database/mode/worker/live-credential readiness.
- `GET /metrics` — Prometheus text exposition including orphan resolves and
  durable outbox state. `rs_monitoring_open_incident` aggregates open incidents
  by `company`, `alias`, `stack`, `service`, and `severity`; it never exposes a
  fingerprint, incident ID, URL, or other free-form label.

Minimal Alertmanager receiver:

```yaml
receivers:
  - name: rabbit-incident-gateway
    webhook_configs:
      - url: http://incident-gateway:8080/api/v1/alerts
        send_resolved: true
```

Persist `/var/lib/incident-gateway`. Keep the gateway behind a private network or
authenticated reverse proxy.

## Tests

```sh
python -m unittest discover -s services/incident-gateway/tests -v
```
