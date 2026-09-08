# Central monitoring migration to deployment — 2026-09-08

Status: applied and verified live on 2026-09-08. The source was `con`; the sole
central monitoring plane is now `deployment` (169.58.132.8), alongside Rabbit
Platform. Source collectors and authenticated legacy ingress remain on `con`.

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

The two retained exporter containers currently use source bridge addresses
172.20.0.2 and 172.20.0.3. The relay pre-start guard checks their identities and
fails closed if a later recreate changes them. Before recreating either source
exporter, stop the relay, reconcile these addresses and update both the guard
and forwarding targets, then restart and verify the exporter labels. These
addresses are operational bindings, not automatically discovered stable IDs.

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

- Runtime release: `d95d22a3468df908b14b024bf0a1b20d53c03d39`; gateway image
  `sha256:c7bd35125accc9838f907fe9ca4660d87147fd8d4b5f6476ec7de75f386c948e`
  has that exact OCI source revision. Later catalog/docs changes do not change
  the gateway artifact.
- Full validator passed: 36 gateway tests, 30 repository tests, 10 Prometheus
  evaluation fixtures, 29 dashboard JSON files, catalog and configuration checks.
- Source Alertmanager stopped first; unsent outbox was zero before gateway stop.
  Seven source central containers remain stopped with `restart=no`. OpenClaw
  processing is still false; three source collector services and Promtail remain.
- Final consistent copy contained 9,336,717,940 bytes. Source and destination
  pre-upgrade SQLite checks both passed, preserving 37 incidents, 49 events,
  two sent outbox rows and live generation 2. Isolated schema upgrade rehearsal
  and production startup preserved that generation and upgraded to schema 2.
- Nine destination monitoring services are running. Gateway, Alertmanager,
  Prometheus, Grafana database and Loki are ready. Prometheus has 36 targets:
  26 up, the same 10 previously down, plus the two new destination exporters.
  `count(up offset 1d)` returned 32 historical series; a Loki count query one
  hour before verification returned 1,741 historical log entries, without
  reading message bodies.
- Controlled canary incident 38 is resolved, with exactly one delivered DOWN
  and one delivered resolution, each with a Telegram message ID. Final check:
  26 accepted carryover incidents open, 12 resolved; two DOWN and two resolution
  outbox rows sent in total; zero unsent rows and zero orphan resolutions.
- Both Grafana organizations, three datasources and existing user hashes were
  preserved. The encryption key was privately transferred with explicit owner
  approval; old plaintext admin password was excluded. Startup reported no
  decryption errors. Greenleaf proxy returns only `company=greenleaf`; a foreign
  company selector is rejected with HTTP 400.
- Existing public Grafana `/api/health` returns HTTP 200. Unauthenticated remote
  write and Loki push still return 401. TLS and existing ingestion credentials
  remain on the original Nginx route; no collector URLs were changed.
- All three post-cutover checker services completed successfully: HTTP in 19s,
  integrity in 27s, service events in 1s. Their timers are enabled on deployment;
  their first scheduled destination triggers were still future at verification.
  All checker/catalog metrics are scraped, including eight inventory servers.
- The restored textfile directory is mode 0755. Nine pre-existing empty,
  unreadable hidden checker `.prom` files on con were moved into the source
  backup; its textfile parse error changed from 1 to 0. Nothing was deleted.
- Temporary write-only rsync authorization was revoked (one exact new key).
  Its private key was archived on con; the permanent restricted relay remains.

Backups: source `/var/backups/rabbit-monitoring-v2/pre-deployment-20260908`,
destination `/var/backups/rabbit-monitoring-v2/pre-cutover-20260908`, and transfer
evidence `/var/lib/rabbit-monitoring-transfer/final-20260908`. Source storage is
retained unchanged; review the rollback window before reclaiming its disk.

The new canonical platform stack is `rabbit-platform` with platform, worker and
database components. Old `rabbit-platform-dev` containers are stopped and are
not managed runtime requirements. External watchdog, real subscription dates,
fresh-evidence incident reconciliation and the ten existing failed scrape paths
remain follow-up work; migration does not establish those missing signals.
