# con integrated Compose deployment

Status: prepared in the repository, not applied to `con` by this document change.

This procedure moves the already deployed Alertmanager and incident gateway from the isolated `rabbit-monitoring-v2-shadow` Compose project into the existing `monitoring` project. It reuses the same images, configuration, secret files and `/var/lib/rabbit-monitoring-v2` state. It does not recreate or redefine Prometheus, Grafana, Loki or any exporter.

## Files and invariants

- Base: `/root/monitoring/docker-compose.yml`.
- Shadow override: `/opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml`.
- Live opt-in: `/opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.live.yml`.
- Legacy sender pause: `/opt/rabbit-monitoring-v2/deploy/openclaw-grafana-paused.override.yml`, layered over `/opt/helper/docker-compose.yml` only during cutover.
- Alertmanager config: `/opt/rabbit-monitoring-v2/monitoring/alertmanager/alertmanager.yml`.
- Gateway secrets: the three existing files under `/opt/rabbit-monitoring-v2/monitoring/secrets` mounted individually and read-only at `/run/secrets`.
- State: `/var/lib/rabbit-monitoring-v2/{incident-gateway,alertmanager}`.
- Project and network: `monitoring` and `monitoring_default`.

The base file must be the first `-f` argument and the project name must remain `monitoring`. The common override is always shadow mode. Live delivery is possible only when the live file is included last.

The override has no `build` section and both images use `pull_policy: never`. Stage and verify the exact gateway image in a separate reviewed release step. Deployment must stop if either image is absent; it must not build or pull an unreviewed replacement implicitly.

After integration, always include the common override when managing these two services. Do not run `docker compose down` for the `monitoring` project, and do not run the base file alone with `--remove-orphans`: either action can affect services outside this change.

## Preflight

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

Inspect the current isolated pair and require healthy shadow state, no notification rows and no unexplained open shadow incidents before migration:

```sh
docker compose \
  -f /opt/rabbit-monitoring-v2/deploy/con-shadow-compose.yml \
  ps alertmanager incident-gateway
curl --fail --silent --show-error http://127.0.0.1:8180/readyz
curl --fail --silent --show-error http://127.0.0.1:8180/metrics
curl --fail --silent --show-error http://127.0.0.1:9093/-/ready
```

## Move the shadow pair into the monitoring project

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

## Shadow to live cutover

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
