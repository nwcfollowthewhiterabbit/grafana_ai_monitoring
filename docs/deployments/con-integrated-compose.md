# con production deployment and rollback

Status: applied to `con` on 2026-09-07 from commit `1e84d41` and verified live.

This record describes how Alertmanager and the incident gateway moved from the isolated `rabbit-monitoring-v2-shadow` project into the existing `monitoring` project. The deployed layout reuses the same images, configuration, secret files and `/var/lib/rabbit-monitoring-v2` state. It did not recreate or redefine Prometheus, Grafana, Loki or any exporter.

## Applied change record

- The pre-migration state is stored at `/var/backups/rabbit-monitoring-v2/pre-integrated-1e84d41`. It contains both complete bind directories and passed SQLite `integrity_check` with 36 incidents, 46 events and zero outbox rows.
- The isolated project was stopped before the backup. Alertmanager and the gateway then started as `monitoring-alertmanager` and `monitoring-incident-gateway` in project `monitoring`; the eight pre-existing monitoring container IDs did not change.
- The stopped `rabbit-monitoring-v2-shadow` containers were removed without `-v`. `/var/lib/rabbit-monitoring-v2` remained the active state root.
- OpenClaw's API was recreated only with `deploy/openclaw-grafana-paused.override.yml`. It remained healthy and reported `GRAFANA_WEBHOOK_PROCESSING_ENABLED=false`; its Telegram webhook ownership and other bot functions were not changed.
- The gateway entered `live` mode at delivery generation 2 with an empty outbox. Alertmanager and gateway are healthy and both Prometheus scrape targets report `up=1`.
- End-to-end canary incident `37` travelled through Alertmanager and produced exactly one delivered DOWN followed by exactly one delivered Recovery. Both outbox rows have Telegram message IDs and there are no pending/retry rows.
- Grafana 12.0.0 and the `monitoring` application recording metric remained healthy. The scheduled-public-site timer completed an automatic cycle successfully. The site-integrity and service-event units are enabled and passed manual smoke runs; at verification time their first scheduled timer cycles had not yet occurred. Catalog and runtime metrics both report the integrated Alertmanager and gateway as present.
- The post-integration Prometheus inventory contained 34 targets: 24 up and 10 down. The two additional targets are Alertmanager and the gateway.

The cutover deliberately accepted 26 already-known open shadow incidents in generation 1. They were not replayed into Telegram and cannot produce standalone Recovery notifications in generation 2. After each source resolves, a later recurrence opens a new generation-2 incident with the full DOWN → Recovery lifecycle. The accepted carryover was:

| Alert | Count |
| --- | ---: |
| ExpectedComponentMissing | 13 |
| MikroTikSNMPDown | 2 |
| NodeDown | 2 |
| WindowsExporterDown | 2 |
| CadvisorDown | 1 |
| CloudBackupMetricsMissing | 1 |
| CloudBackupMountUnhealthy | 1 |
| CloudERPBackupStale | 1 |
| RootDiskLow | 1 |
| StackMetricsStale | 1 |
| TLSCertificateExpiryCritical | 1 |

The added `StackMetricsStale` inhibition prevents the 13 Greenleaf component-missing symptoms from being delivered as a cascade while Docker inventory is unavailable. At the 2026-09-07 verification point, Prometheus had 28 firing alerts; Alertmanager exposed 13 active alerts and inhibited 15 symptoms: 13 `ExpectedComponentMissing` under `StackMetricsStale`, plus 2 `CadvisorDown` under their corresponding `NodeDown` alerts. Inhibition suppresses delivery; it does not create a Recovery or close the 26 accepted generation-1 incidents. The 13 delivered-eligible problems remain real operational follow-up work, not deployment failures.

Root usage remained 95%; a follow-up check showed about 4.0 GiB free and `RootDiskLow` firing. No extra Prometheus or Loki was deployed. `cloud-backup-metrics.timer` and its service intentionally belong on the Greenleaf `cloud` host and are not installed on `con`; `CloudBackupMetricsMissing` and `CloudBackupMountUnhealthy` remain active until that source path is restored.

## Current operating state

Every production Compose command for the monitoring project must use this exact file set, in this order:

```sh
docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.live.yml
```

OpenClaw must continue using its pause layer while the gateway is live:

```sh
docker compose \
  --project-name openclaw-stack \
  -f /opt/helper/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/openclaw-grafana-paused.override.yml
```

The commands above are prefixes: append an explicit operation and service name. Do not run either prefix by itself, do not run `down` on project `monitoring`, and do not use a partial file set with `--remove-orphans`. A base-only OpenClaw API recreate is also unsafe: it removes the pause flag, re-enables the legacy Grafana sender and can produce duplicate Telegram notifications.

Quick read-only health check:

```sh
curl --fail --silent --show-error http://127.0.0.1:8180/readyz
curl --fail --silent --show-error http://127.0.0.1:9093/-/ready
curl --fail --silent --show-error http://127.0.0.1:9090/api/v1/alertmanagers
docker inspect --format '{{.State.Health.Status}}' openclaw-stack-api-1
docker exec openclaw-stack-api-1 sh -c \
  'test "$GRAFANA_WEBHOOK_PROCESSING_ENABLED" = false'
```

