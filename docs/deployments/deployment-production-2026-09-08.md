# Central monitoring migration to deployment — 2026-09-08

Status: migration in progress. Do not infer live authority until the dated
verification record at the end is completed. The source is `con`; the destination
is `deployment` (169.58.132.8). Rabbit Platform already runs on the destination.

## Operating layout

The central services use project `monitoring`, external network
`monitoring_default` (172.23.0.0/16), and
`deploy/deployment-monitoring-compose.yml`. The gateway image and delivery mode
are explicit values in the private `/etc/rabbit-monitoring/release.env`.

```sh
docker compose --env-file /etc/rabbit-monitoring/release.env \
  -f /opt/rabbit-monitoring-v2/deploy/deployment-monitoring-compose.yml ps
```

Prometheus, Grafana, Loki, Blackbox, the Greenleaf label proxy, Alertmanager and
the gateway move to the destination. Destination node-exporter and cAdvisor
observe the new host. Grafana's existing encrypted state and encryption key are
preserved. Grafana, Prometheus, Loki and the gateway publish only loopback ports.

`con` retains node-exporter, cAdvisor, SNMP, the standalone Promtail collector,
the Rentall VPN and NAT tunnel endpoints, Nginx and OpenClaw. OpenClaw's Grafana
sender stays paused. Never run `docker compose down` on its old monitoring
project: the retained collectors belong to it.

## Private relay and ingress continuity

The dedicated `monitoring-relay` SSH account on deployment accepts a new key
generated on con. It has no shell sessions, PTY, agent/X11 forwarding or arbitrary
ports. The systemd service on con opens only the declared sockets. Host trust is
pinned from the existing administrative SSH connection. No existing private key
was copied.

| Destination private socket | Source reached through con |
| --- | --- |
| 172.23.0.1:19110 | con node-exporter |
| 172.23.0.1:19111 | con cAdvisor |
| 172.23.0.1:19100 / 19101 | existing NAT test tunnel sockets |
| 172.23.0.1:19116 | con SNMP exporter / Rentall VPN |
| 172.23.0.1:19120 | howbot node-exporter, otherwise unreachable from deployment |
| 172.23.0.1:19182 / 19183 | Rentall Windows exporters through con |

These listeners bind the Docker bridge gateway, never a public interface.
`scripts/render-deployment-monitoring.py` rewrites transport addresses through
Prometheus relabeling while preserving original `instance` labels.

The old `grafana.exemstsc.world` Nginx virtual host retains TLS and existing
ingestion authentication. Only its upstream sockets change:

- Grafana: con localhost:13000 → deployment localhost:3000;
- `/api/v1/write`: con localhost:19090 → deployment localhost:9090;
- `/loki/api/v1/push`: con localhost:13100 → deployment localhost:3100.

The public Grafana/agent URLs therefore remain valid. A separate new branded
domain may be added later without rewriting collector configuration.

## Data handoff and rollback boundary

Source data is about 7.2 GiB Prometheus, 1.8 GiB Loki, 53 MiB Grafana and under
1 MiB incident/checker state. A restricted, write-only rsync key pre-copies to
`/var/lib/rabbit-monitoring-transfer`; this does not authorize deleting source
data. The temporary authorization is removed after the final sync.

Final handoff stops source Alertmanager, verifies an empty delivery outbox,
stops the gateway, then stops the three central data writers and checker timers.
A final stopped-state sync preserves SQLite/WAL/SHM, TSDB/WAL, Loki and Grafana
databases. Record SQLite integrity and lifecycle/outbox counts before upgrading.

The destination gateway starts directly in the source's live delivery generation
after offline schema rehearsal; toggling restored state through shadow would
change its generation. The old source gateway stays stopped. Accepted carryover
incidents are retained and are not replayed as new DOWN notifications.

Schema-v2 gateway databases must not be opened by the old schema-v1 image.
Rollback must first stop the destination sender and either restore the complete
pre-upgrade backup with the matching old image or use the reviewed new image on
the source with the latest stopped-state database. Do not roll back to a stale
database after successful live delivery without reconciling delivered events.

Source service containers, original data, runtime config and encrypted settings
remain available for rollback. No source volume or backup is deleted.

## Verification record

Pending final cutover: record source stop proof; data integrity and lifecycle
counts; destination release revision; gateway generation and readiness; scrape
parity; scheduled checker success; Grafana customer organization isolation;
legacy HTTPS/ingestion route checks; linked DOWN/Recovery canary; no orphan
recoveries or unsent outbox; temporary transfer authorization removal.
