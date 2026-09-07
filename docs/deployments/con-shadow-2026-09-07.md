# con shadow deployment — 2026-09-07

Managed Monitoring v2 was deployed on `con` from commit `6ccc290` in shadow mode. This record contains no credentials.

## Applied scope

- Checkout: `/opt/rabbit-monitoring-v2`.
- Added isolated Compose project `rabbit-monitoring-v2-shadow` with Alertmanager 0.33.1 and the SQLite incident gateway.
- Reused the existing Prometheus, Grafana, Loki and exporters. No second TSDB or Loki was started.
- Gateway and Alertmanager publish only on loopback and join the existing private `monitoring_default` network.
- Gateway uses the OpenClaw Telegram bot credentials through read-only secret files, but `GATEWAY_MODE=shadow` creates no notification outbox and cannot send a message.
- Installed availability, site-integrity and service-event systemd timers. The first integrity cycle checked 13 targets and reported zero current problems.
- Loaded four validated Prometheus rule files and the generated HTTP `file_sd` inventory. Alertmanager and gateway scrape targets were both `up` after reload.
- Provisioned three admin dashboards in Grafana org 1 and three Greenleaf customer dashboards in org 2.

The firing → duplicate firing → resolved smoke test produced one incident, one firing event, one resolved event and zero outbox rows. The production Telegram route was not tested or cut over; the legacy Grafana/OpenClaw route remains authoritative.

## Preserved state and rollback evidence

- The existing `/root/monitoring` data volumes were retained.
- Pre-change Prometheus config/rules: `/var/backups/rabbit-monitoring-v2/pre-prometheus-70cab6a`.
- Pre-change scheduled-checker units: `/var/backups/rabbit-monitoring-v2/pre-v2-70cab6a`.
- Shadow data: `/var/lib/rabbit-monitoring-v2`; initial usage was about 520 KiB.
- The live server-only Blackbox and Loki configurations were not overwritten.
- The OpenClaw checkout at `/opt/helper` was inspected but not modified.

Use the main rollout runbook for routing rollback. Do not delete the incident database as part of rollback.

## Observed blockers before notification cutover

- Root filesystem is 95% used with about 4.0 GiB free. The shadow pair is small, but a parallel Prometheus/Loki deployment is blocked.
- Ten scrape targets are currently down. `rentall-vpn.service` has been failed since 2026-08-31, which explains the current Windows/MikroTik path failures.
- Greenleaf `cloud` node metrics are reachable, but cAdvisor and Docker inventory metrics are absent. Thirteen expected Greenleaf components therefore remain unconfirmed.
- Backup metrics are absent/stale and correctly produce shadow evidence rather than a green status.
- The service-event registry deliberately contains zero entries until real domain/subscription dates and owners are verified.
- Open incidents created in shadow are not replayed when switching to live. They must be reconciled before the controlled cutover.

No production notification cutover should occur until these gaps and the canary gates in `docs/managed-monitoring-v2-runbook.md` are resolved.