Expected state is gateway `live`, healthy Alertmanager/OpenClaw API, one active Alertmanager discovered by Prometheus, and a silent exit-zero OpenClaw flag check. Timer status must be reported precisely: `enabled` plus a successful manual service run is not the same as an observed scheduled trigger.

## Files and invariants

- Base: `/root/monitoring/docker-compose.yml`.
- Common fail-safe override: `/opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml` (shadow unless the live layer is present).
- Live opt-in: `/opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.live.yml`.
- Legacy sender pause: `/opt/rabbit-monitoring-v2/deploy/openclaw-grafana-paused.override.yml`, layered over `/opt/helper/docker-compose.yml` for the entire period in which the gateway is authoritative.
- Alertmanager config: `/opt/rabbit-monitoring-v2/monitoring/alertmanager/alertmanager.yml`.
- Gateway secrets: the three existing files under `/opt/rabbit-monitoring-v2/monitoring/secrets` mounted individually and read-only at `/run/secrets`.
- State: `/var/lib/rabbit-monitoring-v2/{incident-gateway,alertmanager}`.
- Project and network: `monitoring` and `monitoring_default`.

The base file must be the first `-f` argument and the project name must remain `monitoring`. The common override is always shadow mode. Live delivery is possible only when the live file is included last.

The override has no `build` section and both images use `pull_policy: never`. Stage and verify the exact gateway image in a separate reviewed release step. Deployment must stop if either image is absent; it must not build or pull an unreviewed replacement implicitly.

After integration, always include the common override when managing these two services. Do not run `docker compose down` for the `monitoring` project, and do not run the base file alone with `--remove-orphans`: either action can affect services outside this change.

Likewise, always include the pause override whenever managing or recreating the
OpenClaw API while the gateway is live. Omit it only as the deliberate sender
switch in the documented rollback sequence, after the gateway has returned to
shadow mode.

## Historical migration procedure

The following preflight, move and cutover steps document the applied change and are reusable for a new host. They must not be rerun against the current `con` deployment. Current operators should use the health check above or the rollback section below.

### Preflight

Run as an operator who can read `/root/monitoring` and manage Docker. These checks do not display secret contents.

```sh
docker compose version
docker image inspect --format '{{.Id}} {{.Created}}' rabbitsystems/incident-gateway:0.1.0
docker image inspect --format '{{.Id}} {{.Created}}' quay.io/prometheus/alertmanager:v0.33.1

test -r /opt/rabbit-monitoring-v2/monitoring/alertmanager/alertmanager.yml
test -s /opt/rabbit-monitoring-v2/monitoring/secrets/telegram_bot_token
test -s /opt/rabbit-monitoring-v2/monitoring/secrets/telegram_chat_id
test -s /opt/rabbit-monitoring-v2/monitoring/secrets/telegram_thread_id

stat -c '%a %u:%g %n' \
  /opt/rabbit-monitoring-v2/monitoring/secrets \
  /opt/rabbit-monitoring-v2/monitoring/secrets/telegram_bot_token \
  /opt/rabbit-monitoring-v2/monitoring/secrets/telegram_chat_id \
  /opt/rabbit-monitoring-v2/monitoring/secrets/telegram_thread_id \
  /var/lib/rabbit-monitoring-v2/incident-gateway \
  /var/lib/rabbit-monitoring-v2/alertmanager
```

The secret directory must be traversable by UID/GID `10001:10001`; its three files must be readable by that identity and not world-readable. The state directories must remain writable by `10001:10001` for the gateway and `65534:65534` for Alertmanager.

Inspect the deployed base before merging:

```sh
docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  config --services
```

Abort and reconcile the files if this base already declares `alertmanager` or `incident-gateway`. The integrated override is for the audited live base in which those services are absent; it must not be layered over a second definition accidentally.

Validate the exact shadow merge without starting anything:

```sh
docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  config --quiet
```

Also validate the reversible OpenClaw API override. This reads the existing `/opt/helper/.env` for Compose interpolation but prints no values:

```sh
docker compose \
  --project-name openclaw-stack \
  -f /opt/helper/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/openclaw-grafana-paused.override.yml \
  config --quiet
```

For a new-host migration, inspect the isolated pair and require healthy shadow
state, no notification rows and no unexplained open shadow incidents before the
move:

```sh
docker compose \
  -f /opt/rabbit-monitoring-v2/deploy/con-shadow-compose.yml \
  ps alertmanager incident-gateway
curl --fail --silent --show-error http://127.0.0.1:8180/readyz
curl --fail --silent --show-error http://127.0.0.1:8180/metrics
curl --fail --silent --show-error http://127.0.0.1:9093/-/ready
```

### Move the shadow pair into the monitoring project

Choose a new, explicit backup path ending in the approved change ID. Refuse to continue if it already exists. Stop both isolated containers before copying SQLite/WAL and Alertmanager state.

