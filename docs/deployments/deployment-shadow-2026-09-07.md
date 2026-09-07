# deployment shadow stage — 2026-09-07

Status: applied and verified in shadow mode on `deployment` (`vmi3489272`).

This record contains no credentials. It documents a reversible staging step;
production alert routing and Telegram delivery remain on `con`.

## Source and scope

- Source branch: `feat/managed-monitoring-v2`.
- Source commit: `cbd407f172cf709d83c2ace8c880e9ad1618d369`.
- Checkout: `/opt/rabbit-monitoring-v2`.
- Compose project: `rabbit-monitoring-v2-shadow`.
- Services started: only `incident-gateway` and `alertmanager`.
- Persistent state: `/var/lib/rabbit-monitoring-v2/{incident-gateway,alertmanager}`.
- Published endpoints: loopback-only `127.0.0.1:8180` and
  `127.0.0.1:9093`.
- Private Docker network: newly created `monitoring_default`; at verification it
  contained only the two shadow containers.

No production SQLite/Alertmanager state or Telegram secret was copied. The
checkout's `monitoring/secrets` directory contains only `.gitkeep`. No
Prometheus, Grafana, Loki, exporter, timer, DNS, public ingress or production
route was added on this host.

## Validation evidence

`scripts/validate-repository.sh` completed successfully on the target host:

- 22 Python files compiled;
- 23 incident-gateway tests passed;
- 20 repository/deployment tests passed;
- the service catalog validated with 3 companies, 7 servers, 41 applications,
  67 components and 13 HTTP services;
- generated Prometheus targets and 29 Grafana dashboards validated without
  drift;
- all repository Compose combinations rendered successfully;
- Prometheus configuration and all four rule files passed `promtool`;
- Alertmanager configuration passed `amtool`.

The deployed images were:

| Service | Image | Target-host image ID |
| --- | --- | --- |
| Incident gateway | `rabbitsystems/incident-gateway:0.1.0` | `sha256:892ce986ece0c5f88b5c92eb9387940364742358296b721e8172736dde1f9eaf` |
| Alertmanager | `quay.io/prometheus/alertmanager:v0.33.1` | `sha256:9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d` |

Both containers became healthy. Runtime checks returned:

```json
{"status":"ready","mode":"shadow","database":"ok","telegram_configured":false,"worker":"up"}
```

Alertmanager's `/-/ready` endpoint returned `OK`.

## Safety boundary and next stage

This host is not a production sender. Do not add the live override, Telegram
credentials or a production Prometheus route as an incidental follow-up.

Before a future cutover, prepare a reviewed change window and preserve the
current `con` incident history. The live database on `con` contains accepted
generation-1 shadow carryover incidents. Connecting a fresh database directly
to production alerts can reinterpret known conditions as new DOWN events and
produce a notification burst.

A later migration therefore needs all of the following:

1. capture and compare the exact active alert set on `con`;
2. stop state writers and copy SQLite, WAL/SHM when present, and Alertmanager
   state as one consistent handoff;
3. run SQLite integrity checks and compare table/row counts on both sides;
4. keep both gateways in shadow while reconciling active fingerprints and mode
   generation;
5. prove that only one Telegram sender can be live;
6. switch routing and sender ownership in the documented order, run a controlled
   DOWN → Recovery canary, and retain a tested rollback path.

Until that explicit cutover, `con` remains the authoritative live monitoring and
Telegram sender.