```sh
test ! -e /var/backups/rabbit-monitoring-v2/pre-integrated-CHANGE_ID

docker compose \
  -f /opt/rabbit-monitoring-v2/deploy/con-shadow-compose.yml \
  stop alertmanager incident-gateway

install -d -m 0700 /var/backups/rabbit-monitoring-v2/pre-integrated-CHANGE_ID
cp -a \
  /var/lib/rabbit-monitoring-v2/incident-gateway \
  /var/lib/rabbit-monitoring-v2/alertmanager \
  /var/backups/rabbit-monitoring-v2/pre-integrated-CHANGE_ID/
```

Start only the two added services. `--no-build` is mandatory; the override also prevents pulls.

```sh
docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  up -d --no-build incident-gateway alertmanager
```

Verify that existing services were not recreated, the pair is healthy, and gateway mode remains shadow:

```sh
docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  ps incident-gateway alertmanager

curl --fail --silent --show-error http://127.0.0.1:8180/readyz
curl --fail --silent --show-error http://127.0.0.1:8180/metrics
curl --fail --silent --show-error http://127.0.0.1:9093/-/ready
curl --fail --silent --show-error http://127.0.0.1:9090/api/v1/alertmanagers
```

The readiness payload and metrics must report `shadow`; `notification_outbox` metrics must remain empty/zero. Prometheus must discover the integrated `alertmanager:9093` endpoint. Keep the stopped isolated containers until this observation period passes; do not start both projects together because they share ports, aliases and state.

### Shadow to live cutover

Before this sequence, complete the separate test-destination canary in the main runbook. Reconcile every open shadow incident and record the gateway database backup path, image ID and legacy Grafana/OpenClaw route. A mode switch intentionally does not replay shadow incidents.

1. Stop integrated Alertmanager to freeze v2 ingress while changing senders.
2. Recreate only the OpenClaw API with the paused override. Grafana rules and routing stay configured, but OpenClaw accepts their webhook without processing it or sending Telegram.
3. Require the OpenClaw API container to be healthy and verify the non-secret processing flag is exactly `false`.
4. Recreate only the gateway with the live file included and require `/readyz` to report live/ready.
5. Start Alertmanager with the same live file set.
6. Trigger one unique controlled firing/resolved occurrence, then expand routing gradually.

```sh
docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  stop alertmanager

docker compose \
  --project-name openclaw-stack \
  -f /opt/helper/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/openclaw-grafana-paused.override.yml \
  up -d --no-build --no-deps --force-recreate api

docker inspect --format '{{.State.Health.Status}}' openclaw-stack-api-1
docker exec openclaw-stack-api-1 sh -c 'test "$GRAFANA_WEBHOOK_PROCESSING_ENABLED" = false'

docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.live.yml \
  up -d --no-build --no-deps --force-recreate incident-gateway

curl --fail --silent --show-error http://127.0.0.1:8180/readyz

docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.live.yml \
  up -d --no-build alertmanager
```

Do not start Alertmanager if gateway readiness is false, its mode is not `live`, the OpenClaw API is unhealthy, or its processing flag is not `false`. The `docker exec ... test` command is intentionally silent on success and never displays other environment values. For all later live maintenance commands, include both the common override and live file; omitting the live file during a gateway recreation switches it back to shadow and cancels unsent work.

## Notification rollback

Rollback sender state without deleting the database:

1. Stop Alertmanager so no new gateway events arrive.
2. Recreate only the gateway from the common override, without the live file. This switches it to shadow and retains unsent rows as `cancelled_mode_switch`.
3. Recreate only the OpenClaw API from its base Compose file, omitting the paused override. This restores the already configured Grafana/OpenClaw route without editing its rules or policy.
4. Restart Alertmanager in shadow only if continued v2 observation is useful.
5. Reconcile any generation whose DOWN was delivered but whose Recovery was cancelled; never fabricate a Recovery or delete the audit rows.

```sh
docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.live.yml \
  stop alertmanager

docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  up -d --no-build --no-deps --force-recreate incident-gateway

curl --fail --silent --show-error http://127.0.0.1:8180/readyz

docker compose \
  --project-name openclaw-stack \
  -f /opt/helper/docker-compose.yml \
  up -d --no-build --no-deps --force-recreate api

docker inspect --format '{{.State.Health.Status}}' openclaw-stack-api-1
docker exec openclaw-stack-api-1 sh -c 'test "${GRAFANA_WEBHOOK_PROCESSING_ENABLED:-true}" = true'

docker compose \
  --project-name monitoring \
  --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  up -d --no-build alertmanager
```

If the integrated layout itself must be rolled back, stop only `alertmanager` and `incident-gateway` with the integrated file set, then start `deploy/con-shadow-compose.yml` in shadow mode. Both layouts reuse `/var/lib/rabbit-monitoring-v2`; they must never run simultaneously. Do not use `docker compose down` on the `monitoring` project and do not remove either state directory as part of rollback.
